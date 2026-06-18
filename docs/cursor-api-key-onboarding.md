# Cursor API Key Onboarding

`cursor-agent` needs a Cursor API key to create and run SDK agents. Keep the key local and never commit it.

## 1. Create Or Find Your Cursor API Key

1. Open <https://cursor.com/dashboard/api>.
2. Sign in with the Cursor account you want to use for local agent runs.
3. Create a new API key, or copy an existing key if your organization already issued one for this machine.
4. Store the key in a local password manager or secret store.

Do not paste the key into chat, issues, pull requests, screenshots, or committed files.

## 2. Export The Key Locally

```bash
export CURSOR_API_KEY="your-cursor-api-key"
```

This command makes the key available only to processes started from the current terminal session.

To confirm the variable exists without printing the secret:

```bash
test -n "$CURSOR_API_KEY" && echo "CURSOR_API_KEY is set"
```

This command verifies that the environment variable is non-empty without exposing its value.

## 3. Optional Local Env File

For local convenience, you may keep secrets in a gitignored `.env` file:

```bash
cp .env.example .env
```

This command creates a local environment file from placeholders.

Then edit `.env` locally and set:

```dotenv
CURSOR_API_KEY=your-cursor-api-key
```

Do not commit `.env`. The repository only tracks `.env.example` placeholders.

## 4. Verify SDK Access

Run a non-integration unit gate first:

```bash
uv run pytest -m "not integration" -v
```

This command confirms the local project works without using the API key.

When you need to verify SDK-backed integration behavior:

```bash
uv run pytest -m integration -v
```

This command runs integration tests that use `CURSOR_API_KEY`; tests should skip when the key is absent and should not print the key.

## 5. Use With Telegram Gateway

The Telegram gateway needs both:

- `CURSOR_API_KEY` for Cursor SDK agent runs.
- `TELEGRAM_BOT_TOKEN` for Telegram polling.

After setting `CURSOR_API_KEY`, continue with [Telegram Gateway Onboarding](telegram-gateway-onboarding.md).

## Troubleshooting

### Integration Tests Skip

If integration tests skip unexpectedly, confirm the variable is set in the same terminal:

```bash
test -n "$CURSOR_API_KEY" && echo "CURSOR_API_KEY is set"
```

This command checks the current shell environment without printing the key.

### Gateway Starts But Agent Replies Fail

- Confirm `CURSOR_API_KEY` is exported in the same terminal running the gateway.
- Confirm the key is valid in <https://cursor.com/dashboard/api>.
- Confirm `cursor-sdk-bridge` is available on `PATH`.
- Restart the gateway after changing environment variables.

## Security Notes

- Treat `CURSOR_API_KEY` as a secret.
- Prefer environment variables or local ignored files.
- Never commit real API keys.
- Do not pass secrets through command-line arguments, because shell history can persist them.
