#!/usr/bin/env python3
"""Initialize a PR review by fetching the diff and exploding it into a
queryable tree under .reviews/<pr>/.

Layout produced:

    .reviews/<pr>/
    ├── index.json         # PR metadata + per-file index with line ranges
    └── files/
        └── <mirrored repo path>.diff   # one unified-diff segment per file

Subsequent skill turns read index.json to orient and selectively read
files/<path>.diff for the file under discussion. The full diff is never
loaded all at once.

Stdlib-only. Invokes the `gh` CLI for fetching.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")


def run(cmd: list[str]) -> str:
    """Run a subprocess; return stdout. Raises on non-zero exit."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def detect_repo() -> str:
    """Return owner/repo of the cwd's git repo, via gh."""
    return run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]).strip()


def fetch_pr_meta(pr: int, repo: str) -> dict:
    fields = "number,title,url,baseRefName,headRefName,headRefOid,state"
    return json.loads(run(["gh", "pr", "view", str(pr), "--repo", repo, "--json", fields]))


def fetch_pr_diff(pr: int, repo: str) -> str:
    return run(["gh", "pr", "diff", str(pr), "--repo", repo])


def split_into_file_segments(diff_text: str) -> list[list[str]]:
    """Split unified diff into per-file segments. Each segment starts with `diff --git`."""
    segments: list[list[str]] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                segments.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        segments.append(current)
    return segments


def parse_segment(segment: list[str]) -> dict:
    """Parse one per-file segment. Returns:
        {
            "path": str,            # post-rename / new path
            "old_path": str | None, # only set if rename
            "status": "added" | "modified" | "deleted" | "renamed" | "binary",
            "is_binary": bool,
            "hunks": [{old_start, old_count, new_start, new_count}, ...],
        }
    """
    info: dict = {
        "path": None,
        "old_path": None,
        "status": "modified",
        "is_binary": False,
        "hunks": [],
    }

    first = segment[0].rstrip("\n")
    m = DIFF_GIT_RE.match(first)
    if not m:
        raise ValueError(f"unexpected diff header: {first!r}")
    a_path, b_path = m.group(1), m.group(2)

    # Walk header lines until first hunk
    i = 1
    while i < len(segment):
        line = segment[i].rstrip("\n")
        if line.startswith("@@"):
            break
        if line.startswith("new file mode "):
            info["status"] = "added"
        elif line.startswith("deleted file mode "):
            info["status"] = "deleted"
        elif line.startswith("rename from "):
            info["status"] = "renamed"
            info["old_path"] = line[len("rename from "):]
        elif line.startswith("rename to "):
            info["status"] = "renamed"
            info["path"] = line[len("rename to "):]
        elif line.startswith("--- "):
            src = line[4:]
            if src != "/dev/null" and src.startswith("a/"):
                src = src[2:]
            if src != "/dev/null" and not info["old_path"]:
                info["old_path"] = src
        elif line.startswith("+++ "):
            tgt = line[4:]
            if tgt != "/dev/null" and tgt.startswith("b/"):
                tgt = tgt[2:]
            if tgt != "/dev/null":
                info["path"] = tgt
        elif "Binary files" in line and "differ" in line:
            info["is_binary"] = True
            info["status"] = "binary"
        i += 1

    # Fallbacks
    if info["path"] is None:
        info["path"] = b_path if b_path != "/dev/null" else a_path
    if info["old_path"] is None and info["status"] != "added":
        info["old_path"] = a_path

    # Parse hunks
    while i < len(segment):
        line = segment[i].rstrip("\n")
        m = HUNK_HEADER_RE.match(line)
        if m:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) else 1
            info["hunks"].append({
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
            })
        i += 1

    return info


def hunks_to_ranges(hunks: list[dict], side: str) -> list[list[int]]:
    """Convert hunks to a list of [start, end] inclusive ranges for the given side.

    LEFT  → ranges in the old file (deletion + context lines)
    RIGHT → ranges in the new file (addition + context lines)
    """
    out: list[list[int]] = []
    for h in hunks:
        start = h["old_start"] if side == "LEFT" else h["new_start"]
        count = h["old_count"] if side == "LEFT" else h["new_count"]
        if count > 0:
            out.append([start, start + count - 1])
    return out


def write_outputs(target_dir: Path, meta: dict, file_entries: list[dict], segments: list[list[str]], pr: int, repo: str) -> None:
    """Write index.json and per-file .diff files."""
    files_dir = target_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    for entry, seg in zip(file_entries, segments):
        diff_path = target_dir / entry["diff"]
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text("".join(seg))

    index = {
        "pr": pr,
        "repo": repo,
        "url": meta.get("url"),
        "title": meta.get("title"),
        "state": meta.get("state"),
        "base_ref": meta.get("baseRefName"),
        "head_ref": meta.get("headRefName"),
        "head_sha": meta.get("headRefOid"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "active_review": None,
        "files": file_entries,
    }
    (target_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize a PR review tree.")
    parser.add_argument("pr", type=int, help="PR number")
    parser.add_argument("--repo", default=None, help="owner/repo (default: detect from cwd)")
    parser.add_argument("--target", default=".reviews",
                        help="Target directory under cwd (default: .reviews)")
    args = parser.parse_args(argv)

    repo = args.repo or detect_repo()
    pr = args.pr

    print(f"Fetching PR #{pr} from {repo}…", file=sys.stderr)
    meta = fetch_pr_meta(pr, repo)
    diff_text = fetch_pr_diff(pr, repo)

    target_dir = Path(args.target) / str(pr)

    segments = split_into_file_segments(diff_text)
    file_entries = []
    for seg in segments:
        info = parse_segment(seg)
        path = info["path"]
        rel_diff = f"files/{path}.diff"
        entry: dict = {
            "path": path,
            "status": info["status"],
            "diff": rel_diff,
        }
        if info["status"] == "renamed":
            entry["old_path"] = info["old_path"]
        if info["is_binary"]:
            entry["new_lines"] = []
            entry["old_lines"] = []
        else:
            entry["new_lines"] = hunks_to_ranges(info["hunks"], "RIGHT")
            entry["old_lines"] = hunks_to_ranges(info["hunks"], "LEFT")
        file_entries.append(entry)

    write_outputs(target_dir, meta, file_entries, segments, pr, repo)

    print(f"Wrote {target_dir}/index.json", file=sys.stderr)
    print(f"Wrote {len(file_entries)} per-file diffs to {target_dir}/files/", file=sys.stderr)
    print(f"\nDone. Read {target_dir}/index.json to begin.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
