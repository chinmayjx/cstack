# Workflows

The flows that drove the design. Five at this layer, each spanning multiple components.

## 1. Initialize a review

1. User: "review PR \<N\>" in chat.
2. Draft skill invokes the CLI to register the PR with the PR draft manager.
3. Draft manager starts (if not already running), records the PR, returns a localhost URL.
4. Skill replies in chat with the URL.

## 2. Read the PR (and generate docs)

The doc skill uses `gh` directly — diff, files, file contents, PR metadata. Does **not** go through the draft manager. Documentation files are written into the target repo.

This is the read-only side of the system: no state in the draft manager, no GitHub writes, just reading and producing docs.

## 3. Drafting comments — two paths

There are two ways comments end up in the draft, and both go through the draft manager (the single writer of draft state):

- **Skill push**: draft skill builds a YAML payload, calls the CLI to push it. Manager validates each comment's `(path, line, side)` against the diff, replaces the active draft, broadcasts to open browsers via WebSocket.
- **UI edit**: user adds, edits, or deletes comments in the browser. UI hits the manager's HTTP API. Manager updates state, broadcasts via WebSocket to other connected browsers.

## 4. Publish

User clicks Publish in the browser. Draft manager re-validates positions, posts the review to GitHub via `gh api ... pulls/<N>/reviews`, archives the local draft.

## 5. Sync between agent and UI

- **UI → agent**: hook on `UserPromptSubmit` queries the draft manager and injects current state into the agent's context. Passive — fires only when the user sends a chat message. Sufficient because the agent only acts at turn boundaries.
- **Agent → UI**: WebSocket from the draft manager pushes immediately on state change. Active — keeps the browser live regardless of user action.

The asymmetry is intentional: agent state changes need to reach the UI immediately so the user sees them; UI changes only need to reach the agent at the agent's *next* turn.
