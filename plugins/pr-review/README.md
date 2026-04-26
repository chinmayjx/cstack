# pr-review

Multi-stage, local-first GitHub PR review workflow.

## Goal

Optimize for review **depth** and **team-knowledge accumulation**, not throughput. Each review goes through a structured reasoning process and produces two outputs: a line-anchored review on GitHub and (eventually) component-level design documentation that accumulates as a side effect.

This is **not** a CI bot. Reviews run from the local host with a human in the loop. Drafts live locally; nothing reaches GitHub until the human explicitly publishes.

## Status

Scaffolded. No skills implemented yet.

## Planned skills

| Skill | Trigger | Purpose |
|---|---|---|
| `/pr-review:start` | `<PR number or URL>` | Walk a PR through the multi-stage review workflow; produce a draft. |
| `/pr-review:publish` | `<PR number>` | Validate the local draft against the diff and atomically post to GitHub. |
| `/pr-review:doc` | `<component path>` | Generate or update a component's `DESIGN.md`. |

(Names and shape will likely shift as we build them — this is intent, not contract.)

## Planned tooling (non-skill)

A local web UI for reviewing the diff with comment overlays before publish — likely a small Python HTTP server + vanilla HTML, lives under `tools/` once built. Out of scope until we have at least one skill that produces drafts.

## Workflow stages (target)

1. **Understand the change** — read diff, group by component, locate touched code in its module/file context.
2. **Gather context** — read existing `DESIGN.md` if any, check git log for prior decisions, surface conventions.
3. **Identify the problem** — state the author's intent explicitly; pause for human confirmation. (Most bad reviews start from a wrong intent guess.)
4. **Consider solution space** — enumerate 2–3 defensible solutions with tradeoffs. Do NOT collapse to a single "ideal" answer.
5. **Evaluate** — debate with the human. Iterate on the draft until both parties converge.
6. **Output drafts** — review YAML at `.reviews/pr-<N>.yaml` (gitignored, per target repo) plus any documentation updates.

## Hard constraints

- Never autonomous. Never auto-publish. Human edits before posting.
- Reviews attributed to the human's GitHub account. The skill produces drafts; the human owns the published output.
- Scope discipline: distinguish issues caused by this PR (blocking) vs. made worse (flag) vs. preexisting (note as tech debt, do not demand rewrite).
- Stage 4 must enumerate alternatives, not converge on "the right answer."

## Storage

Per-target-repo:
- `.reviews/pr-<N>.yaml` — active draft (gitignored)
- `.reviews/posted/pr-<N>-<timestamp>.yaml` — archive after publish

The plugin operates on whichever repo `cwd` points to; nothing about it is specific to a single project.

## Development

Edit `SKILL.md` files (none yet) and run `/reload-plugins` to pick up changes. The plugin is loaded from `~/Documents/cstack/plugins/pr-review/` directly (cstack uses local-marketplace soft-link semantics) so edits are live.
