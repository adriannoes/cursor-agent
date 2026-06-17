# AGENTS.md — Guide for AI Agents

> **Primary entry point** for agent sessions in this repository. Read this file before implementing anything.

---

## What is cursor-agent

**cursor-agent** is a clean-room orchestration layer for the [Cursor Python SDK](https://cursor.com/docs/sdk/python) and **Composer 2.5**. It delegates the agentic loop, tools, and inference to the SDK, and implements sessions, configuration, concurrency, CLI UX, and security policy (hooks, tool profiles, allowlists).

You may study reference projects (for example [Hermes Agent](https://github.com/NousResearch/hermes-agent) or [OpenClaw](https://github.com/openclaw/openclaw)) for **behavior patterns only** — **zero copied code**; reimplement in `cursor_agent`.

---

## Repository map

```text
cursor-agent/
├── AGENTS.md              ← you are here
├── README.md              ← human-facing overview
├── SECURITY.md            ← messaging threat model and acceptance probes
├── LICENSE                ← MIT
├── .env.example           ← documented environment variables
├── pyproject.toml         ← package, tooling, and wheel includes
│
├── src/cursor_agent/      ← production Python package
│   ├── sdk_facade.py      ← only module that imports cursor_sdk
│   ├── messaging_hooks.py ← hook install/deploy for messaging profile
│   ├── pool.py            ← session agent pool
│   └── cli/               ← Typer CLI entry point
│
├── hooks/messaging/       ← versioned hook scripts (also packaged in wheel)
├── tests/                 ← pytest unit and integration tests
└── examples/              ← SDK spike scripts (async REPL, tools inventory)
```

**Note:** Runtime hook deployment writes to `{workspace}/.cursor/hooks.json` and `{workspace}/.cursor/hooks/messaging/` when `tool_profile` is `messaging`. That workspace `.cursor/` tree is generated at runtime — it is not the same as any local-only planning directories you may have on disk.

---

## Tool profiles

| Profile | Use case | Posture |
|---------|----------|---------|
| `coding` | Local development, trusted operator | SDK auto-approve; optional dev hooks only |
| `messaging` | Gateways, bots, untrusted input | Read-only workspace; deny hooks; empty MCP; sandbox network off |

For gateways and bots, **always** use `tool_profile: messaging`. Do not rely on `coding` + auto-approve outside a trusted local session. See [SECURITY.md](SECURITY.md) for the threat model, hook layout, and acceptance probes.

CLI override: `cursor-agent --profile messaging`

---

## How to work

1. **Read the user request and relevant source** before editing — grep-friendly modules, explicit types, small functions.
2. **TDD:** for functional changes, write a **failing** pytest test → implement → green.
3. **Keep SDK isolation:** import `cursor_sdk` only from `src/cursor_agent/sdk_facade.py`.
4. **Do not commit** unless the user explicitly asks.
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
  tests/unit/test_hooks_deploy.py tests/unit/test_cli_bootstrap.py tests/unit/test_pool.py -v
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
| Tests | `pytest` in `./tests` |
| Code and comments | English |

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

| Document | Description |
|----------|-------------|
| [README.md](README.md) | Project overview and prerequisites |
| [SECURITY.md](SECURITY.md) | Messaging threat model and hook acceptance |
| [.env.example](.env.example) | Environment variable reference |
| [pyproject.toml](pyproject.toml) | Package metadata and quality gates |
| [hooks/messaging/](hooks/messaging/) | Versioned deny-hook scripts |
| [Cursor Python SDK](https://cursor.com/docs/sdk/python) | Upstream SDK documentation |
| [Cursor Hooks](https://cursor.com/docs/hooks) | Hook schema reference |
