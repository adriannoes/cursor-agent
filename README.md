# cursor-agent

> **Humans:** quick start below. **Agents:** start at **[AGENTS.md](AGENTS.md)**.

Clean-room agent inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent) behavior and [OpenClaw](https://github.com/openclaw/openclaw) gateway patterns — reference docs and codebases may be studied for patterns, with **zero copied code** (not a fork). Powered by the [Cursor Python SDK](https://cursor.com/docs/sdk/python) and **Composer 2.5**.

Orchestration layer only — the SDK owns the agent loop, tools, and inference. **cursor-agent** adds sessions, configuration, CLI UX, concurrency, and security policy (tool profiles, hooks, allowlists).

## What it provides

- Interactive local REPL (`cursor-agent`)
- Persistent sessions (`cursor-agent sessions list`)
- Long-running messaging gateway, including Telegram (`cursor-agent gateway`)
- Local Memory v1 from `~/.cursor-agent/USER.md` and `~/.cursor-agent/MEMORY.md`
- `coding` and `messaging` tool profiles for trusted dev vs untrusted input

## Documentation

| Document | Description |
|----------|-------------|
| [AGENTS.md](AGENTS.md) | **Agent entry point** — repo map, conventions, verification |
| [SECURITY.md](SECURITY.md) | Messaging threat model, hooks, and acceptance probes |
| [Cursor API Key Onboarding](docs/cursor-api-key-onboarding.md) | Local setup guide for creating and exporting `CURSOR_API_KEY` |
| [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md) | Local setup guide for BotFather, `TELEGRAM_BOT_TOKEN`, allowlist, and gateway testing |
| [.env.example](.env.example) | Environment variable reference |

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

For a local `.env` file, copy [.env.example](.env.example) to `.env`, set `CURSOR_API_KEY`, and keep `.env` out of git. Full key setup: [Cursor API Key Onboarding](docs/cursor-api-key-onboarding.md).

Run the unit test gate without an API key:

```bash
uv run pytest -m "not integration" -v
```

## Usage

```bash
uv run cursor-agent                         # interactive REPL (default: coding profile)
uv run cursor-agent --profile messaging     # validate messaging hooks locally
uv run cursor-agent sessions list             # list sessions for the workspace key
uv run cursor-agent gateway                   # gateway using ~/.cursor-agent/gateway.yaml
uv run cursor-agent gateway --config /path/to/gateway.yaml
```

Runtime config and session data live under `~/.cursor-agent/` (see [.env.example](.env.example) for overrides).

## Memory

Memory v1 reads `~/.cursor-agent/USER.md` and `~/.cursor-agent/MEMORY.md`. On the first user turn for a session, `cursor-agent` injects up to 8 KB before the message: up to 4 KB from `USER.md`, then the remaining budget from `MEMORY.md`. Oversized sections keep the end of the file.

After that first turn, memory is frozen for the session: edits or new files on disk are not picked up until `/new` starts a fresh session row (or `/resume` on a row that has not yet injected memory). `/memory show` always reads from disk at command time.

Use `/memory show` in the CLI to inspect the exact effective payload, quotas, byte counts, and truncation state. Missing files are treated as empty.

## Gateway (Telegram)

The gateway runs **cursor-agent** as a long-running bot process with `tool_profile: messaging` — read-only workspace, deny hooks, empty MCP, sandbox network off. See [SECURITY.md](SECURITY.md) and the step-by-step [Telegram Gateway Onboarding](docs/telegram-gateway-onboarding.md).

Example config: [examples/gateway.yaml.example](examples/gateway.yaml.example). Set `TELEGRAM_BOT_TOKEN` in the environment; do not commit real tokens.

## Development hooks (optional)

For local work with `tool_profile: coding`, you may add an optional `.cursor/hooks.json` in your workspace to moderate tool behavior (for example, shell gates). **cursor-agent does not install messaging deny hooks for `coding`** — any dev hooks are a documented developer convenience only. See the [Cursor Hooks](https://cursor.com/docs/hooks) schema and wire hook scripts under `.cursor/hooks/` as needed.

For `tool_profile: messaging`, deny hooks are **auto-deployed** on CLI startup to `.cursor/hooks.json` and `.cursor/hooks/messaging/*.sh` in the active workspace (source versioned under `hooks/messaging/` in the repo). Sandbox and MCP policy are defined in [SECURITY.md](SECURITY.md).

## Auto-approve risk (`coding` vs `messaging`)

The default **`coding`** profile runs the local SDK with **auto-approve** — tools execute without interactive prompts. That posture is a **developer convenience**, not a security boundary for public gateways or untrusted input. Optional dev hooks do not make `coding` gateway-safe.

The **`messaging`** profile is read-only over the workspace: it auto-deploys deny hooks to `.cursor/hooks/messaging/`, passes `mcp_servers: {}`, and enables `sandbox_options.enabled: true` (network off). Use `cursor-agent --profile messaging` to validate hooks locally before gateway work.

For bots and gateways, use `tool_profile: messaging` as specified in [SECURITY.md](SECURITY.md). Do not rely on `coding` + auto-approve outside a trusted local dev session.

## License

MIT — see [LICENSE](LICENSE).
