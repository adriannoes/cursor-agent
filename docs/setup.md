# cursor-agent setup

Public setup index for humans and AI agents. Use placeholders for secrets (`your-cursor-api-key`, `your-telegram-bot-token`) and keep real tokens in environment variables or gitignored local files only.

## Configuration

Configuration merges multiple sources with explicit precedence ([ADR-007](decisions/ADR-007-config-loader.md)):

```text
CLI flags > env (including CWD .env) > ~/.cursor-agent/config.yaml > defaults
```

At startup the CLI loads a gitignored `.env` file from the **current working directory** with `override=False` — values already exported in your shell win over the file. Pydantic settings read `CURSOR_AGENT__*` variables from the environment; `CURSOR_API_KEY` is the SDK exception (no prefix). See [.env.example](../.env.example) for placeholders.

| Variable | Purpose |
|----------|---------|
| `CURSOR_API_KEY` | Cursor API key for SDK agent runs (required for live inference) |
| `CURSOR_AGENT__RUNTIME__LOCAL__CWD` | Default workspace directory for local agents |
| `CURSOR_AGENT__MEMORY_ROOT` | Directory containing `USER.md` and `MEMORY.md` |
| `CURSOR_AGENT_SESSIONS_DB` | SQLite session store path |
| `CURSOR_AGENT_USAGE_TOKEN` | Optional OAuth override for `cursor-agent usage` (default: `accessToken` in `~/.config/cursor/auth.json`) |
| `CURSOR_AGENT__MODEL` | Model id (default: `grok-4.5`; pin Composer with `composer-2.5`) |
| `CURSOR_AGENT__TOOL_PROFILE` | `coding`, `messaging`, or `full` (default: `coding`) |
| `CURSOR_AGENT__MCP__FULL__SERVERS` | JSON list of curated MCP server ids for `full` (default: all curated) |
| `CURSOR_AGENT__MCP__FULL__GITHUB_TRANSPORT` | `github` transport for `full`: `http` (default) or `stdio` (case-insensitive) |

Legacy flat names `CURSOR_AGENT_WORKSPACE` and `CURSOR_AGENT_CONFIG` are **not supported** — use `CURSOR_AGENT__RUNTIME__LOCAL__CWD` and `~/.cursor-agent/config.yaml` instead.

### Choosing a model

When `model` is unset, the default is **Grok 4.5** (`grok-4.5`). Recommended first-party options:

| Id | Role |
|----|------|
| `grok-4.5` | Default when unset |
| `composer-2.5` | Alternate — pin for cost or preference |

Choose a model via:

- Interactive `cursor-agent setup` — model step accepts `1` (Grok), `2` (Composer), or a Cursor SDK model id
- YAML: `model: composer-2.5` in `~/.cursor-agent/config.yaml`
- Env: `CURSOR_AGENT__MODEL=composer-2.5`
- REPL: `/model composer-2.5` (bare `/model` lists first-party options)

Other Cursor SDK model ids are accepted (advanced). Existing YAML or env that already pins `composer-2.5` is preserved ([ADR-007](decisions/ADR-007-config-loader.md)).

### Tool profile `full` (curated MCP allowlist)

`full` injects a curated MCP allowlist for trusted **local** operators (`github` defaults to remote HTTP; Brave/Playwright stay local stdio). It is **local-only** — the Telegram gateway refuses to start with `full` (use `messaging` there). There is no `cursor-agent mcp *` CLI; enable the profile and set secrets via env. Design details: [ADR-029](decisions/ADR-029-mcp-registry-full-profile.md) and [Architecture — Tool profiles](architecture.md#tool-profiles).

**Effective profile:** if config or session is `messaging`, messaging wins. Otherwise, among `coding` / `full`, the **session** profile wins over config (example: `config=full` + `session=coding` → `coding`).

Enable with any of:

```bash
cursor-agent setup --tool-profile full --yes
```

```bash
export CURSOR_AGENT__TOOL_PROFILE=full
```

Or in `~/.cursor-agent/config.yaml`:

```yaml
tool_profile: full
```

Curated servers and required env (secrets stay in env — never put tokens in YAML plaintext):

| Server id | Required env | Launch notes |
|-----------|--------------|--------------|
| `github` | `GITHUB_PERSONAL_ACCESS_TOKEN` | **Default:** official remote HTTP (`https://api.githubcopilot.com/mcp/`). **Opt-in:** Docker stdio via `mcp.full.github_transport: stdio` |
| `brave-search` | `BRAVE_API_KEY` | `npx -y @brave/brave-search-mcp-server` |
| `playwright` | _(none)_ | `npx -y @playwright/mcp@0.0.78` (pinned; bump deliberately) |

**Default path — `github` without Docker** (PAT required; omit+warn if missing):

```bash
export CURSOR_AGENT__TOOL_PROFILE=full
export CURSOR_AGENT__MCP__FULL__SERVERS='["github"]'
export GITHUB_PERSONAL_ACCESS_TOKEN="your-github-pat"
# CURSOR_AGENT__MCP__FULL__GITHUB_TRANSPORT defaults to http — no Docker needed
cursor-agent
```

**Operator choice — local Docker stdio** (air-gapped / remote blocked hosts):

```bash
export CURSOR_AGENT__TOOL_PROFILE=full
export CURSOR_AGENT__MCP__FULL__SERVERS='["github"]'
export GITHUB_PERSONAL_ACCESS_TOKEN="your-github-pat"
export CURSOR_AGENT__MCP__FULL__GITHUB_TRANSPORT=stdio
# requires a running Docker daemon and image ghcr.io/github/github-mcp-server
cursor-agent
```

YAML equivalent for the transport choice:

```yaml
tool_profile: full
mcp:
  full:
    github_transport: stdio  # default is http when omitted
```

Example local `.env` placeholders for the full curated set (see [.env.example](../.env.example)):

```bash
export CURSOR_AGENT__TOOL_PROFILE=full
export GITHUB_PERSONAL_ACCESS_TOKEN="your-github-pat"
export BRAVE_API_KEY="your-brave-api-key"
```

**Missing env (omit, do not hard-fail):** if a curated server’s required env is unset, that server is omitted and a one-time warning is emitted. The REPL still starts; secret values are never logged.

Optional allowlist. When the key is **omitted** / unset (`null`), all curated ids are enabled. An **explicit empty list** is different — it injects an empty MCP map and does **not** emit omit-missing-env warnings:

```yaml
mcp:
  full:
    servers: [github, brave-search, playwright]  # subset or all curated ids
# servers: []   # empty map on purpose — not the same as omitting the key
```

Env form (JSON list):

```bash
export CURSOR_AGENT__MCP__FULL__SERVERS='["github","playwright"]'
# export CURSOR_AGENT__MCP__FULL__SERVERS='[]'  # empty map; no omit warnings
```

Ops may use `npx mcporter` for MCP discovery outside this project; it is **not** a `cursor-agent` dependency.

## Interactive setup

`cursor-agent setup` writes local configuration (API key in `.env`, non-secrets in `~/.cursor-agent/config.yaml`) without changing ADR-007 precedence. Shell exports still win over CWD `.env`, which wins over YAML, which wins over defaults.

Setup does **not** export variables into the current shell. After apply, run `source .env` (or open a new terminal) so `CURSOR_API_KEY` and other env keys are visible to the next process.

### Humans (interactive)

On a TTY, run without value-bearing flags (opt-in — setup is never forced on first REPL launch):

```bash
cursor-agent setup
```

Interactive setup uses a guided step UI: API key (hidden input), workspace, optional memory/sessions paths, model choice (`1` / `2` / SDK id), and tool profile (`1` / `2` / `3` / name — including `full` for trusted local use). After a summary confirmation it writes configuration.

Non-interactive `setup apply` (value-bearing flags + `--yes`) stays terse and unchanged — no step chrome.

Verify and inspect:

```bash
cursor-agent setup check
cursor-agent setup show
```

These commands validate offline readiness and print effective settings with the API key redacted.

### AI agents (headless)

Non-interactive apply uses value-bearing flags and never prompts. `--yes` is
recommended: it skips the interactive wizard when stdout is a TTY (value flags
already imply a non-wizard path; `--yes` documents agent intent explicitly).

```bash
cursor-agent setup \
  --api-key "your-cursor-api-key" \
  --workspace "/path/to/your/project" \
  --yes
```

This command writes the same artifacts as the interactive path. Follow with `cursor-agent setup check` before starting the REPL or gateway.

### Workspace override

Set the agent workspace without editing YAML:

```bash
export CURSOR_AGENT__RUNTIME__LOCAL__CWD="/path/to/your/project"
```

This command points session keys and SDK workspace resolution at the given directory.

Or add the same key to a CWD `.env` file (see [Cursor API Key Onboarding — Optional local env file](cursor-api-key-onboarding.md#3-optional-local-env-file)).

### Sessions database override

```bash
export CURSOR_AGENT_SESSIONS_DB="/path/to/sessions.db"
```

This command relocates the SQLite session store away from the default `~/.cursor-agent/sessions.db`.

The default database uses SQLite **schema version 1**; opening an older file without version metadata is upgraded automatically on startup with existing session rows preserved. See [Architecture — Session SQLite baseline](architecture.md#session-sqlite-baseline-v1) for details.

### Plan usage (`cursor-agent usage`)

`uv run cursor-agent usage` prints a snapshot of the current Cursor plan quota (total / auto / API). It calls an **undocumented** dashboard endpoint and is best-effort — the response shape may change without notice.

Auth (in order): `CURSOR_AGENT_USAGE_TOKEN`, then the OAuth `accessToken` from `~/.config/cursor/auth.json` written by the **official** Cursor Agent CLI (`agent login`). That store lives outside `~/.cursor-agent/`. This package has no `login` command. `CURSOR_API_KEY` is not accepted by the usage endpoint.

### Memory root override

```bash
export CURSOR_AGENT__MEMORY_ROOT="/path/to/memory"
```

This command changes where `USER.md` and `MEMORY.md` are read for memory injection.

### Verify configuration locally

```bash
uv run pytest -m "not integration and not package_smoke" -v
```

This command runs the unit test gate without requiring `CURSOR_API_KEY` (matches the CI `quality` job). Before a release tag, also run `uv run pytest -m package_smoke -v`.

```bash
uv run ruff check src tests && uv run mypy --strict src
```

This command matches the contributor lint and type-check gate from [AGENTS.md](../AGENTS.md).

## Humans

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (dependency manager used by this repo)
- A [Cursor API key](https://cursor.com/dashboard/api) exported as `CURSOR_API_KEY`
- `cursor-sdk-bridge` on PATH (installed with `cursor-sdk`)

### Install

```bash
uv sync
```

This command installs project dependencies into the local virtual environment.

### Configure `CURSOR_API_KEY`

Do not commit real API keys. Follow [Cursor API Key Onboarding](cursor-api-key-onboarding.md) to create or copy a key, export it in your shell, or use a gitignored CWD `.env` file from [.env.example](../.env.example). For precedence and other overrides, see [Configuration](#configuration) above.

```bash
export CURSOR_API_KEY="your-cursor-api-key"
```

This command makes the key available to processes started from the current terminal session.

### First local use

```bash
uv run cursor-agent
```

This command starts the interactive REPL with the default `coding` profile. On first launch you see the welcome banner (see [README.md — First run](../README.md#first-run)); type a plain-language request or `/help` to explore commands.

Verify the project without an API key:

```bash
uv run pytest -m "not integration and not package_smoke" -v
```

This command confirms the local project passes unit tests without SDK access.

When you need SDK-backed behavior, set `CURSOR_API_KEY` and run integration tests as described in the API key onboarding guide.

## For AI agents

Start from [AGENTS.md](../AGENTS.md) for repository conventions, then use this table to reach the right public doc without prior chat context.

| Document | When to use | Verify command |
|----------|-------------|----------------|
| [docs/setup.md](setup.md) | Install, API key, config contract, gateway index, cron operator notes | `uv run pytest -m "not integration and not package_smoke" -v` |
| [docs/architecture.md](architecture.md) | System design, sessions, facade, tool profiles | — |
| [docs/decisions/README.md](decisions/README.md) | Recorded architecture decisions (ADRs) | — |
| [docs/cursor-api-key-onboarding.md](cursor-api-key-onboarding.md) | Create or export `CURSOR_API_KEY` | `test -n "$CURSOR_API_KEY" && echo "CURSOR_API_KEY is set"` |
| [docs/telegram-gateway-onboarding.md](telegram-gateway-onboarding.md) | BotFather, `TELEGRAM_BOT_TOKEN`, gateway config, cron setup | `uv run cursor-agent gateway --config ~/.cursor-agent/gateway.yaml` (after config) |
| [README.md](../README.md) | Project overview, first-run banner shape, usage examples | `uv run cursor-agent --help` |
| [examples/README.md](../examples/README.md) | Product-facing CLI, gateway, profiles, memory, and cron examples | `uv run cursor-agent --help` |
| [SECURITY.md](../SECURITY.md) | Messaging threat model, `messaging` profile, hook policy | `uv run pytest tests/unit/test_messaging_profile.py -v` |
| [.env.example](../.env.example) | Canonical `CURSOR_AGENT__*` and `CURSOR_API_KEY` placeholders | `grep CURSOR_AGENT .env.example` |

## Gateway (Telegram)

The CLI welcome banner is local-only. Telegram has its own first-contact flow — do not expect `/skills`, `sessions list`, or CLI slash commands on Telegram.

**First contact:** In a private chat, click Telegram's Start button or send `/start`. The bot replies with a short hint to send `/new` — this is onboarding UX, not an active session.

**Start a conversation:** Send `/new`. The bot confirms a fresh session; then send free-text questions about the configured workspace.

**Formatting:** Assistant replies use a small Markdown subset rendered to Telegram HTML. GitHub-flavored tables appear as compact bullet lines or labeled row blocks — not raw pipe syntax (`| col |`). For supported syntax, limitations, and manual checks, see [Markdown formatting troubleshooting](telegram-gateway-onboarding.md#markdown-formatting-looks-wrong) in the gateway onboarding guide.

Full BotFather steps, allowlist setup, gateway YAML, and end-to-end Telegram tests: [Telegram Gateway Onboarding](telegram-gateway-onboarding.md).

## Cron operator notes

Scheduled jobs run inside the long-running gateway process. These notes are for operators — `cursor-agent cron` commands do not appear in the CLI welcome banner.

- `cursor-agent cron list` — metadata-only listing (schedule, next run, runtime, chat ID). Invalid per-job entries are skipped with `warning:` lines; the command still exits 0.
- `cursor-agent cron list --strict` — same listing, but fail fast on any invalid entry.
- `cursor-agent cron show <job_id>` — load the full prompt body for one job.
- Jobs live in `~/.cursor-agent/cron/jobs.yaml` and reload when the file mtime changes. After fixing a YAML parse error, save or touch the file so the scheduler picks up the correction.
- Full setup, demo flow, and delivery behavior: [Optional scheduled cron jobs](telegram-gateway-onboarding.md#9-optional-scheduled-cron-jobs) (section 9 of the gateway onboarding guide).
