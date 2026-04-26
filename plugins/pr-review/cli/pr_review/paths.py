"""Filesystem paths for pr-review's local state.

Layout:

    ~/.cstack/pr-review/
    ├── daemon.json                 # rendezvous file: {port, pid, started_at}
    └── state/
        ├── <owner>__<repo>__<PR>.yaml      # active review state
        └── posted/
            └── <owner>__<repo>__<PR>__<timestamp>.yaml

The base directory is created on demand by callers that need it; this module
only computes paths.
"""

from pathlib import Path

BASE_DIR = Path.home() / ".cstack" / "pr-review"
STATE_DIR = BASE_DIR / "state"
POSTED_DIR = STATE_DIR / "posted"
DAEMON_RENDEZVOUS = BASE_DIR / "daemon.json"


def ensure_base_dirs() -> None:
    """Create the base + state + posted directories if they don't exist."""
    POSTED_DIR.mkdir(parents=True, exist_ok=True)


def state_file_for(owner: str, repo: str, pr: int) -> Path:
    return STATE_DIR / f"{owner}__{repo}__{pr}.yaml"
