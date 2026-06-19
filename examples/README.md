# cursor-agent examples

Product-facing examples for the orchestration layer. Use `cursor-agent` and its CLI — not raw `cursor_sdk` imports.

Historical SDK investigation scripts live under [internal-docs/sdk-spikes/](../internal-docs/sdk-spikes/) and are not recommended for new integrations.

## Local CLI

Interactive REPL with the default `coding` profile:

```bash
export CURSOR_API_KEY="your-cursor-api-key"
uv run cursor-agent
```

Validate the `messaging` profile and deny hooks locally before gateway work:

```bash
uv run cursor-agent --profile messaging
```

List persisted sessions for the current workspace key:

```bash
uv run cursor-agent sessions list
```

Inspect CLI options:

```bash
uv run cursor-agent --help
```

Full setup, configuration precedence, and verification without an API key: [docs/setup.md](../docs/setup.md).

## Tool profiles

| Profile | Use case |
|---------|----------|
| `coding` | Trusted local development — SDK auto-approve; optional dev hooks |
| `messaging` | Gateways and bots — read-only workspace, deny hooks, empty MCP, sandbox network off |

Override on the CLI with `--profile messaging` or set `CURSOR_AGENT__TOOL_PROFILE` / `tool_profile` in `~/.cursor-agent/config.yaml`. See [SECURITY.md](../SECURITY.md) for the messaging threat model.

## Gateway configuration

Copy [gateway.yaml.example](gateway.yaml.example) to `~/.cursor-agent/gateway.yaml`, set `TELEGRAM_BOT_TOKEN` in the environment, and run:

```bash
uv run cursor-agent gateway
```

Override the config path:

```bash
uv run cursor-agent gateway --config /path/to/gateway.yaml
```

Step-by-step Telegram onboarding: [docs/telegram-gateway-onboarding.md](../docs/telegram-gateway-onboarding.md).

## Memory files

Memory v1 reads `USER.md` and `MEMORY.md` from `~/.cursor-agent/` by default. Override with `CURSOR_AGENT__MEMORY_ROOT` or `memory_root` in config YAML.

In the REPL, use `/memory show` to inspect the effective payload. Edits on disk apply on the next `/new` session — see [README.md — Memory](../README.md#memory).

## Cron jobs

Scheduled jobs run inside the long-running gateway process. Manage them from the CLI:

```bash
uv run cursor-agent cron list
uv run cursor-agent cron list --strict
uv run cursor-agent cron show <job_id>
```

Jobs are stored in `~/.cursor-agent/cron/jobs.yaml`. Full operator notes: [docs/setup.md — Cron operator notes](../docs/setup.md#cron-operator-notes).

## Historical SDK spikes

Early bridge and tool-introspection probes are preserved for provenance only:

- [internal-docs/sdk-spikes/async_repl.py](../internal-docs/sdk-spikes/async_repl.py)
- [internal-docs/sdk-spikes/tools_list.py](../internal-docs/sdk-spikes/tools_list.py)

Do not treat these as the public integration path. Application code should use `cursor_agent.sdk_facade` instead of importing `cursor_sdk` directly.
