# Decisions

The design choices that fell out of walking the [workflows](./workflows.md) over the [components](./components.md).

## Local browser UI, not GitHub's review interface

GitHub-published comments are clunky to edit — you publish, then revise. We want code-like editability before anything reaches GitHub: fast iteration, cheap deletion. A local browser UI gives us that; GitHub's UI cannot.

## Draft manager's scope is drafts, not "all of GitHub"

The first draft of the model wrapped all GitHub interaction in the daemon. Rejected after walking the explore-PR workflow: replicating `gh`'s read surface (diff, files, file contents, PR metadata) inside the daemon would be busywork without payoff. Instead Claude uses `gh` directly for read-only exploration; the draft manager owns only drafts and publishing.

## Two skills, distinct roles

Documentation generation and comment drafting are different jobs with different inputs (read code vs. write comments) and different outputs (docs vs. draft YAML). Splitting them keeps each skill's prompt focused.

## CLI transport, not MCP

Everything is local: one machine, one user, shell access available. MCP's value (cross-system access, generic interface) doesn't apply here. CLI is simpler — it starts the server, the server holds state, the CLI is a thin client to it.

## Sync asymmetry: hook for UI→agent, WebSocket for agent→UI

- **UI → agent**: `UserPromptSubmit` hook. Fires only when the user prompts the agent. The agent only acts at turn boundaries, so passive sync is enough.
- **Agent → UI**: WebSocket. The browser must reflect agent state changes immediately so the user can see and react.

Symmetric sync would over-engineer one side or under-serve the other. The asymmetry matches the actual lifecycle of each consumer.

## Publish enforced architecturally, not by skill discipline

Claude's permissions deny `gh api ... pulls/<N>/reviews` at the Bash-permission layer. The PR draft manager is the only component with the publish path (via the UI's publish button). This turns "browser-only publish" from a policy that depends on the skill prompt into a structural invariant — even a misbehaving or jailbroken skill cannot ship a review.
