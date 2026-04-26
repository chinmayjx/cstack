"""pr-review daemon: long-running HTTP server backing the CLI.

This module implements the daemon as a single class with a small route
table. State is held in memory; persistence is handled by the state module
(to be added in a later slice).

Design choices that this slice locks in:

    - One daemon process per user, serving all reviews across all repos.
    - Listens on a free OS-assigned port; CLI rendezvous via a JSON file at
      ``paths.DAEMON_RENDEZVOUS``. The file is removed on graceful shutdown.
    - Idle timeout (``IDLE_TIMEOUT_SEC``) shuts the daemon down when no
      requests have arrived for that long. Any incoming request resets the
      idle clock.
    - Threaded HTTP server (one thread per request) so a long-poll / SSE
      stream can't block other requests.

Routes implemented in this slice:

    GET  /health           → {"status": "ok", "pid", "uptime_s", "version"}
    POST /shutdown         → graceful shutdown (used by ``daemon stop``)

All other routes return 404. Subsequent slices add ``/api/pr/...`` endpoints
and the SSE stream.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pr_review import __version__
from pr_review.paths import DAEMON_RENDEZVOUS, ensure_base_dirs

IDLE_TIMEOUT_SEC = 30 * 60   # 30 minutes


class DaemonState:
    """Daemon-global state shared across request threads.

    Only the bits that need to be visible to handlers and to the idle-watcher
    live here. Per-review state will be added in a later slice.
    """

    def __init__(self) -> None:
        self.started_at = time.time()
        self.last_request_at = time.time()
        self.lock = threading.Lock()
        self.shutdown_requested = threading.Event()

    def touch(self) -> None:
        with self.lock:
            self.last_request_at = time.time()

    def idle_seconds(self) -> float:
        with self.lock:
            return time.time() - self.last_request_at

    def uptime_seconds(self) -> float:
        return time.time() - self.started_at


def _make_handler(state: DaemonState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Quieter than the default; keep stderr usable.
            sys.stderr.write(f"[daemon] {self.address_string()} {format % args}\n")

        def _reply_json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            state.touch()
            if self.path == "/health":
                self._reply_json(
                    200,
                    {
                        "status": "ok",
                        "pid": os.getpid(),
                        "uptime_s": round(state.uptime_seconds(), 3),
                        "idle_s": round(state.idle_seconds(), 3),
                        "version": __version__,
                    },
                )
                return
            self._reply_json(404, {"error": "not found", "path": self.path})

        def do_POST(self) -> None:
            state.touch()
            if self.path == "/shutdown":
                self._reply_json(200, {"status": "shutting down"})
                state.shutdown_requested.set()
                return
            self._reply_json(404, {"error": "not found", "path": self.path})

    return Handler


def _write_rendezvous(port: int) -> None:
    ensure_base_dirs()
    payload = {
        "port": port,
        "pid": os.getpid(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
    }
    DAEMON_RENDEZVOUS.write_text(json.dumps(payload, indent=2))


def _remove_rendezvous() -> None:
    try:
        DAEMON_RENDEZVOUS.unlink()
    except FileNotFoundError:
        pass


def _idle_watcher(state: DaemonState, server: ThreadingHTTPServer) -> None:
    """Background thread: shut down the server if idle too long, or if asked.

    Wakes immediately on shutdown_requested, otherwise every 30s for an idle
    check. Avoids the latency of a fixed-interval poll.
    """
    while True:
        if state.shutdown_requested.wait(timeout=30):
            sys.stderr.write("[daemon] shutdown requested; stopping\n")
            server.shutdown()
            return
        if state.idle_seconds() > IDLE_TIMEOUT_SEC:
            sys.stderr.write(
                f"[daemon] idle for {state.idle_seconds():.0f}s "
                f"(> {IDLE_TIMEOUT_SEC}s); stopping\n"
            )
            server.shutdown()
            return


def run() -> int:
    """Entry point for ``python -m pr_review.daemon`` and ``daemon start`` (foreground)."""

    if read_rendezvous() is not None and _rendezvous_is_live():
        sys.stderr.write(
            "[daemon] another daemon already running "
            f"(rendezvous: {DAEMON_RENDEZVOUS}); refusing to start\n"
        )
        return 1

    state = DaemonState()
    handler_cls = _make_handler(state)

    # Bind to localhost on a free port (port 0 = OS assigns).
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    _write_rendezvous(port)

    # Make Ctrl-C a clean shutdown.
    def _on_signal(signum, _frame):
        sys.stderr.write(f"[daemon] caught signal {signum}; shutting down\n")
        state.shutdown_requested.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    watcher = threading.Thread(target=_idle_watcher, args=(state, server), daemon=True)
    watcher.start()

    sys.stderr.write(
        f"[daemon] listening on http://127.0.0.1:{port} "
        f"(pid={os.getpid()}, version={__version__})\n"
    )

    try:
        server.serve_forever()
    finally:
        _remove_rendezvous()
        sys.stderr.write("[daemon] exited\n")

    return 0


def read_rendezvous() -> dict | None:
    """Return the parsed rendezvous file, or None if it doesn't exist."""
    if not DAEMON_RENDEZVOUS.exists():
        return None
    try:
        return json.loads(DAEMON_RENDEZVOUS.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _rendezvous_is_live() -> bool:
    """Best-effort check: is the daemon at the rendezvous actually answering?"""
    rv = read_rendezvous()
    if rv is None:
        return False
    port = rv.get("port")
    if not isinstance(port, int):
        return False
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        # Connection refused, host unreachable, etc. → stale rendezvous.
        return False


if __name__ == "__main__":
    sys.exit(run())
