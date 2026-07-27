<p align="center">
  <img
    src=".github/assets/cursor-agent-banner.jpg"
    alt="CURSOR-AGENT banner — pixel art agent with Cursor Harness, Composer Model, and defense-in-depth security panels"
    width="100%"
  />
</p>

> **Humans:** quick start below. **AI Agents:** start at **[AGENTS.md](AGENTS.md)**.

Clean-room orchestration for the [Cursor Python SDK](https://cursor.com/docs/sdk/python) — sessions, CLI, concurrency, and security policy. The SDK owns the agent loop, tools, and inference. Default model: **Grok 4.5** (pin **Composer 2.5** via config / `CURSOR_AGENT__MODEL` / `/model`).

## Quick start

```bash
uv sync
export CURSOR_API_KEY="your-cursor-api-key"
uv run cursor-agent
```

Or copy [.env.example](.env.example) → `.env`, set `CURSOR_API_KEY`, and run `uv run cursor-agent` (CWD `.env` loads without overriding shell exports). Key setup: [Cursor API Key Onboarding](docs/cursor-api-key-onboarding.md). Full config: [Setup guide](docs/setup.md#configuration).

**Needs:** Python 3.11+, [uv](https://docs.astral.sh/uv/), `CURSOR_API_KEY`, and `cursor-sdk-bridge` on PATH (comes with `cursor-sdk`).

## First run

On first interactive launch the CLI prints a welcome banner (local commands only — not gateway/cron/Telegram):

```text
==========================================================
                     >_  CURSOR AGENT
                   powered by Cursor

   You bring the ideas. We handle the repetitive parts.

     ✓ Installation complete — you're ready to build.

Get started:
  - describe what you want, in plain language
  - /help            list commands
  - /new             start a fresh session
  - /skills          list skills (also: skills list)
  - skills seed      optional starters; skills path
  - sessions list    see past sessions
  - doctor           check local setup health

  Setup & docs: docs/setup.md
==========================================================
```

Later launches are shorter. Suppress with `--no-banner`, or when stdout is not a TTY / `CI=1`. Interactive config: `cursor-agent setup` — see [Interactive setup](docs/setup.md#interactive-setup).

## Common commands

```bash
uv run cursor-agent                         # REPL (default: coding profile)
uv run cursor-agent --profile messaging     # validate messaging hooks locally
uv run cursor-agent --profile full          # curated MCP (local only)
uv run cursor-agent sessions list           # past sessions for this workspace
uv run cursor-agent sessions show <id>      # inspect one workspace session
uv run cursor-agent sessions delete <id> --yes
uv run cursor-agent sessions prune --older-than 30 --keep 10 --yes
uv run cursor-agent skills list             # discovered skills
uv run cursor-agent skills seed             # copy starter pack into .cursor/skills/
uv run cursor-agent cron list               # scheduled jobs
uv run cursor-agent usage                   # plan usage snapshot (total / auto / API)
uv run cursor-agent usage --json
uv run cursor-agent auth status --no-probe  # local API key + usage OAuth (offline)
uv run cursor-agent auth status             # same + live probes when credentials present
uv run cursor-agent doctor                  # aggregate setup / auth / hooks / gateway (local)
uv run cursor-agent doctor --gateway-config ~/.cursor-agent/gateway.yaml
uv run cursor-agent gateway check           # offline gateway.yaml validate (no Telegram)
uv run cursor-agent gateway                 # ~/.cursor-agent/gateway.yaml
uv run cursor-agent gateway --config /path/to/gateway.yaml
uv run cursor-agent models                  # live model catalog (needs CURSOR_API_KEY)
uv run cursor-agent models --json
```

Runtime data lives under `~/.cursor-agent/`. Overrides: [Setup — Configuration](docs/setup.md#configuration) and [.env.example](.env.example).

`cursor-agent usage` hits Cursor's dashboard endpoint (best-effort; not the SDK). Auth: OAuth token from `~/.config/cursor/auth.json` (via official `agent login`) or `CURSOR_AGENT_USAGE_TOKEN` — not `CURSOR_API_KEY`.

`cursor-agent auth status` reports both channels without printing secrets. Use `--no-probe` for a fast/air-gapped local check; default probes when a credential is present (API-key probe launches the SDK bridge).

`cursor-agent doctor` aggregates setup, auth, messaging hooks, and offline gateway YAML (when present). Local by default; `--probe` opt-in. Prefer `--gateway-config` (not `--config`). `gateway check` validates YAML without starting the long-lived process.

`cursor-agent models` lists the live Cursor catalog via the SDK bridge (needs `CURSOR_API_KEY`). Soft-catalog ids are marked `(recommended)`; use `--json` for scripts.

## Skills

Starter playbooks ship under [`skills/`](skills/). Paste third-party AgentSkills into project or user `.cursor/skills/`. CLI: `skills path` / `list` / `seed`. Details: [`skills/README.md`](skills/README.md) and [Setup — skills](docs/setup.md).

## Tool profiles

| Profile | Use when |
|---------|----------|
| `coding` (default) | Trusted local dev — SDK auto-approve |
| `messaging` | Gateways / bots / untrusted input — read-only + deny hooks |
| `full` | Trusted local operator + curated MCP (GitHub, Brave, Playwright) |

For bots and gateways, always use `messaging`. Threat model: [SECURITY.md](SECURITY.md). Profile matrix: [Architecture](docs/architecture.md#mcp-and-sandbox-by-profile-create-and-resume).

## Gateway, cron, and memory

- **Telegram gateway:** long-running bot with `tool_profile: messaging`. Setup: [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md). Sample: [examples/gateway.yaml.example](examples/gateway.yaml.example).
- **Cron:** `~/.cursor-agent/cron/jobs.yaml`, managed by `cursor-agent cron list|add|remove`, runs inside the gateway. Demo: [Telegram guide — cron](docs/telegram-gateway-onboarding.md#9-optional-scheduled-cron-jobs).
- **Memory (v1):** injects `USER.md` + `MEMORY.md` on the first turn of a session (frozen afterward until `/new`). Inspect with `/memory show`. Details: [Setup](docs/setup.md).

More product examples: [examples/README.md](examples/README.md).

## Docs

| Document | Description |
|----------|-------------|
| [Setup guide](docs/setup.md) | Install, API key, config, operator CLI, skills, gateway index |
| [AGENTS.md](AGENTS.md) | Conventions and verification for AI agents |
| [SECURITY.md](SECURITY.md) | Messaging threat model and hooks |
| [Architecture](docs/architecture.md) | Sessions, facade, concurrency, profiles |
| [Architecture decisions](docs/decisions/README.md) | ADR index |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Issues, PRs, local quality gate |

## Releases

- **v1.3.0** *(not yet tagged on `main`)* — operator CLI hygiene: `auth status`, `doctor`, `gateway check`, `sessions show|delete|prune`, live `models`; docs, package-smoke, and operator smoke for the release train.
- **v1.2.1** — skills discovery harden + package-smoke isolation after the v1.2.0 review follow-up.
- **v1.2.0** — product skills pack (`skills/`, `skills path|list|seed`, BYO paste).
- Earlier: v1.1.0 (`full` profile, Grok default), v1.0 (first-run banner + setup index).

Roadmap: operator CLI hygiene (`auth`/`doctor`/`gateway check`/sessions hygiene/`models`) for v1.3.0 (docs/closeout on this branch; not yet merged to main), logging persistence (PRD-015), Discord/Slack onboarding (PRD-014), Unicode terminal fallback, session search / queueing / TUI when demand justifies.

## Contributing

Bug reports, ideas, and PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
