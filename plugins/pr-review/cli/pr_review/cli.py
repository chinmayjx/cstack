"""pr-review CLI entry point.

The CLI is a thin client: it talks to the daemon over local HTTP loopback.
The daemon owns all state. See ARCHITECTURE.md for the full design.

Subcommands implemented so far:

    daemon {start, stop, status}    — control the long-running daemon process

Subcommands still stubbed (filled in by subsequent slices):

    init, draft, show, status, stop
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from pr_review import daemon


def _stub(name: str):
    def handler(args: argparse.Namespace) -> int:
        print(f"[pr-review {name}] not yet implemented; args={vars(args)}", file=sys.stderr)
        return 2

    return handler


def cmd_init(args: argparse.Namespace) -> int:
    return _stub("init")(args)


def cmd_draft(args: argparse.Namespace) -> int:
    return _stub("draft")(args)


def cmd_show(args: argparse.Namespace) -> int:
    return _stub("show")(args)


def cmd_status(args: argparse.Namespace) -> int:
    return _stub("status")(args)


def cmd_stop(args: argparse.Namespace) -> int:
    return _stub("stop")(args)


def _daemon_url(path: str) -> str | None:
    rv = daemon.read_rendezvous()
    if rv is None:
        return None
    return f"http://127.0.0.1:{rv['port']}{path}"


def _daemon_get(path: str, timeout: float = 2.0) -> tuple[int, dict] | None:
    url = _daemon_url(path)
    if url is None:
        return None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        return None


def _daemon_post(path: str, body: dict | None = None, timeout: float = 2.0) -> tuple[int, dict] | None:
    url = _daemon_url(path)
    if url is None:
        return None
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except (urllib.error.URLError, OSError):
        return None


def cmd_daemon(args: argparse.Namespace) -> int:
    if args.action == "status":
        result = _daemon_get("/health")
        if result is None:
            print("daemon: not running")
            return 1
        status, body = result
        print(f"daemon: running on port {daemon.read_rendezvous()['port']}")
        print(f"  pid:      {body.get('pid')}")
        print(f"  uptime_s: {body.get('uptime_s')}")
        print(f"  idle_s:   {body.get('idle_s')}")
        print(f"  version:  {body.get('version')}")
        return 0

    if args.action == "stop":
        result = _daemon_post("/shutdown")
        if result is None:
            print("daemon: not running (nothing to stop)")
            return 1
        print("daemon: shutdown requested")
        return 0

    if args.action == "start":
        # If already running, do nothing.
        if _daemon_get("/health") is not None:
            print("daemon: already running")
            return 0

        # Spawn the daemon as a detached subprocess. Inherit stderr so the
        # operator can see startup logs in the same terminal during dev.
        cmd = [sys.executable, "-m", "pr_review.daemon"]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Wait for the rendezvous file + a successful /health.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            result = _daemon_get("/health", timeout=0.5)
            if result is not None:
                rv = daemon.read_rendezvous()
                print(f"daemon: started on port {rv['port']} (pid={rv['pid']})")
                return 0
            if proc.poll() is not None:
                print(f"daemon: subprocess exited early with code {proc.returncode}", file=sys.stderr)
                return 1
            time.sleep(0.1)

        print("daemon: failed to come up within 5s", file=sys.stderr)
        return 1

    return _stub(f"daemon {args.action}")(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pr-review",
        description="Local-first GitHub PR review CLI.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<command>")

    p_init = sub.add_parser(
        "init",
        help="Initialize a review for a GitHub PR. Idempotent (resumes if state exists).",
    )
    p_init.add_argument("pr_url", help="Full GitHub PR URL or <owner>/<repo>#<N>.")
    p_init.set_defaults(func=cmd_init)

    p_draft = sub.add_parser(
        "draft",
        help="Push a YAML draft to the daemon. Validates positions; replaces current draft.",
    )
    p_draft.add_argument("pr", help="PR number (must already be initialized).")
    p_draft.add_argument("yaml_path", help="Path to the YAML payload file.")
    p_draft.set_defaults(func=cmd_draft)

    p_show = sub.add_parser(
        "show",
        help="Print current review state for a PR. Used by the hook for context sync.",
    )
    p_show.add_argument("pr", help="PR number.")
    p_show.set_defaults(func=cmd_show)

    p_status = sub.add_parser(
        "status",
        help="List active reviews. With --cwd, returns the active PR for that cwd's repo (or 'none').",
    )
    p_status.add_argument("--cwd", default=None, help="Look up active review for the repo containing this path.")
    p_status.set_defaults(func=cmd_status)

    p_stop = sub.add_parser(
        "stop",
        help="Discard the active review state. Does not affect already-published reviews.",
    )
    p_stop.add_argument("pr", help="PR number.")
    p_stop.set_defaults(func=cmd_stop)

    p_daemon = sub.add_parser("daemon", help="Daemon lifecycle control (mostly internal).")
    p_daemon.add_argument("action", choices=["start", "stop", "status"])
    p_daemon.set_defaults(func=cmd_daemon)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
