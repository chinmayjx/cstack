# Components

At the highest layer of abstraction the system has five components.

| Component | Role | Lives in |
|---|---|---|
| **User** | Reviews PRs with Claude's help. Drives the workflow; gates publish. | Outside the system. |
| **Skills** | Two skills inside Claude Code. A *doc skill* reads the PR and code via `gh` to produce documentation. A *draft skill* writes comments via the PR draft manager. | A Claude Code session. |
| **PR draft manager** | CLI + local HTTP server. Owns the draft lifecycle. The *only* component with the publish path to GitHub. | A long-running process on the user's machine. |
| **Interface** | Browser UI served by the draft manager. Editable comments, publish button. | A localhost browser tab. |
| **GitHub** | Source of truth for the PR (code, diff, files). Destination for published reviews. | External. |

## Interactions at this layer

- User ↔ Skills — chat in Claude Code
- User ↔ Interface — browser
- Skills → GitHub — read-only via `gh` (publish path is denied at the permission layer)
- Skills → PR draft manager — push a YAML draft via CLI
- PR draft manager → Interface — HTTP for editing, WebSocket for live sync
- PR draft manager → GitHub — publish via `gh api`, on user click only
- Hook (UserPromptSubmit) ↔ PR draft manager — hook pulls current draft state on every user prompt, injects it into Claude's context

## What's not a component at this layer

- `gh` itself. It's an edge between Skills/Manager and GitHub, not a component.
- The hook. It mediates the Manager→Skills edge but isn't a thing of its own at this layer.
- The state file / database. It's an internal detail of the PR draft manager. Lives at a deeper layer.
