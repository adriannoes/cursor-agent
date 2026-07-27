# Email Gateway Onboarding

This guide walks through running `cursor-agent` as an email assistant over **IMAP + SMTP**.
The channel is provider-agnostic (AgentMail, Gmail, Fastmail, and similar). No AgentMail SDK is required.

Use placeholders in files and keep real passwords or API keys only in your local environment.
If you do not have a Cursor API key yet, start with [Cursor API Key Onboarding](cursor-api-key-onboarding.md).

## Prerequisites

- A valid Cursor API key. See [Cursor API Key Onboarding](cursor-api-key-onboarding.md).
- An inbox with IMAP and SMTP access (dedicated bot inbox recommended).
- Your own email address for the allowlist.
- The repository dependencies installed with `uv`.

## 1. Choose An Inbox (AgentMail Quick Path)

[AgentMail](https://www.agentmail.to) provides agent-ready inboxes with IMAP/SMTP:

| Setting | Value |
|---------|-------|
| IMAP host | `imap.agentmail.to` |
| IMAP port | `993` (SSL required) |
| SMTP host | `smtp.agentmail.to` |
| SMTP port | `465` (implicit TLS) or `587` (STARTTLS) |
| Username | Your inbox email (for example `bot@agentmail.to`) |
| Password | Your AgentMail API key (`am_...`) |

Create an inbox and API key in the [AgentMail console](https://console.agentmail.to). Treat the API key as a secret.

### Other providers

Any IMAP/SMTP provider works. Typical defaults:

| Provider | IMAP | SMTP |
|----------|------|------|
| Gmail | `imap.gmail.com:993` | `smtp.gmail.com:587` (app password) |
| Fastmail | `imap.fastmail.com:993` | `smtp.fastmail.com:587` |

Use a dedicated inbox — do not point the gateway at your personal mailbox.

## 2. Install Dependencies

```bash
uv sync
```

Email uses Python’s standard library (`imaplib`, `smtplib`, `email`) — no extra packages.

## 3. Export Local Secrets

```bash
export CURSOR_API_KEY="your-cursor-api-key"
export EMAIL_PASSWORD="your-email-password-or-api-key"
```

For AgentMail, `EMAIL_PASSWORD` is the API key. For Gmail, use an app password.

## 4. Create Gateway Configuration

```bash
mkdir -p ~/.cursor-agent
```

```bash
cat > ~/.cursor-agent/gateway.yaml <<'YAML'
workspace: /absolute/path/to/your/project
tool_profile: messaging

platforms:
  email:
    enabled: true
    address: bot@agentmail.to
    password: ${EMAIL_PASSWORD}
    imap_host: imap.agentmail.to
    imap_port: 993
    smtp_host: smtp.agentmail.to
    smtp_port: 465
    poll_interval_seconds: 15
    allowed_users:
      - you@example.com
YAML
```

Edit the file and replace:

- `/absolute/path/to/your/project` with the repository path the agent should use.
- `bot@agentmail.to` with your bot inbox address.
- `you@example.com` with the addresses allowed to talk to the agent (case-insensitive).

Do not put the real password in `gateway.yaml`; keep `password: ${EMAIL_PASSWORD}`.

An empty `allowed_users` list blocks everyone (by design). The gateway warns at startup if the allowlist is empty.

You can enable Telegram and email in the same `gateway.yaml` — each platform is independent.

## 5. Start The Gateway

```bash
uv run cursor-agent gateway --config ~/.cursor-agent/gateway.yaml
```

The email adapter polls IMAP for new (`UNSEEN`) messages and replies over SMTP with `In-Reply-To` / `References` so threads stay intact.

Keep this terminal open while testing. Stop with `Ctrl+C`.

## 6. Test By Email

From an allowlisted address, email the bot inbox:

1. Send a message with `/new` alone on the first line of the body (or in the subject if the body is empty).
   Expected reply: `Started a new conversation.`
2. Send a normal question in the same thread (or a new message from the same address).
   Expected behavior: the agent replies in-thread as plain text.
3. Send `/help` alone on the first line of the body (subject is used only when the body is empty).
   Expected behavior: lists `/new`, `/stop`, and `/help`.
4. Send free text before `/new`.
   Expected reply: hint to send `/new` first.
5. Send `/stop` while a run is in progress to cancel it.

Session identity is per sender address: `email:{sender}:{workspace_hash}` (see [ADR-004](decisions/ADR-004-session-key-workspace.md)).

Mail that arrives while the gateway is stopped stays `UNSEEN` and is processed on the next start (the adapter seeds only already-`SEEN` UIDs).

## 7. Optional Memory Files

Same Memory v1 path as Telegram/CLI. If `USER.md` / `MEMORY.md` exist under `~/.cursor-agent` (or `memory_root`), the first free-text turn after `/new` receives the bounded injection. Email does not expose `/memory show`; use the CLI when you need to inspect it.

## Notes And Limits

- Poll interval defaults to 15 seconds (not push/IDLE). Must be `> 0`.
- Attachments are ignored in v1 (body text / HTML-stripped text only).
- Cron → email delivery is not supported yet (Telegram cron unchanged).
- **Identity:** allowlisting matches the SMTP `From` address (case-insensitive). Unlike Telegram user IDs, `From` can be spoofed unless your provider rejects failed SPF/DKIM/DMARC before the message reaches INBOX. Use a dedicated bot inbox and a short allowlist.
- The adapter ignores mail whose `From` is the bot’s own address (prevents SMTP reply loops).
- Sample config: [examples/gateway.yaml.example](../examples/gateway.yaml.example).

## Related Docs

- [Telegram Gateway Onboarding](telegram-gateway-onboarding.md)
- [Setup guide](setup.md)
- [SECURITY.md](../SECURITY.md) — messaging threat model (`tool_profile: messaging`)
