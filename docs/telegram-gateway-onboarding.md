# Telegram Gateway Onboarding

This guide walks through the local setup for running `cursor-agent` as a Telegram bot.
Use placeholders in files and keep real tokens only in your local environment.
If you do not have a Cursor API key yet, start with [Cursor API Key Onboarding](cursor-api-key-onboarding.md).

## Prerequisites

- A valid Cursor API key. See [Cursor API Key Onboarding](cursor-api-key-onboarding.md).
- A Telegram bot created with BotFather.
- Your numeric Telegram user ID.
- The repository dependencies installed with `uv`.

## 1. Create A Telegram Bot

1. Open Telegram and start a chat with `@BotFather`.
2. Send `/newbot`.
3. Follow BotFather's prompts for the bot display name and username.
4. Copy the bot token BotFather returns.

The token usually looks like `123456789:AA...`; treat it as a secret. Do not commit it, paste it into issues, or store it in shared docs.

## 2. Find Your Numeric Telegram User ID

The gateway allowlist uses numeric Telegram user IDs, not `@username` handles. You need **your** user ID — the person who will chat with the bot — not the bot's ID and not the BotFather token.

You will add this number to `platforms.telegram.allowed_users` in `gateway.yaml` (step 5). Without it, the gateway silently ignores your messages even when the token is valid and the process is running.

One simple option is to start a chat with a user info bot such as `@userinfobot` and copy the numeric `Id` value it returns. Usernames can change; numeric IDs are stable and match what the Telegram API sends in `from_user.id`.

## 3. Install Dependencies

```bash
uv sync
```

This command installs the project dependencies, including the Telegram adapter dependency `aiogram`.

## 4. Export Local Secrets

```bash
export CURSOR_API_KEY="your-cursor-api-key"
```

This command makes your Cursor API key available to the gateway process in the current terminal only.

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
```

This command makes your Telegram bot token available to the gateway process in the current terminal only.

## 5. Create Gateway Configuration

```bash
mkdir -p ~/.cursor-agent
```

This command creates the local cursor-agent configuration directory if it does not already exist.

```bash
cat > ~/.cursor-agent/gateway.yaml <<'YAML'
workspace: /absolute/path/to/your/project
tool_profile: messaging

platforms:
  telegram:
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
    allowed_users:
      - 123456789
YAML
```

This command writes a local gateway configuration file with Telegram enabled.

Edit the file and replace:

- `/absolute/path/to/your/project` with the repository path you want the bot to answer questions about.
- `123456789` with your numeric Telegram user ID.

Do not put the real Telegram token in `gateway.yaml`; keep `bot_token: ${TELEGRAM_BOT_TOKEN}` and provide the token through the environment.

## 6. Start The Gateway

```bash
uv run cursor-agent gateway --config ~/.cursor-agent/gateway.yaml
```

This command starts the long-running Telegram gateway with aiogram polling.

Keep this terminal open while testing. Stop the gateway with `Ctrl+C`.

## 7. Optional Memory Files

The gateway inherits Memory v1 through the shared send path. If `~/.cursor-agent/USER.md` or `~/.cursor-agent/MEMORY.md` exist (or a custom `memory_root` in `gateway.yaml`), the first free-text message after `/new` receives the same bounded memory payload as the CLI. After that first message, memory is frozen for the session until `/new` creates a fresh session row; mid-session file edits are not re-injected. Telegram does not expose `/memory show`; use the CLI command when you need to inspect the effective payload.

```bash
printf '%s\n' 'Prefer concise answers.' > ~/.cursor-agent/USER.md
```

This command creates a local user-memory file for manual testing. Keep private preferences and facts local, and do not commit these files.

## 8. Test In Telegram

Open a private chat with your bot and run this flow:

1. Click Telegram's Start button or send `/start`.
   Expected reply: `Send /new to start a conversation.`
2. Send regular text before creating a session.
   Expected reply: `Send /new to start a conversation.`
3. Send `/new`.
   Expected reply: `Started a new conversation.`
4. Send a repository question, such as `What files implement the Telegram adapter?`
   Expected behavior: the bot shows typing and then sends an answer.
5. Send `/help`.
   Expected behavior: the bot lists only `/new`, `/stop`, and `/help`.
6. Ask for a long response.
   Expected behavior: long answers are split into multiple Telegram messages.
7. Ask for a formatted answer with bold text, inline code, fenced code, and a link.
   Expected behavior: Telegram shows readable formatting (bold, monospace code blocks, and clickable `http://` or `https://` links) instead of raw Markdown syntax.

## 9. Optional Scheduled Cron Jobs

Cron jobs run inside the long-running gateway process. They use `~/.cursor-agent/cron/jobs.yaml`, reload when the file mtime changes, and never share a Telegram or CLI session key. Each run uses a fresh `cron:{job_id}:{run_id}` session row.

Cron schedules use UTC by default and must not fire more often than once per minute for the same job. The `prompt` field is capped at 64 KiB. Oversized prompts are rejected before writes, and invalid gateway reloads keep the last known-good job cache.

```bash
uv run cursor-agent cron list
```

This command lists configured jobs with schedule, next run, runtime, and Telegram chat ID metadata.

```bash
uv run cursor-agent cron add telegram-demo-report --schedule "*/1 * * * *" --prompt "Create a concise status update with a Markdown table, one link to https://example.com, and a short fenced code block." --runtime cloud --chat-id "123456789"
```

This command writes a demo job to `~/.cursor-agent/cron/jobs.yaml`; replace `123456789` with the destination Telegram chat ID and remove the job after testing to avoid recurring SDK usage.

```bash
uv run cursor-agent gateway --config ~/.cursor-agent/gateway.yaml
```

This command starts the embedded scheduler and Telegram gateway; keep it running until the demo job fires.

Expected Telegram delivery:

1. The scheduled job creates a dedicated cron session, not a chat session.
2. The result is rendered through the same Telegram formatter/chunker used for assistant replies.
3. Markdown tables are shown as bullets or row blocks, links remain clickable for `http://` and `https://`, and code stays readable.
4. If Telegram delivery fails, the cron run status remains independent and logs include only safe metadata such as job id and exception class.

```bash
uv run cursor-agent cron remove telegram-demo-report
```

This command removes the demo job after validation so it does not continue running every minute.

Cron prompts do not resolve CLI skills. The job `prompt` is the source of truth; `/<skill-name>` and `/skills` remain CLI/REPL behavior.

## 10. Restart Test

1. Stop the gateway with `Ctrl+C`.
2. Start it again:

```bash
uv run cursor-agent gateway --config ~/.cursor-agent/gateway.yaml
```

This command restarts the gateway using the same persisted session store.

3. Send another message to the bot.
   Expected behavior: the bot replies using the existing Telegram session. The first reply after restart can take longer because the pool may reattach the SDK agent.

## Troubleshooting

### Bot Does Not Reply

- Confirm the gateway process is still running.
- Confirm `TELEGRAM_BOT_TOKEN` is exported in the same terminal that runs the gateway.
- Confirm your Telegram user ID is listed under `allowed_users`.
- Confirm `allowed_users` uses a numeric ID, not an `@username`.
- Confirm the chat is a private one-to-one chat with the bot. Groups and topics are out of scope for the MVP.

### Gateway Fails At Startup

```bash
uv run cursor-agent gateway --config ~/.cursor-agent/gateway.yaml
```

This command reruns startup and prints configuration or dependency errors.

Common causes:

- `tool_profile` is not `messaging`.
- `bot_token` expands to an empty value because `TELEGRAM_BOT_TOKEN` is not exported.
- `workspace` is not an absolute path to the intended repository.
- The Telegram token format is invalid.

### Cron Job Does Not Appear In Telegram

- Confirm the gateway process was running when the scheduled time passed.
- Confirm the job has `delivery.telegram.chat_id` configured.
- Confirm the chat ID is numeric for normal private chats, or a Telegram-supported string destination if you intentionally use one.
- Confirm the schedule is UTC and not in local time.
- Confirm the job prompt is no larger than 64 KiB.
- Confirm `cursor-agent cron list` shows the job after `cron add`.
- Confirm you removed demo jobs that use `*/1 * * * *` after testing to avoid repeated SDK runs.

### User Is Ignored

The Telegram adapter silently ignores blocked users. Add only trusted numeric IDs to `allowed_users`.

### Markdown Formatting Looks Wrong

Assistant replies are rendered from a small Cursor-style Markdown subset to Telegram HTML (`parse_mode=HTML`).

Supported in answers:

- `**bold**`
- `` `inline code` ``
- fenced code blocks (language tag shown as bold label + inline monospace, e.g. **Shell:** `echo ok`)
- `#` headings (shown as bold)
- `[label](https://example.com)` links with `http://` or `https://` only
- GitHub-flavored Markdown tables (rendered as compact bullet lines or labeled row blocks)

Known limitations:

- Unsupported Markdown (blockquotes, nested lists) may appear as plain text.
- `javascript:` and other non-http(s) links stay as escaped plain text for safety.
- If rendering fails, the bot falls back to escaped plain text and logs only safe metadata.
- Malformed tables fall back to escaped plain text instead of Telegram HTML tables.

Table rendering behavior:

- Two-column tables become lines like `• **Label**: value`.
- Three-or-more-column tables become compact blocks with `Item N` headings and `Header: value` lines.
- Separator rows (`|---|---|`) are never shown in Telegram output.

To validate table formatting manually, ask the bot for a comparison table (for example criteria vs scores) and confirm Telegram shows bullets or row blocks instead of raw pipe syntax.

Command replies such as `/new`, `/stop`, `/help`, and the first-contact hint stay plain text.

### Integration Test Is Skipped

```bash
uv run pytest tests/integration/test_gateway_cold_start.py -m integration -v
```

This command runs the cold-start gateway integration test when `CURSOR_API_KEY` is available.

If the test skips, export `CURSOR_API_KEY` in the same terminal and run it again.

## Security Notes

- Keep `CURSOR_API_KEY` and `TELEGRAM_BOT_TOKEN` in environment variables or local ignored files only.
- Never commit real tokens.
- Use `tool_profile: messaging` for Telegram and other untrusted chat gateways.
- The `messaging` profile is read-only over the workspace and deploys defensive hooks at gateway startup.
- Non-allowlisted Telegram users receive no reply.
