---
name: aira
description: Delegate Capillary work to aiRA — a sub-agent that creates loyalty/CRM configurations (promotions, campaigns, audiences, coupons, journeys, milestones, rewards, badges, gift vouchers, templates) and runs analytics on Capillary data (Spark/SparkSQL, customer/transaction/campaign metrics, plots). Use whenever the user asks about Capillary configs, intouch, loyalty programs, CRM analytics, or anything domain-specific to Capillary's platform. Invokes the `aira` CLI which talks to the deployed aiRA backend over a daemon-held WebSocket.
allowed-tools:
  - Bash(${CLAUDE_SKILL_DIR}/aira.py *)
  - Read
---

# aira — Capillary AIRA sub-agent CLI

aiRA is Capillary's own AI assistant. It has a domain-tuned system prompt, MCP tools that read Capillary's schema and master data, and a sandboxed Spark/Databricks environment for analytics. **Delegate Capillary tasks to it; do not try to do them yourself.** Your job is to drive the CLI, interpret its streamed output, and surface results to the user.

## Commands

Always invoke via the absolute path so Bash permissions match the allowlist:

```bash
${CLAUDE_SKILL_DIR}/aira.py login            # reads $AIRA_* env vars; flags optional
${CLAUDE_SKILL_DIR}/aira.py session create
${CLAUDE_SKILL_DIR}/aira.py chat --session-id <id> "<message>"
${CLAUDE_SKILL_DIR}/aira.py daemon-stop
```

### `login` (one-time per machine)

Authenticates and stores a JWT at `~/.aira/credentials.json`. On the first login the CLI also bootstraps its runtime — it creates a private Python venv at `~/.aira/venv` and installs `websockets` into it; subsequent commands re-exec via that interpreter so the system Python stays untouched. The user runs this themselves — never ask them for a password mid-session and never store it in any artifact you produce. If `aira session create` or `aira chat` fails with `Not logged in` or returns an auth error (`401 Unauthorized`), tell the user to re-run `aira login`; the token has expired or was cleared.

Credentials and the target cluster come from environment variables by default, so the user just runs `aira login` with no arguments. The recommended setup is to export these in `~/.bashrc` (or `~/.zshrc`):

```bash
export AIRA_USERNAME="you@capillarytech.com"
export AIRA_PASSWORD="••••••"      # omit to be prompted instead of storing it
export AIRA_ORG_ID="12345"
export AIRA_CLUSTER="nightly"
```

Any value can be overridden on the CLI — flags take precedence over the environment, and the password is prompted if set neither way:

```bash
${CLAUDE_SKILL_DIR}/aira.py login -u <email> -p <password> --org-id <id> --cluster <name>
```

`--cluster` / `$AIRA_CLUSTER` selects which deployment to talk to; it defaults to `nightly`.

| Cluster   | intouch URL                                 |
|-----------|---------------------------------------------|
| `nightly` | `https://nightly.intouch.capillarytech.com` |

### `session create`

Creates a fresh aiRA conversation on the server and prints the `session_id` to stdout (the friendly name goes to stderr). Capture the id into a shell variable so subsequent chats use the same session:

```bash
SID=$(${CLAUDE_SKILL_DIR}/aira.py session create)
```

A session preserves chat history, file context, and (within a single Python cell lifetime) the Spark kernel. Use one session per coherent task; spawn a new session for unrelated work.

### `chat --session-id <id> "<message>"`

Sends the message and streams aiRA's reply to stdout. Multi-turn — keep using the same `--session-id` to continue the conversation.

## How to read the streamed output

The CLI renders three kinds of content as plain text on stdout. Stderr carries metadata (session names, build-artifact notices, errors). When teeing to a log file use `2>&1` to capture both.

1. **Text response** — aiRA's natural-language reply. Streams chunk-by-chunk; may contain HTML/markdown (`<details>`, `<br>`, etc.) that wraps tool-discovery output. Keep all of it; the references in those blocks are aiRA's grounding evidence.
2. **Config artifact** — buffered, printed as one block when ready:
   ```
   ─── Artifact: <name> ───
   { ...full config JSON... }
   Tips: • ...
   Blockers: • ...
   ─── end artifact ───
   ```
   The config is **not** auto-created. The user must click **Create** on the artifact in the aiRA web UI (`https://nightly.intouch.capillarytech.com/ask-aira/ui/chat/<session_id>`). Surface that explicitly when you report results: tell the user the artifact is ready and where to click.
3. **Python cell** (analytics) — streamed linearly:
   ```
   ──── Python Cell N: <title> ────
   Code:
   <code streams live>

   Output:
   <text / table / error / markdown streams live>
   [plot saved: ~/.aira/outputs/<session_id>/<version_id>-N.svg]
   ──── end cell ────
   ```
   `[plot saved: <path>]` is a real file you can `Read` with the Read tool. Same for `[PDF saved: <path>]`.

## Session logs

Every `chat` turn is automatically teed to `~/.aira/logs/<session_id>.log` (append mode — the file becomes the full transcript of that session: rendered text, cells, tables, and `[plot saved: ...]` notices). You don't pipe anything; the CLI writes it and prints `[session log: <path>]` on stderr at the start of each turn.

You already have the same output inline, but the file is useful to hand to the user — tell them they can watch a long-running turn live with:

```bash
tail -f ~/.aira/logs/<session_id>.log
```

## Error recovery

- **`[error: WS dropped mid-response: ...]`** — the WebSocket between the local daemon and the aiRA backend dropped mid-stream. The session is still alive on the server with its full chat history, so you do **not** have to redo the task. **Re-run the same `aira chat --session-id <same id> "..."`** — it reconnects and continues the conversation from where it left off. One caveat: a reconnect resets the analytics Python/Spark sandbox, so any in-memory state from an interrupted analytics turn (loaded dataframes, variables, the warm Spark kernel) is lost and that step re-executes from scratch. Plain config/chat turns have no such state and just resume.

Other guidance:

- Long analytics turns can run for minutes (schema discovery → big LLM tool calls → Spark cold start → query). Don't time out the bash call too aggressively.
- The daemon auto-spawns on first chat. If it can't connect, the chat prints `daemon did not start; check ~/.aira/daemon.log`. Read that file to diagnose.
- `aira daemon-stop` kills the local daemon (SIGTERM via stored pidfile). Next chat respawns it. Use this if you suspect daemon state is bad — but normally never needed.

## When to use aiRA vs. doing it yourself

- **Use aiRA**: anything Capillary-specific. Loyalty configs (promotions, campaigns, audiences, milestones, badges, rewards, coupons, journeys, gift vouchers), templates (SMS/email/WhatsApp/RCS/Zalo), QA tests, customer/transaction analytics, schema questions, Spark/SparkSQL queries against the customer's data.
- **Don't use aiRA**: anything not Capillary. General coding help, unrelated research, system administration. aiRA is scoped to one domain.

## Patterns

**Single analytics question** (one-shot insight): `session create` → one `chat`.

**Multi-step exploration** (the user wants to dig into something): `session create` → many `chat`s on the same session_id. Each chat builds on prior context.

**Comparing two unrelated things in parallel**: two sessions, each with its own UUID. The daemon multiplexes; both stay open.

**Config creation with HITL**: aiRA builds the config artifact. Surface the **Create** CTA + UI link explicitly so the user knows to confirm. Never claim a config was "created" — only that it's ready for the user to create.
