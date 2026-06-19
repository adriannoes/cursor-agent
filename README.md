# Cursor Agent

> **Humans:** quick start below. **Contributors and agents:** start at **[AGENTS.md](AGENTS.md)**.

Clean-room agent inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent) behavior and [OpenClaw](https://github.com/openclaw/openclaw) gateway patterns. Powered by the [Cursor Python SDK](https://cursor.com/docs/sdk/python) and **Composer 2.5**.

Orchestration layer only — the SDK owns the agent loop, tools, and inference. **Cursor Agent** adds sessions, configuration, CLI UX, concurrency and security policy (tool profiles, hooks, allowlists).

## What it provides

- Interactive local REPL (`cursor-agent`)
- Persistent sessions (`cursor-agent sessions list`)
- Long-running messaging gateway, including Telegram (`cursor-agent gateway`)
- Local Memory v1 from `~/.cursor-agent/USER.md` and `~/.cursor-agent/MEMORY.md`
- Embedded cron scheduler managed by `cursor-agent cron list|add|remove`
- `coding` and `messaging` tool profiles for trusted dev vs untrusted input

## Documentation

| Document | Description |
|----------|-------------|
| [Setup guide](docs/setup.md) | Install, API key, gateway index for humans and AI agents |
| [Architecture](docs/architecture.md) | System design — sessions, facade, concurrency, profiles |
| [Architecture decisions](docs/decisions/README.md) | Curated ADR index for contributors |
| [AGENTS.md](AGENTS.md) | **Agent entry point** — conventions, verification, tool profiles |
| [SECURITY.md](SECURITY.md) | Messaging threat model, hooks, and acceptance probes |
| [Cursor API Key Onboarding](docs/cursor-api-key-onboarding.md) | Local setup guide for creating and exporting `CURSOR_API_KEY` |
| [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md) | Local setup guide for BotFather, `TELEGRAM_BOT_TOKEN`, allowlist, and gateway testing |
| [.env.example](.env.example) | Environment variable reference |
| [examples/README.md](examples/README.md) | Product-facing CLI, gateway, profiles, memory, and cron examples |

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (dependency manager used by this repo)
- [Cursor API key](https://cursor.com/dashboard/api) → `CURSOR_API_KEY`
- `cursor-sdk-bridge` on PATH (installed with `cursor-sdk`)

## Quick start

```bash
uv sync
export CURSOR_API_KEY="your-cursor-api-key"
uv run cursor-agent
```

The first command installs project dependencies into the local virtual environment.

The second command exports your Cursor API key for the current shell session.

The third command starts the interactive REPL with the default `coding` profile.

Alternatively, copy [.env.example](.env.example) to `.env` in the project directory, set `CURSOR_API_KEY`, and run `uv run cursor-agent` — the CLI loads CWD `.env` at startup without overriding variables already exported in your shell. Full key setup: [Cursor API Key Onboarding](docs/cursor-api-key-onboarding.md). Configuration precedence and overrides: [Setup guide](docs/setup.md#configuration).

## First run

On your first interactive launch (`uv run cursor-agent`), the CLI prints a welcome banner before the REPL prompt. The banner lists only real local commands — not gateway, cron, or Telegram shortcuts.

```text
==========================================================
                     >_  CURSOR AGENT
                   powered by Composer

   You bring the ideas. We handle the repetitive parts.

     ✓ Installation complete — you're ready to build.

Get started:
  - describe what you want, in plain language
  - /help            list commands
  - /new             start a fresh session
  - /skills          list available workspace skills
  - sessions list    see past sessions

  Setup & docs: docs/setup.md
==========================================================
```

On later launches the banner is shorter (logo, tagline, and a ready line). Suppress it with `--no-banner`, or when stdout is not a TTY or `CI=1` is set.

Before the first session, export `CURSOR_API_KEY` — see [Setup guide](docs/setup.md) and [Cursor API Key Onboarding](docs/cursor-api-key-onboarding.md). For Telegram gateway setup, see [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md).

Run the unit test gate without an API key:

```bash
uv run pytest -m "not integration" -v
```

This command runs the local test suite and skips integration tests that require `CURSOR_API_KEY`.

## Usage

```bash
uv run cursor-agent                         # interactive REPL (default: coding profile)
uv run cursor-agent --profile messaging     # validate messaging hooks locally
uv run cursor-agent sessions list             # list sessions for the workspace key
uv run cursor-agent cron list                 # list scheduled jobs
uv run cursor-agent gateway                   # gateway using ~/.cursor-agent/gateway.yaml
uv run cursor-agent gateway --config /path/to/gateway.yaml
```

Runtime config and session data live under `~/.cursor-agent/`. Override workspace, sessions DB, memory root, model, or tool profile via environment variables or YAML — see [Setup guide — Configuration](docs/setup.md#configuration) and [.env.example](.env.example).

## Memory

Memory v1 reads `~/.cursor-agent/USER.md` and `~/.cursor-agent/MEMORY.md` by default. Override the directory with `memory_root` in `~/.cursor-agent/config.yaml` or `CURSOR_AGENT__MEMORY_ROOT` (see [Setup guide — Configuration](docs/setup.md#configuration)). On the first user turn for a session, `cursor-agent` injects up to 8 KB before the message: up to 4 KB from `USER.md`, then the remaining budget from `MEMORY.md`. Oversized sections keep the end of the file.

After that first turn, memory is frozen for the session: edits or new files on disk are not picked up until `/new` starts a fresh session row (or `/resume` on a row that has not yet injected memory). `/memory show` always reads from disk at command time.

Use `/memory show` in the CLI to inspect the exact effective payload, quotas, byte counts, and truncation state. Missing files are treated as empty.

## Gateway (Telegram)

The gateway runs **cursor-agent** as a long-running bot process with `tool_profile: messaging` — read-only workspace, deny hooks, empty MCP, sandbox network off. See [SECURITY.md](SECURITY.md) and the step-by-step [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md).

Example config: [examples/gateway.yaml.example](examples/gateway.yaml.example). More examples: [examples/README.md](examples/README.md). Set `TELEGRAM_BOT_TOKEN` in the environment; do not commit real tokens.

## Cron Jobs

Scheduled jobs are configured in `~/.cursor-agent/cron/jobs.yaml` and run inside `cursor-agent gateway`. Use `cursor-agent cron list|add|remove` to manage them without hand-editing YAML. Job prompts are capped at 64 KiB, schedules use UTC by default, and jobs with `delivery.telegram.chat_id` deliver formatted output through the Telegram gateway. See [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md#9-optional-scheduled-cron-jobs) for the full setup and demo flow.

## Auto-approve risk (`coding` vs `messaging`)

The default **`coding`** profile runs the local SDK with **auto-approve** — tools execute without interactive prompts. That posture is a **developer convenience**, not a security boundary for public gateways or untrusted input. Optional dev hooks do not make `coding` gateway-safe.

On **create** and **resume**, `coding` omits `mcp_servers` so your Cursor **project** (`.cursor/mcp.json`) and **user** MCP settings stay in effect. `messaging` always passes an empty `mcp_servers` map and enables sandbox (network off) on both paths.

The **`messaging`** profile is read-only over the workspace: it auto-deploys deny hooks to `.cursor/hooks/messaging/` before the first agent run. Use `cursor-agent --profile messaging` to validate hooks locally before gateway work.

For bots and gateways, use `tool_profile: messaging` as specified in [SECURITY.md](SECURITY.md). Do not rely on `coding` + auto-approve outside a trusted local dev session.

## What's next

**v1.0** ships the first-run welcome banner, one-time getting-started hints, and a [setup docs index](docs/setup.md). Post-1.0 roadmap:

- Interactive `cursor-agent setup` wizard for API keys and local configuration.
- Discord and Slack gateway onboarding at the same bar as the Telegram guides.
- `full` tool profile with MCP-backed web search (GitHub + Brave Search).
- Terminal output fallback when the locale cannot render Unicode symbols (for example, replacing checkmarks with ASCII).
- Session search, gateway queueing, and a Textual-based TUI — promoted when demand justifies scope.

## Contributing

Bug reports, feature ideas, and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for issue templates and the local verification gate.

## License

MIT — see [LICENSE](LICENSE).
