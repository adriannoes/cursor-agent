# cursor-agent

> **Agents:** start at **[AGENTS.md](AGENTS.md)**

Clean-room agent inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent) behavior and [OpenClaw](https://github.com/openclaw/openclaw) gateway patterns — reference docs and codebases may be studied for patterns, with **zero copied code** (not a fork). Powered by the [Cursor Python SDK](https://cursor.com/docs/sdk/python) and **Composer 2.5**.

Orchestration layer only — the SDK owns the agent loop, tools, and inference.

## Documentation

| Document | Description |
|----------|-------------|
| [AGENTS.md](AGENTS.md) | **Agent entry point** — repo map, conventions, verification |
| [SECURITY.md](SECURITY.md) | Messaging threat model, hooks, and acceptance probes |
| [.env.example](.env.example) | Environment variable reference |

## Prerequisites

- Python 3.11+
- [Cursor API key](https://cursor.com/dashboard/api) → `CURSOR_API_KEY`
- `cursor-sdk-bridge` on PATH (installed with `cursor-sdk`)

## Development hooks (optional)

For local work with `tool_profile: coding`, you may add an optional `.cursor/hooks.json` in your workspace to moderate tool behavior (for example, shell gates). **cursor-agent does not install messaging deny hooks for `coding`** — any dev hooks are a documented developer convenience only. See the [Cursor Hooks](https://cursor.com/docs/hooks) schema and wire hook scripts under `.cursor/hooks/` as needed.

For `tool_profile: messaging`, deny hooks are **auto-deployed** on CLI startup to `.cursor/hooks.json` and `.cursor/hooks/messaging/*.sh` in the active workspace (source versioned under `hooks/messaging/` in the repo). Sandbox and MCP policy are defined in [SECURITY.md](SECURITY.md).

## Auto-approve risk (`coding` vs `messaging`)

The default **`coding`** profile runs the local SDK with **auto-approve** — tools execute without interactive prompts. That posture is a **developer convenience**, not a security boundary for public gateways or untrusted input. Optional dev hooks do not make `coding` gateway-safe.

The **`messaging`** profile is read-only over the workspace: it auto-deploys deny hooks to `.cursor/hooks/messaging/`, passes `mcp_servers: {}`, and enables `sandbox_options.enabled: true` (network off). Use `cursor-agent --profile messaging` to validate hooks locally before gateway work.

For bots and gateways, use `tool_profile: messaging` as specified in [SECURITY.md](SECURITY.md). Do not rely on `coding` + auto-approve outside a trusted local dev session.

## License

MIT — see [LICENSE](LICENSE).
