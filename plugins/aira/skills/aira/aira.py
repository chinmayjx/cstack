#!/usr/bin/env python3
"""aira — CLI for Capillary AIRA. Talks to a local daemon over UDS for chat;
the daemon holds one persistent WebSocket to the AIRA backend."""

import argparse
import asyncio
import getpass
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Cluster name -> intouch base URL. Add new clusters here as they come online.
CLUSTERS = {
    "nightly": "https://nightly.intouch.capillarytech.com",
}
DEFAULT_CLUSTER = "nightly"
STATE_DIR = Path.home() / ".aira"
CREDENTIALS_PATH = STATE_DIR / "credentials.json"
SOCK_PATH = STATE_DIR / "daemon.sock"
PID_PATH = STATE_DIR / "daemon.pid"
LOG_PATH = STATE_DIR / "daemon.log"


def _ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_credentials():
    if not CREDENTIALS_PATH.exists():
        sys.exit("Not logged in. Run: aira login -u <user> -p <pass> --org-id <id>")
    return json.loads(CREDENTIALS_PATH.read_text())


def _auth_headers(creds):
    return {
        "Authorization": f"Bearer {creds['token']}",
        "x-cap-api-auth-org-id": str(creds["org_id"]),
        "User-Agent": "aira-cli/0.1",
    }


def _ws_url(creds, session_id):
    base = creds["host"].replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/ask-aira/copilot/chat/{session_id}"


# --- login ------------------------------------------------------------------


def cmd_login(args):
    # CLI flags win; otherwise fall back to the AIRA_* environment variables.
    username = args.username or os.environ.get("AIRA_USERNAME")
    password = args.password or os.environ.get("AIRA_PASSWORD")
    org_id = args.org_id or os.environ.get("AIRA_ORG_ID")
    cluster = args.cluster or os.environ.get("AIRA_CLUSTER") or DEFAULT_CLUSTER

    if not username:
        sys.exit("no username: pass -u or set $AIRA_USERNAME")
    if not org_id:
        sys.exit("no org id: pass --org-id or set $AIRA_ORG_ID")
    if cluster not in CLUSTERS:
        sys.exit(f"unknown cluster '{cluster}'. known clusters: {', '.join(CLUSTERS)}")
    host = CLUSTERS[cluster]

    if not password:
        password = getpass.getpass("Password: ")

    payload = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{host}/arya/api/v1/auth/login",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "aira-cli/0.1",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(
            f"login failed: {e.code} {e.reason}\n{e.read().decode(errors='ignore')}"
        )
    except urllib.error.URLError as e:
        sys.exit(f"could not reach {host}: {e.reason}")

    token = body.get("token")
    if not token:
        sys.exit(f"login response missing token: {body}")

    _ensure_state_dir()
    CREDENTIALS_PATH.write_text(
        json.dumps(
            {
                "username": username,
                "token": token,
                "org_id": org_id,
                "cluster": cluster,
                "host": host,
            },
            indent=2,
        )
    )
    CREDENTIALS_PATH.chmod(0o600)
    print(f"logged in as {username} (org {org_id}, cluster {cluster})")


# --- session create ---------------------------------------------------------


def cmd_session_create(args):
    creds = _load_credentials()
    url = f"{creds['host']}/ask-aira/copilot/session/create"
    payload = json.dumps({"first_message": args.first_message}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={**_auth_headers(creds), "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        sys.exit(
            f"session create failed: {e.code} {e.reason}\n{e.read().decode(errors='ignore')}"
        )

    sys.stderr.write(f"created session: {body['session_name']}\n")
    sys.stderr.flush()
    # session_id alone goes to stdout so it can be captured / piped.
    print(body["session_id"])


# --- chat (CLI side) --------------------------------------------------------


def _daemon_alive():
    if not SOCK_PATH.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.connect(str(SOCK_PATH))
        return True
    except OSError:
        return False


def _spawn_daemon():
    _ensure_state_dir()
    log = open(LOG_PATH, "ab")
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "daemon"],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _wait_for_daemon(timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _daemon_alive():
            return True
        time.sleep(0.1)
    return False


class _Tee:
    """Mirror every write to a real stream and to the session log file, so the
    user can tail the log while Claude still sees the output inline."""

    def __init__(self, stream, logfile):
        self._stream = stream
        self._logfile = logfile

    def write(self, data):
        self._stream.write(data)
        self._logfile.write(data)
        return len(data)

    def flush(self):
        self._stream.flush()
        self._logfile.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def _open_session_log(session_id: str, message: str):
    log_dir = STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{session_id}.log"
    logfile = path.open("a", encoding="utf-8")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    logfile.write(f"\n===== {stamp} | > {message} =====\n")
    logfile.flush()
    return logfile, path


def cmd_chat(args):
    _load_credentials()

    if not _daemon_alive():
        _spawn_daemon()
        if not _wait_for_daemon():
            sys.exit(f"daemon did not start; check {LOG_PATH}")

    state: dict = {
        "artifacts": {},
        "last_was_text": False,
        "session_id": args.session_id,
    }

    logfile, log_path = _open_session_log(args.session_id, args.message)
    real_stdout, real_stderr = sys.stdout, sys.stderr
    sys.stdout = _Tee(real_stdout, logfile)
    sys.stderr = _Tee(real_stderr, logfile)
    sys.stderr.write(f"[session log: {log_path}]\n")
    sys.stderr.flush()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(str(SOCK_PATH))
            s.sendall(
                (
                    json.dumps(
                        {
                            "type": "chat",
                            "session_id": args.session_id,
                            "message": args.message,
                        }
                    )
                    + "\n"
                ).encode()
            )
            f = s.makefile("rb")
            for raw in f:
                line = raw.decode(errors="replace").rstrip("\n")
                if not line:
                    continue
                if args.raw:
                    print(line)
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                _render_ws_message(msg, state)

        _finish_stream(state)
    finally:
        sys.stdout, sys.stderr = real_stdout, real_stderr
        logfile.close()


def _render_ws_message(msg: dict, state: dict) -> None:
    t = msg.get("type")

    if t == "CONTENT_BLOCK":
        content = msg.get("content") or {}
        ctype = content.get("type")
        if ctype == "TEXT":
            sys.stdout.write(content.get("text", ""))
            sys.stdout.flush()
            state["last_was_text"] = True
            return
        if ctype == "ARTIFACT":
            _on_artifact_card(content, state)
        return

    if t == "ARTIFACT_RESPONSE":
        _on_artifact_response(msg.get("version_id"), msg.get("response") or {}, state)
        return

    if t == "ERROR":
        _break_text_line(state)
        err = msg.get("error") or msg.get("message") or msg
        sys.stderr.write(f"[error: {err}]\n")
        sys.stderr.flush()
        return

    # STATUS, TODO_LIST, COMPLETE, etc. — ignored in the rendered view.


def _on_artifact_card(content: dict, state: dict) -> None:
    version_id = content.get("version_id")
    if not version_id:
        return
    artifact_inner = content.get("artifact") or {}
    sub = artifact_inner.get("type")
    name = content.get("name") or "Artifact"

    _break_text_line(state)

    if sub == "PYTHON_SHELL":
        cell_number = artifact_inner.get("cell_number")
        sys.stdout.write(f"\n──── Python Cell {cell_number}: {name} ────\nCode:\n")
        sys.stdout.flush()
        state["artifacts"][version_id] = {"kind": "python_shell", "card": content}
        return

    # Config (CONFIGURATION / INFERENCE) and anything else — buffer until ready.
    state["artifacts"][version_id] = {
        "kind": "config",
        "card": content,
        "inference": None,
        "error": None,
        "printed": False,
    }
    sys.stderr.write(f"[building artifact: {name}]\n")
    sys.stderr.flush()


def _on_artifact_response(version_id: str | None, response: dict, state: dict) -> None:
    if not version_id:
        return
    artifact = state["artifacts"].get(version_id)
    if artifact is None:
        return
    rtype = response.get("type")
    kind = artifact["kind"]

    if kind == "python_shell":
        _on_python_shell_response(version_id, artifact, rtype, response, state)
        return

    # config
    if rtype == "INFERENCE":
        artifact["inference"] = response
        _break_text_line(state)
        _print_config_artifact(artifact)
        artifact["printed"] = True
    elif rtype == "ERROR":
        artifact["error"] = response.get("error") or response
        _break_text_line(state)
        sys.stderr.write(
            f"[artifact error: {artifact['card'].get('name')}: {artifact['error']}]\n"
        )
        sys.stderr.flush()
        artifact["printed"] = True


def _on_python_shell_response(
    version_id: str,
    artifact: dict,
    rtype: str | None,
    response: dict,
    state: dict,
) -> None:
    if rtype == "PYTHON_SHELL_CHUNK":
        sys.stdout.write(response.get("chunk", ""))
        sys.stdout.flush()
        return
    if rtype == "PYTHON_SHELL_COMPLETE":
        sys.stdout.write("\n\nOutput:\n")
        sys.stdout.flush()
        return
    if rtype == "PYTHON_SHELL_OUTPUT_COMPLETE":
        sys.stdout.write("──── end cell ────\n\n")
        sys.stdout.flush()
        state["last_was_text"] = False
        return
    _print_shell_output(version_id, artifact, rtype, response, state)


def _print_shell_output(
    version_id: str,
    artifact: dict,
    rtype: str | None,
    response: dict,
    state: dict,
) -> None:
    if rtype == "TEXT":
        text = response.get("text", "")
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        return
    if rtype == "TABLE":
        sys.stdout.write(_format_table(response.get("content") or {}) + "\n")
        sys.stdout.flush()
        return
    if rtype == "ERROR":
        sys.stdout.write(f"[error] {response.get('error', '')}\n")
        sys.stdout.flush()
        return
    if rtype == "MARKDOWN":
        sys.stdout.write(response.get("markdown", "") + "\n")
        sys.stdout.flush()
        return
    if rtype == "SVG":
        path = _save_artifact_output(
            version_id, artifact, state, ext=".svg", text=response.get("svg", "")
        )
        sys.stdout.write(f"[plot saved: {path}]\n")
        sys.stdout.flush()
        return
    if rtype == "PDF":
        import base64

        try:
            data = base64.b64decode(response.get("pdf_base64", ""))
        except Exception as e:
            sys.stdout.write(f"[PDF decode failed: {e}]\n")
            sys.stdout.flush()
            return
        path = _save_artifact_output(
            version_id,
            artifact,
            state,
            ext=".pdf",
            data=data,
            original_filename=response.get("filename"),
        )
        sys.stdout.write(f"[PDF saved: {path}]\n")
        sys.stdout.flush()
        return
    sys.stdout.write(json.dumps(response, indent=2) + "\n")
    sys.stdout.flush()


def _save_artifact_output(
    version_id: str,
    artifact: dict,
    state: dict,
    *,
    ext: str,
    text: str | None = None,
    data: bytes | None = None,
    original_filename: str | None = None,
) -> Path:
    session_id = state.get("session_id") or "unknown_session"
    out_dir = STATE_DIR / "outputs" / session_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact["output_count"] = artifact.get("output_count", 0) + 1
    n = artifact["output_count"]
    if original_filename:
        stem = Path(original_filename).stem
        suffix = Path(original_filename).suffix or ext
        path = out_dir / f"{version_id}-{n}-{stem}{suffix}"
    else:
        path = out_dir / f"{version_id}-{n}{ext}"
    if data is not None:
        path.write_bytes(data)
    elif text is not None:
        path.write_text(text)
    return path


def _format_table(content: dict) -> str:
    rows = content.get("rows") or []
    columns = content.get("columns") or []
    if not rows:
        return "(empty)"
    if isinstance(rows[0], dict):
        if not columns:
            columns = list(rows[0].keys())
        dict_rows = rows
    else:
        if not columns:
            columns = [f"col{i}" for i in range(len(rows[0]))]
        dict_rows = [dict(zip(columns, r)) for r in rows]

    widths = {c: len(str(c)) for c in columns}
    for r in dict_rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))

    header = "| " + " | ".join(str(c).ljust(widths[c]) for c in columns) + " |"
    sep = "|" + "|".join("-" * (widths[c] + 2) for c in columns) + "|"
    body = "\n".join(
        "| " + " | ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns) + " |"
        for r in dict_rows
    )
    return f"{header}\n{sep}\n{body}"


def _break_text_line(state: dict) -> None:
    if state["last_was_text"]:
        sys.stdout.write("\n")
        sys.stdout.flush()
        state["last_was_text"] = False


def _print_config_artifact(artifact: dict) -> None:
    card = artifact["card"]
    inference = artifact.get("inference") or {}
    name = card.get("name") or "Artifact"
    config = inference.get("inference")
    tips = inference.get("tips") or []
    blockers = inference.get("blockers") or []

    print()
    print(f"─── Artifact: {name} ───")
    if config is not None:
        print(json.dumps(config, indent=2))
    if tips:
        print("Tips:")
        for tip in tips:
            print(f"  • {tip}")
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"  • {blocker}")
    print("─── end artifact ───")
    print()
    sys.stdout.flush()


def _finish_stream(state: dict) -> None:
    _break_text_line(state)
    for artifact in state["artifacts"].values():
        if artifact.get("kind") != "config":
            continue
        if not artifact.get("printed"):
            sys.stderr.write(
                f"[artifact never finalized: {artifact['card'].get('name')}]\n"
            )
            sys.stderr.flush()


# --- daemon ----------------------------------------------------------------


async def daemon_main():
    creds = _load_credentials()
    hdrs = _auth_headers(creds)

    try:
        from websockets.asyncio.client import connect as ws_connect
        from websockets.exceptions import ConnectionClosed
        from websockets.protocol import State
    except ImportError:
        sys.exit("daemon requires 'websockets'. Install with: pip install websockets")

    _ensure_state_dir()
    SOCK_PATH.unlink(missing_ok=True)
    PID_PATH.write_text(str(os.getpid()))

    stop_event = asyncio.Event()

    def _signal_handler():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    # session_id -> {"ws": ws|None, "lock": asyncio.Lock(), "ws_url": str}
    sessions: dict = {}
    sessions_lock = asyncio.Lock()

    async def get_session(session_id: str):
        async with sessions_lock:
            state = sessions.get(session_id)
            if state is None:
                state = {
                    "ws": None,
                    "lock": asyncio.Lock(),
                    "ws_url": _ws_url(creds, session_id),
                }
                sessions[session_id] = state
            return state

    async def ensure_ws(session_id: str, state: dict):
        """Caller must hold state['lock']. Returns a live WS or raises."""
        existing = state["ws"]
        if existing is not None and existing.state == State.OPEN:
            return existing
        if existing is not None:
            try:
                await existing.close()
            except Exception:
                pass
        state["ws"] = None
        print(f"[daemon] connecting session {session_id}", flush=True)
        # ping_interval=None matches the browser's WS behavior: no client-side
        # pings. AIRA's event loop can lag during heavy operations (LLM streams,
        # Databricks startup) and miss pong deadlines even though the WS is fine.
        new_ws = await ws_connect(
            state["ws_url"], additional_headers=hdrs, ping_interval=None
        )
        state["ws"] = new_ws
        print(f"[daemon] session {session_id} WS open", flush=True)
        return new_ws

    async def _write_safe(writer, payload: bytes) -> bool:
        try:
            writer.write(payload)
            await writer.drain()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    async def handle_client(reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            req = json.loads(line.decode())
            if req.get("type") != "chat":
                return
            session_id = req.get("session_id")
            if not session_id:
                await _write_safe(
                    writer,
                    json.dumps(
                        {"type": "ERROR", "error": "session_id is required"}
                    ).encode()
                    + b"\n",
                )
                return

            state = await get_session(session_id)
            payload = json.dumps({"type": "TEXT", "message": req["message"]})

            async with state["lock"]:
                # Pre-flight: ensure a live WS and send. Retry ONCE on a dead WS.
                ws = None
                send_ok = False
                for attempt in range(2):
                    try:
                        ws = await ensure_ws(session_id, state)
                        await ws.send(payload)
                        send_ok = True
                        break
                    except (ConnectionClosed, OSError, TimeoutError) as e:
                        print(
                            f"[daemon] send failed for session {session_id} "
                            f"(attempt {attempt + 1}): {e}",
                            flush=True,
                        )
                        state["ws"] = None
                        if attempt == 1:
                            await _write_safe(
                                writer,
                                json.dumps(
                                    {
                                        "type": "ERROR",
                                        "error": f"WS connect/send failed: {e}",
                                    }
                                ).encode()
                                + b"\n",
                            )
                            return

                if not send_ok or ws is None:
                    return

                client_ok = True
                while True:
                    try:
                        raw = await ws.recv()
                    except ConnectionClosed as e:
                        print(
                            f"[daemon] session {session_id} WS dropped mid-response: {e}",
                            flush=True,
                        )
                        state["ws"] = None
                        if client_ok:
                            await _write_safe(
                                writer,
                                json.dumps(
                                    {
                                        "type": "ERROR",
                                        "error": f"WS dropped mid-response: {e}",
                                    }
                                ).encode()
                                + b"\n",
                            )
                        break

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = {}

                    if client_ok:
                        if not await _write_safe(writer, raw.encode() + b"\n"):
                            client_ok = False
                    if msg.get("type") == "COMPLETE":
                        break
        except Exception as e:
            print(f"[daemon] client handler error: {e}", flush=True)
            await _write_safe(
                writer,
                json.dumps({"type": "ERROR", "error": str(e)}).encode() + b"\n",
            )
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    print("[daemon] starting", flush=True)
    server = await asyncio.start_unix_server(handle_client, path=str(SOCK_PATH))
    SOCK_PATH.chmod(0o600)
    print(f"[daemon] listening on {SOCK_PATH}", flush=True)
    async with server:
        stop_task = asyncio.create_task(stop_event.wait())
        serve_task = asyncio.create_task(server.serve_forever())
        await asyncio.wait([stop_task, serve_task], return_when=asyncio.FIRST_COMPLETED)
        server.close()
        await server.wait_closed()

    for sid, state in sessions.items():
        if state["ws"] is not None:
            try:
                await state["ws"].close()
            except Exception:
                pass

    print("[daemon] shutting down", flush=True)


def cmd_daemon(args):
    try:
        asyncio.run(daemon_main())
    finally:
        PID_PATH.unlink(missing_ok=True)
        SOCK_PATH.unlink(missing_ok=True)


def _kill_daemon(quiet=False):
    if not PID_PATH.exists():
        if not quiet:
            print("daemon not running")
        return
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        if not quiet:
            print(f"sent SIGTERM to daemon {pid}")
    except (ValueError, ProcessLookupError):
        PID_PATH.unlink(missing_ok=True)
        if not quiet:
            print("daemon process not found (stale pidfile)")


def cmd_daemon_stop(args):
    _kill_daemon()


# --- entrypoint -------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(prog="aira", description="Capillary AIRA CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="Authenticate and store credentials.")
    p_login.add_argument("-u", "--username", help="Defaults to $AIRA_USERNAME.")
    p_login.add_argument(
        "-p", "--password", help="Defaults to $AIRA_PASSWORD, else prompts."
    )
    p_login.add_argument("--org-id", help="Defaults to $AIRA_ORG_ID.")
    p_login.add_argument(
        "--cluster",
        help=f"Cluster to target. Defaults to $AIRA_CLUSTER, else '{DEFAULT_CLUSTER}'. "
        f"Known: {', '.join(CLUSTERS)}.",
    )
    p_login.set_defaults(func=cmd_login)

    p_session = sub.add_parser("session", help="Session management.")
    p_session_sub = p_session.add_subparsers(dest="session_cmd", required=True)
    p_session_create = p_session_sub.add_parser(
        "create", help="Create a new AIRA session."
    )
    p_session_create.add_argument("--first-message", default="session start")
    p_session_create.set_defaults(func=cmd_session_create)

    p_chat = sub.add_parser("chat", help="Send a message to an AIRA session.")
    p_chat.add_argument("message", help="Message text to send.")
    p_chat.add_argument(
        "--session-id",
        required=True,
        help="Session id returned by 'aira session create'.",
    )
    p_chat.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON frames from the WS instead of the rendered view.",
    )
    p_chat.set_defaults(func=cmd_chat)

    p_daemon = sub.add_parser("daemon", help="Run the daemon (used internally).")
    p_daemon.set_defaults(func=cmd_daemon)

    p_daemon_stop = sub.add_parser("daemon-stop", help="Stop the daemon.")
    p_daemon_stop.set_defaults(func=cmd_daemon_stop)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
