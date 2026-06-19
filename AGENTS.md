# AGENTS.md — Guide for Contributors and AI Agents

> **Primary onboarding doc** for this repository. Humans: pair with [CONTRIBUTING.md](CONTRIBUTING.md). AI agents: read this file before implementing anything.

---

## What is cursor-agent

**cursor-agent** is a clean-room orchestration layer for the [Cursor Python SDK](https://cursor.com/docs/sdk/python) and **Composer 2.5**. It delegates the agentic loop, tools, and inference to the SDK, and implements sessions, configuration, concurrency, CLI UX, and security policy (hooks, tool profiles, allowlists).

You may study reference projects (for example [Hermes Agent](https://github.com/NousResearch/hermes-agent) or [OpenClaw](https://github.com/openclaw/openclaw)) for **behavior patterns only** — **zero copied code**; reimplement in `cursor_agent`.

---

## Tool profiles

| Profile | Use case | Posture |
|---------|----------|---------|
| `coding` | Local development, trusted operator | SDK auto-approve; optional dev hooks only |
| `messaging` | Gateways, bots, untrusted input | Read-only workspace; deny hooks; empty MCP; sandbox network off |

For gateways and bots, **always** use `tool_profile: messaging`. Do not rely on `coding` + auto-approve outside a trusted local session. With `messaging`, the CLI deploys deny hooks into the active workspace at `{workspace}/.cursor/hooks/messaging/` (manifest at `{workspace}/.cursor/hooks.json`) at runtime — not editor-local config. See [SECURITY.md](SECURITY.md) for the threat model, hook layout, and acceptance probes.

CLI override: `cursor-agent --profile messaging`

---

## How to work

1. **Read the request and relevant source** before editing — grep-friendly modules, explicit types, small focused functions.
2. **TDD:** for functional changes, write a **failing** pytest test → implement → green.
3. **Keep SDK isolation:** import `cursor_sdk` only from `src/cursor_agent/sdk_facade.py`.
4. **Verify locally** before opening a PR — commands below match CI (see [CONTRIBUTING.md](CONTRIBUTING.md)).
5. **Do not commit secrets** — use `CURSOR_AGENT__*` env vars or `CURSOR_API_KEY` (see `.env.example`).

### Local verification (no API key required for unit tests)

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest -m "not integration" -v
```

Integration tests (`pytest -m integration -v`) require `CURSOR_API_KEY` and skip when it is unset.

Focused messaging/hook checks:

```bash
uv run pytest tests/unit/test_cli_profile.py tests/unit/test_messaging_profile.py \
  tests/unit/test_messaging_hooks_deploy.py tests/unit/test_hook_workspace_deploy.py \
  tests/unit/test_cli_bootstrap.py tests/unit/test_pool.py -v
```

---

## Conventions

| Concept | Value |
|---------|-------|
| Project name | `cursor-agent` |
| Python package | `cursor_agent` |
| Config directory | `~/.cursor-agent` |
| Environment variables | prefix `CURSOR_AGENT__*` (see also `CURSOR_API_KEY` in `.env.example`) |
| CLI | `cursor-agent` |
| Dependency manager | `uv` (per `pyproject.toml`) |
| Linter / formatter | `ruff` |
| Type checker | `mypy --strict` on `src/` |
| Tests | `pytest` in `./tests` |
| Code and comments | English |

### Code style (contributors)

- **Grep-friendly names** — specific symbols; avoid generic `data`, `handler`, `util`.
- **Explicit types** on public APIs; no untyped surfaces.
- **Imports at module top** — no inline imports unless a documented circular-dependency exception.
- **Small units** — short functions; one responsibility per module.
- **Comments** explain *why* and provenance, not obvious syntax.
- **Error messages** include the offending value and expected shape.

---

## What NOT to do

- **Do not copy code** from reference projects — study patterns, reimplement in `cursor_agent`.
- **Do not import `cursor_sdk`** outside `sdk_facade.py`.
- **Do not skip TDD** for functional requirements.
- **Do not assume** features exist — verify in source and tests.
- **Do not create** unsolicited documentation files.
- **Do not use** `cursor-hermes` — the correct name is `cursor-agent`.

---

## Quick links

For install, API key, and gateway setup without prior context, start at [docs/setup.md](docs/setup.md).

| Document | Description |
|----------|-------------|
| [docs/setup.md](docs/setup.md) | Public setup index for humans and AI agents |
| [docs/architecture.md](docs/architecture.md) | System design — sessions, facade, concurrency |
| [docs/decisions/README.md](docs/decisions/README.md) | Curated architecture decision records |
| [README.md](README.md) | Project overview, first-run banner, usage |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Issues, pull requests, verification gate |
| [SECURITY.md](SECURITY.md) | Messaging threat model and hook acceptance |
| [docs/cursor-api-key-onboarding.md](docs/cursor-api-key-onboarding.md) | Local `CURSOR_API_KEY` setup |
| [docs/telegram-gateway-onboarding.md](docs/telegram-gateway-onboarding.md) | Telegram bot and gateway setup |
| [.env.example](.env.example) | Environment variable reference |
| [pyproject.toml](pyproject.toml) | Package metadata and quality gates |
| [hooks/messaging/](hooks/messaging/) | Versioned deny-hook scripts |
| [examples/gateway.yaml.example](examples/gateway.yaml.example) | Sample gateway configuration |
| [Cursor Python SDK](https://cursor.com/docs/sdk/python) | Upstream SDK documentation |
| [Cursor Hooks](https://cursor.com/docs/hooks) | Hook schema reference |
