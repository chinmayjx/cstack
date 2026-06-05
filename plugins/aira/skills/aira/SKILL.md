---
name: aira
description: Delegate Capillary work to aiRA — a sub-agent that creates loyalty/CRM configurations (promotions, campaigns, audiences, coupons, journeys, milestones, rewards, badges, gift vouchers, templates) and runs analytics on Capillary data (Spark/SparkSQL, customer/transaction/campaign metrics, plots). Use whenever the user asks about Capillary configs, intouch, loyalty programs, CRM analytics, or anything domain-specific to Capillary's platform. Invokes the `aira` CLI which talks to the deployed aiRA backend over a daemon-held WebSocket.
allowed-tools:
  - Bash(${CLAUDE_SKILL_DIR}/aira.py *)
  - Read
---

# aira — Capillary AIRA sub-agent CLI

aiRA is Capillary's own AI assistant. It has a domain-tuned system prompt, MCP tools that read Capillary's schema and master data, and a sandboxed Spark/Databricks environment for analytics. **Delegate Capillary tasks to it; do not try to do them yourself.** Your job is to drive the CLI, interpret its streamed output, and surface results to the user.

## One-time setup

The script needs the `websockets` Python package:

```bash
pip install --user websockets
```

If a chat call ever prints `aira chat requires the 'websockets' package`, that's what to run.

## Commands

Always invoke via the absolute path so Bash permissions match the allowlist:

```bash
${CLAUDE_SKILL_DIR}/aira.py login -u <email> -p <password> --org-id <org_id>
${CLAUDE_SKILL_DIR}/aira.py session create
${CLAUDE_SKILL_DIR}/aira.py chat --session-id <id> "<message>"
${CLAUDE_SKILL_DIR}/aira.py daemon-stop
```

### `login` (one-time per machine)

Stores a JWT at `~/.aira/credentials.json`. The user does this themselves — never ask them for a password mid-session and never store it in any artifact you produce. If `aira session create` fails with `Not logged in`, tell the user to run the login command with their credentials.

### `session create`

Creates a fresh aiRA conversation on the server and prints the `session_id` to stdout (the friendly name goes to stderr). Capture the id into a shell variable so subsequent chats use the same session:

```bash
SID=$(${CLAUDE_SKILL_DIR}/aira.py session create)
```

A session preserves chat history, file context, and (within a single Python cell lifetime) the Spark kernel. Use one session per coherent task; spawn a new session for unrelated work.

### `chat --session-id <id> "<message>"`

Sends the message and streams aiRA's reply to stdout. Multi-turn — keep using the same `--session-id` to continue the conversation.

## How to read the streamed output

The CLI renders four kinds of content as plain text on stdout. Stderr carries metadata (session names, build-artifact notices, errors). When teeing to a log file use `2>&1` to capture both.

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
4. **DBR SQL cell** — same shape, headed `──── SQL ────` / `Result:` / `──── end SQL ────`.

## Error recovery

Two distinct failure modes — different recovery rules:

- **`[error: WS dropped mid-response: ...]`** — the WebSocket between the local daemon and the aiRA backend dropped mid-stream. The session is still alive on the server. **Re-run the same `aira chat --session-id <same id> "..."`** to continue. The previous assistant turn was cut off server-side, but session history is preserved.
- **`<details class="error-analysis">` HTML block in the stream** — aiRA itself errored mid-turn (server-side internal error / token limit / tool failure). Re-running won't help in the same shape. **Split the request into smaller sub-tasks** and send them one at a time. e.g. instead of "discover schema, analyze 60 days, recommend config" in one prompt, send three separate chats.

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
