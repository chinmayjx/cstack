# pr-review — Architecture

## 1. Purpose

A local-first GitHub PR review tool. The agent (Claude in any chat session) drafts line-anchored review comments through the CLI; the human reviews and edits in a browser UI; the human publishes to GitHub atomically and only on explicit click.

State stays local until publish — nothing reaches GitHub until the user clicks the button in the browser. This is the central invariant. Every architectural choice in this document serves it.

## 2. High-level flow

1. **User in chat**: "review PR 653" (or similar).
2. **Agent invokes the CLI**: `pr-review init <PR-url>`. CLI fetches the diff via `gh`, parses hunks, computes the set of valid `(path, line, side)` positions where comments can be placed, persists the state, ensures the daemon is running, returns a URL.
3. **Agent drafts review YAML** to a temp file, then calls `pr-review draft <PR> <yaml-path>`. CLI validates each comment's position, replaces the current draft, notifies any open browser via SSE.
4. **Agent replies in chat** with the URL plus a free-form summary of what it drafted.
5. **User opens URL** → browser UI shows the diff with comments anchored to lines. User edits / deletes / adds comments in-place; browser hits CLI HTTP endpoints; CLI persists.
6. **UserPromptSubmit hook fires on every follow-up turn** → calls `pr-review show <PR>` → output injected into agent's context. Agent always sees fresh state at turn start without needing to remember to poll.
7. **Iteration loop**: agent updates draft via CLI in response to chat input; user edits in browser. Both routes go through the CLI as the single writer.
8. **User clicks publish in browser** → CLI re-validates positions one last time and posts to GitHub via a single `gh api repos/<owner>/<repo>/pulls/<N>/reviews` call → CLI archives the draft to `state/posted/`.

## 3. Components

| Component | Role |
|---|---|
| **CLI binary** (`pr-review`) | Python entry point. Subcommands. Talks to the daemon over local HTTP loopback. Used by the agent and (rarely) by the human directly. |
| **Daemon HTTP server** | Long-running Python process. Holds active reviews in memory, persists to disk, serves the browser UI, exposes the API for both browser and CLI. |
| **State store** | Filesystem under `~/.cstack/pr-review/state/`. One YAML file per active review. |
| **Hook script** | `cstack/plugins/pr-review/hooks/on-prompt-submit.sh`. Runs on every `UserPromptSubmit`. Queries the daemon for active-review state, prints a compact summary on stdout — that becomes part of the agent's context for the turn. |
| **Browser UI** | Vanilla HTML + JS, served by the daemon. Diff rendered with `diff2html` (CDN), comment overlays anchored to lines, edit / publish controls. |

## 4. CLI subcommand surface

| Command | Purpose |
|---|---|
| `pr-review init <PR-url>` | Initialize a review. Idempotent: if state already exists for that PR, resumes it instead of refetching. |
| `pr-review draft <PR> <yaml-path>` | Push a YAML draft. Validates positions; replaces the current draft atomically. |
| `pr-review show <PR>` | Print current state (used by the hook and by the agent for re-sync). |
| `pr-review status [--cwd <path>]` | List active reviews. With `--cwd`, returns the active review for the repo containing that path, or "none". |
| `pr-review stop <PR>` | Discard the active draft (delete state). Does not affect already-published reviews. |
| `pr-review daemon {start,stop,status}` | Explicit daemon control. Mostly internal — `init` starts it lazily — but available for debugging. |

## 5. Browser-facing HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/pr/<PR>` | Returns `{diff, draft, valid_positions, pr_meta}` in one shot. The UI loads everything it needs from this. |
| `POST` | `/api/pr/<PR>/comment` | Add a comment. Body: `{path, line, side, severity, body}`. Server assigns an `id`. |
| `PUT` | `/api/pr/<PR>/comment/<id>` | Edit an existing comment. |
| `DELETE` | `/api/pr/<PR>/comment/<id>` | Delete a comment. |
| `PUT` | `/api/pr/<PR>/summary` | Update the review's summary text. |
| `PUT` | `/api/pr/<PR>/event` | Set review event (`COMMENT` / `APPROVE` / `REQUEST_CHANGES`). |
| `POST` | `/api/pr/<PR>/publish` | Validate one final time, post to GitHub, archive draft. Returns the published review URL. |
| `GET` | `/api/pr/<PR>/events` | Server-Sent Events stream. Emits when state changes (e.g., agent pushes a new draft) so the UI can refresh. |
| `GET` | `/` and `/static/*` | Serve the UI assets. |

## 6. State model

One YAML file per active review at `~/.cstack/pr-review/state/<owner>__<repo>__<PR>.yaml`:

```yaml
pr: 653
repo: Capillary/cap-ai-readiness
url: https://github.com/Capillary/cap-ai-readiness/pull/653
fetched_at: 2026-04-26T00:00:00Z
diff: |
  <full unified diff text from `gh pr diff`>
valid_positions:                              # computed at init, cached
  - { path: api/capdoc/features/media/router.py, line: 24, side: RIGHT }
  - ...
draft:
  event: COMMENT                              # COMMENT | APPROVE | REQUEST_CHANGES
  summary: ""
  comments:
    - id: c-7f3a1b                            # generated
      path: api/capdoc/features/media/service.py
      line: 11
      side: RIGHT
      severity: suggestion                    # blocking | suggestion | question
      body: |
        free-form markdown
```

After publish, the file is moved to `~/.cstack/pr-review/state/posted/<owner>__<repo>__<PR>__<timestamp>.yaml` for archival and grep-ability.

State file naming is flat (with `__` separators) rather than nested directories so that simple `ls ~/.cstack/pr-review/state/` shows everything at a glance.

## 7. Hook integration

File: `cstack/plugins/pr-review/hooks/on-prompt-submit.sh`. Wired into `plugin.json`'s hooks section to fire on `UserPromptSubmit`.

Behavior:

1. Determine the current cwd's git repo via `git rev-parse --show-toplevel`. Exit 0 silently if not inside a repo.
2. Call `pr-review status --cwd "$PWD"`. Returns the active PR number for this repo, or `none`.
3. If `none`, exit silently.
4. Otherwise call `pr-review show <PR>` and emit a compact summary to stdout. The hook's stdout becomes part of the agent's context for that turn.

This guarantees the agent sees fresh state at the start of every turn, regardless of what edits the user made in the browser between turns. No "remember to poll" instruction in the skill prompt is needed.

## 8. Daemon lifecycle

- Started lazily by `pr-review init` if not already running.
- Listens on a free port. Writes `{port, pid}` to `~/.cstack/pr-review/daemon.json` so the CLI can rendezvous with it on subsequent invocations.
- 30-minute idle timeout (matching gstack's pattern). Any incoming request resets the timer.
- A single daemon process serves all reviews across all repos. Reviews are keyed by `(owner, repo, pr)`.
- Graceful shutdown on SIGTERM: flushes in-memory state to disk, closes connections.

## 9. Dependencies

- **`gh` CLI** — user-installed and authenticated. The CLI shells out for diff fetch, PR metadata, and the publish call.
- **Python 3.10+** — stdlib only for HTTP server (`http.server.ThreadingHTTPServer`), `subprocess`, `json`, `argparse`, `urllib`.
- **`pyyaml`** — the only third-party Python dependency.
- **`diff2html`** — browser-side, loaded from CDN. No bundler.

## 10. Decisions and rejected alternatives

- **CLI owns state** vs. agent writing YAML to a known path → CLI owns. Single writer, clean modularity, the agent never touches files directly. The YAML format is a transit/payload format, not a public contract about where state lives.
- **Daemon model** vs. per-command server → daemon. The HTTP server has to outlive the `init` command for the browser to remain functional after the command returns.
- **UserPromptSubmit hook** vs. agent polling vs. monitor stream → hook. Robust against the LLM forgetting to poll; the right primitive for the lifecycle event we actually need (turn start). A monitor would only be justified if the agent had to react to events *during* a turn, which it doesn't.
- **YAML payload by file path** vs. piping vs. per-comment CLI flags → file path. Explicit, debuggable, supports many comments in one call without round-tripping. Cleanly mirrors how `curl -d @file` works.
- **Python over Bun** → Python. Simpler MVP; no bundler; the architecture doesn't depend on language choice and can be revisited if distribution becomes a priority.
- **Browser-only publish** vs. CLI / chat publish → browser-only. Deliberate human gate; the agent never has the ability to ship a review to GitHub. This is the central invariant from §1, made operational.

## 11. Out of scope (for this CLI)

- The `/pr-review:start` skill that drives the CLI. Lives separately under `skills/`. This doc is about the CLI + daemon; the skill's prompt design is its own document.
- Component documentation generation (`docs/<component>/DESIGN.md` outputs from earlier plans). Out of scope for the CLI; would be a separate skill.
- Subagent decomposition (Phase 6 of the original plan). The CLI's contract doesn't depend on whether the skill runs in one thread or many.
- Multi-PR queue / dashboard. Each review is opened individually for now; a "show me all my open reviews" view can be added later if it earns its way in.
- Authentication beyond what `gh` provides.
- Publishing to GitLab, Bitbucket, etc. GitHub-only.
