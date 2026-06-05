---
name: pr-review
description: Start a collaborative PR review on a GitHub PR. Fetches the diff, drafts comments in chat, posts as a pending GitHub review only on the user's explicit green flag. Invoke as /dev:pr-review <pr-number-or-url>.
user-invocable: true
allowed-tools:
  - Bash(gh *)
  - Bash(python *)
  - Read
  - Write
---

# /dev:pr-review — Collaborative PR review

Comments are drafted in chat. They go to GitHub (as a pending review, private to the user) only when the user explicitly says "post these" or equivalent. After posting, edits go through the GitHub API surgically. The user submits the review via GitHub.com when they're done.

The review is structured: derive the problem statement, build a multi-level abstraction doc as you go, slice the PR by component groups (each slice small enough to hold in your head), then review each slice against the doc plus engineering common sense. This deliberately spreads cognitive load across many turns rather than cramming a 20-comment review into one response.

## Workflow at a glance

1. **Initialise** — fetch diff and metadata.
2. **Orient** — read `index.json`.
3. **Derive the problem statement** — explore the codebase; confirm intent with the user.
4. **Build (or extend) the docs** — first-principles multi-level abstraction model of the touched system.
5. **Slice the PR** — partition into component groups, each small enough to hold in your head, tracked via `TaskCreate`.
6. **Per-slice review loop** — for each slice, compare impl against the doc, apply common sense, draft comments in chat, append to `draft.json` after explicit approval.
7. **Post on green flag** — single API call creates a pending review.
8. **Iterate after posting** — surgical edits via the GitHub API.
9. **User submits** via GitHub.com's "Submit Review" button.

---

## 1. Initialise

Extract the PR number from the user's input (bare number or full GitHub URL). Then run:

```bash
python "${CLAUDE_SKILL_DIR}/init_review.py" <pr-number>
```

This populates `<cwd>/.reviews/<pr>/`:

- `index.json` — PR metadata (`pr`, `repo`, `url`, `head_sha`, …), `active_review` (initially `null`), and a `files` array with `path`, `status`, `new_lines` (RIGHT-side ranges), `old_lines` (LEFT-side ranges).
- `files/<mirrored-repo-path>.diff` — one unified-diff segment per file.

If the cwd's repo isn't the target, pass `--repo <owner>/<repo>` to the script.

## 2. Orient

Read `.reviews/<pr>/index.json` to see PR metadata, file list, statuses, and valid line ranges per file. **Do not** read all per-file diffs upfront — diffs can be thousands of lines and would burn context.

## 3. Derive the problem statement

Before reading any diff, work out what the PR is actually trying to solve. The PR description is often auto-generated (CodeRabbit, Copilot Workspace, etc.) and should not be trusted as a statement of intent.

Explore the surrounding codebase: read top-level READMEs, root and subproject `CLAUDE.md` files, the relevant package's `__init__` or main entry, the modules the PR touches *from the outside*. Form a hypothesis at the highest level of abstraction: what is this system, what is this PR's role within it, what problem is being solved.

Then state your hypothesis to the user explicitly and pause for confirmation. Most bad reviews start from a wrong guess about intent — catching it here is cheap; catching it after a full analysis is wasted analysis.

## 4. Build (or extend) the docs

The docs are the first-principles output of the review, not a side note. They live in the project at `docs/<component-name>/` (e.g., `docs/event-tracking/index.md`, `docs/event-tracking/data-model.md`, `docs/event-tracking/migration.md`). They outlive this PR — the next review of the same component starts from a higher baseline.

The doc is a **multi-level abstraction model** of the system:

- **Highest level** (`index.md`): the system's purpose. What problem does it solve? What does it expose to its callers / users? Two or three paragraphs. Pointers to deeper docs.
- **Mid levels** (one or more focused files): the modules that compose the system. For each — purpose, contract, internal model, dependencies, rejected alternatives, compromises.
- **Lower levels**: data shapes, dispatch flows, drift mechanics — only as deep as needed to anchor reasoning. **Do not go down to implementation details, or the doc becomes the code.**

Build the doc collaboratively with the user. They'll fill in product context, constraints, and design decisions you can't derive from code alone. Confirm at each abstraction level before moving deeper. Update the docs as the conversation surfaces things — design choices the user reveals, requirements that have evolved, items that turn out to be in/out of scope. The doc is a living artifact.

When existing docs are present, read them first, treat them as the spec, and update them as discrepancies surface during the review.

## 5. Slice the PR

Partition the PR's components into slices before drafting any comments. The constraint is **per-slice cognitive load**, not total slice count:

- Each slice covers a small group of related components — roughly **up to ~5 components** that a single review pass can hold in working memory while drafting comments.
- Each slice maps to a coherent question — "does the data model match its design?", "is the dispatch path correct?", "is migration safe?".
- The number of slices is whatever the PR divides into at that per-slice limit. A small PR might be one slice; a big one might be ten or more. Don't compress a large PR into fewer slices — split further.

Trivial PRs (single component, a handful of files) don't need slicing — review them directly.

Use `TaskCreate` to track the slices as a checklist. Mark each `in_progress` when you start it, `completed` when its comments are in the payload.

Slicing forces structure on the review, spreads cognitive load over many turns, makes user pushback easier within a slice, and surfaces doc gaps as you go (the slices that don't map to documented sections need new doc content).

## 6. Per-slice review loop

For each slice in order:

1. **Announce** the slice — name it, list its files, state what you're comparing against (specific doc section, or "general engineering judgment" if no doc covers it yet).
2. **Read** only that slice's files. Use `index.json` for line ranges; pull individual `files/<path>.diff` only when needed.
3. **Surface findings**:
    - **Spec-vs-impl divergences**: where does the implementation deviate from the doc? Each divergence is either a code comment to file, a doc update, or both.
    - **Engineering common sense** (regardless of whether the doc covers it — see "Don't get lost in the docs" below).
4. **Draft comments in chat** with file path, line numbers (start_line if a range), severity tag, body. Discuss with the user — refine wording, drop comments that don't earn their way in, add ones they request.
5. After explicit approval, **append the comments to `<cwd>/.reviews/<pr>/draft.json`**.
6. **Mark task completed**, move to the next slice.

The chat is the working draft for each slice. The payload accumulates across slices.

## 7. Post on green flag

When the user explicitly approves ("post these", "ship it", etc.), validate every `(path, line, side)` against the `new_lines` / `old_lines` ranges in `index.json`. GitHub atomically rejects the whole review if any position is invalid.

Then post:

```bash
gh api --method POST \
  /repos/<owner>/<repo>/pulls/<pr>/reviews \
  --input <payload>.json
```

Payload shape:

```json
{
  "commit_id": "<head_sha from index.json>",
  "body": "<short overall summary>",
  "comments": [
    { "path": "...", "line": 12, "side": "RIGHT", "body": "..." },
    { "path": "...", "start_line": 17, "line": 19, "start_side": "RIGHT", "side": "RIGHT", "body": "..." }
  ]
}
```

Omitting `event` creates the review in PENDING state — visible only to the user.

After a successful POST, write the returned review id back into `index.json`'s `active_review` field as `{"id": <id>, "state": "PENDING"}`.

## 8. Iterate after posting

When the user wants to add / edit / delete a comment after posting, operate against GitHub directly. **Always re-fetch the current pending comments before editing or deleting** — IDs and bodies are canonical on GitHub, not in any local cache.

```bash
# List current pending comments (with IDs)
gh api /repos/<owner>/<repo>/pulls/<pr>/reviews/<review_id>/comments

# Edit a comment
gh api --method PATCH /repos/<owner>/<repo>/pulls/comments/<comment_id> -f body="<new body>"

# Delete a comment
gh api --method DELETE /repos/<owner>/<repo>/pulls/comments/<comment_id>

# Add a new comment (auto-attaches to the active pending review)
gh api --method POST /repos/<owner>/<repo>/pulls/<pr>/comments \
  -f path="..." -F line=<int> -f side="RIGHT" -f body="..." -f commit_id="<head_sha>"

# Discard the entire pending review
gh api --method DELETE /repos/<owner>/<repo>/pulls/<pr>/reviews/<review_id>
```

## 9. Submit

The user submits the review via GitHub.com's "Submit Review" button. The skill **does not** call submit — that's the deliberate human action that sends the review to others.

---

## Don't get lost in the docs

The doc is a tool for structuring the review, not the deliverable. Apply general engineering common sense throughout, regardless of whether the doc covers it:

- **Directory structure** — does the file live where its peers live? Are layers respected (models in models, routes in routes)?
- **Naming** — does the symbol/file name say what it does? (e.g., `compute_time_seconds` for a wall-clock latency measurement is misleading.)
- **Null/missing handling** — fields accessed without guards; `entry["foo"]` instead of `entry.get("foo")`; defaults that mask absence (`result.get("id") or 0` swallows both `None` and a legitimate `0`).
- **Errors not masked** — broad `except Exception` swallowing failures, fallbacks that silently substitute wrong values, log-and-continue when failing-loud is right. For source-of-truth code paths especially, default to fail-loud.
- **Defensive code** — try/except around things that shouldn't fail; bypassing schema validation with permissive types; "just in case" branches that hide design assumptions.
- **Auth surfaces** — endpoints that should be admin-gated; credentials with personal-account defaults; injection risk in string-interpolated queries.
- **Resource lifecycles** — fire-and-forget tasks without strong references (Python's `asyncio.create_task` GC pitfall); connections without cleanup; unbounded buffers.
- **Single source of truth** — duplicated constants across files; data written to two collections without a clear primary; schemas defined twice in different forms.
- **Observability** — silent operations that should emit notifications; structured logs vs print; metrics for things you'd want to see in prod.
- **Concurrency / atomicity** — claims of atomicity that aren't actually atomic; reconciliation paths that rebuild from cache instead of source of truth.

These cut across slices. Watch for them while reviewing each slice's files.

## Comment quality

**Length matches content, not the user's terse style.** The user's review style may be short out of laziness, not because brevity is correct. Write comments at the length the content needs. Cite docs / upstream sources when claims need backing (e.g., link to Python docs for the `asyncio.create_task` weak-reference quote rather than asserting it from memory).

**Severity discipline:**

- **blocking** — bug, security gap, or correctness failure that exists independent of any design decision (a real `KeyError` waiting to fire, an unauthenticated mutation endpoint, a task that can be GC'd mid-execution).
- **suggestion** — design or quality improvement that requires the author's judgment.
- **question** — when you genuinely don't know if something is intentional. Phrase as a question, not a veiled assertion.

Use blocking sparingly. Most findings are suggestions or questions. Severity inflation devalues the label.

**Tone.** Comments are attributed to the user's GitHub account. Be substantive but not condescending; soften where appropriate. Don't pile on with three small adjacent suggestions when one consolidated comment carries more weight.

## LLM bias guards

Watch for these failure modes when drafting:

- **Q&A tendency** — jumping straight to comments before understanding the problem. Resist by working through Sections 3–4 (problem statement, docs) first.
- **Recency bias** — reaching for the same observation pattern slice after slice (e.g., flagging the same kind of defensive `try/except` everywhere, or repeatedly proposing the same refactor). Each slice's findings should come from that slice, not from a habit.
- **Premature structure** — imposing numbered taxonomies, sub-sections, and headers when prose would do. Numbered lists earn their place when the items are genuinely parallel; otherwise they're ceremony.
- **Sycophancy** — conceding when the user pushes back firmly. Concession-without-reasoning reads agreeable but doesn't help. If you genuinely changed your mind, say *why*. If you didn't, hold the position.
- **Substrate-mismatched mimicry** — dropping items from a draft just because that's what humans do, even when the cost of including them is near-zero in this medium.

## Constraints

- Never auto-publish. "Post these" creates a *pending* review only.
- Validate every comment's `(path, line, side)` against `index.json` before posting. Bad positions cause atomic rejection.
- For large PRs, never load all diff content at once. `index.json` for navigation, individual `files/<path>.diff` only when discussing that file.
- Wait for explicit user approval before appending comments to `draft.json`.
