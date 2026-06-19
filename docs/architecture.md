# Architecture

High-level design of **Cursor Agent** — an orchestration layer on the [Cursor SDK (Python)](https://cursor.com/docs/sdk/python) and **Composer 2.5**. For install and operations, see [setup.md](setup.md). For recorded design choices, see [Architecture decisions](decisions/README.md).

---

## Thesis

Projects like [Hermes Agent](https://github.com/NousResearch/hermes-agent) and [OpenClaw](https://github.com/openclaw/openclaw) implement the agentic loop, tools, providers, and gateway internally. **cursor-agent** delegates the loop, tools, and inference to the **Cursor SDK** and implements only:

| Layer | Responsibility |
|-------|----------------|
| **Orchestration** | Sessions, config, concurrency |
| **UX** | CLI, slash commands, gateway adapters |
| **Policy** | Hooks, tool profiles, allowlists |

Reference projects may inform **behavior patterns** — reimplement in `cursor_agent`; do not copy code.

---

## Layer diagram

```text
┌──────────────────────────────────────────────────────────────┐
│  Entry points: CLI (cursor-agent)  |  Gateway (long-run)     │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Config │ SessionStore │ Commands │ SessionAgentPool         │
│  PlatformAdapter (Telegram, …)                               │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
                    AsyncSdkFacade  ← sole cursor_sdk import
                             ▼
                    Cursor SDK (Composer 2.5 + tools)
                             ▼
                  Local cwd  |  Cloud VM
```

**CLI flow:** input → `CommandRouter` → `SessionStore.resolve(session_key)` → `SessionAgentPool.send` → `AsyncSdkFacade` → stream → display → `SessionStore.touch()`.

User data lives under `~/.cursor-agent/` (`config.yaml`, `sessions.db`, `MEMORY.md`, `USER.md`, `gateway.yaml`, logs).

### Session SQLite baseline (V1)

Local session metadata is stored in SQLite at `~/.cursor-agent/sessions.db` by default (override with `CURSOR_AGENT_SESSIONS_DB`). New databases and legacy pre-version files are upgraded idempotently to **schema version 1** on `SessionStore.initialize()` via `PRAGMA user_version`. Existing rows are preserved across upgrades; future schema changes add migrations in `sessions/store.py` rather than manual SQL edits.

---

## Dual persistence session model

Two stores cooperate; each owns a distinct concern:

```text
session_key  →  SessionStore (SQLite)  →  agent_id  →  SDK (history + checkpoint)
```

| Concept | Role |
|---------|------|
| `session_key` | Logical identity — e.g. `cli:{profile}:{workspace_hash}`, `telegram:{chat_id}:{workspace_hash}` ([ADR-004](decisions/ADR-004-session-key-workspace.md)) |
| Session id (UUID) | Primary key in SQLite; exposed to users via `/resume` |
| `agent_id` | Cursor identifier (`agent-*` / `bc-*`); internal, not primary UX |
| Conversation history | **Source of truth: SDK** via `agent_id` |
| Metadata (title, platform, workspace) | **Source of truth: SessionStore** |

**Rules:**

- `/resume` with no argument → last session for the current `session_key`
- `/resume <session-id>` → resolve UUID → `Agent.resume(agent_id)`; **runtime must match** current config ([ADR-003](decisions/ADR-003-cross-runtime-resume.md))
- `/new` → new `agent_id` + new SQLite row; previous sessions remain listable

---

## Concurrency — SessionAgentPool

```text
SessionAgentPool
  ├── get(session_key) → AsyncAgent (lazy resume via agent_id)
  ├── send(session_key, msg) → asyncio.Lock per session_key
  └── cron / background → dedicated agent_id per job (never shared with chat)
```

One inbound message at a time per `session_key`. Lock behavior differs by entry point:

| Entry point | Lock | Behavior |
|-------------|------|----------|
| **CLI** | blocking `await lock.acquire()` | Waits until the current run finishes or `/stop` |
| **Gateway** | `try_acquire` | If busy, raises `AgentBusyError` with a user-facing message |

Cron and background jobs always use a **dedicated** `agent_id` — never shared with chat sessions.

---

## SDK facade boundary

All `cursor_sdk` imports are confined to `src/cursor_agent/sdk_facade.py` and `src/cursor_agent/sdk_error_mapping.py`. CLI, gateway, and cron share one **async-first** facade:

- `AsyncSdkFacade` — real adapter over `AsyncClient.launch_bridge`
- `FakeSdkFacade` — unit tests without `CURSOR_API_KEY`
- Sync CLI paths use `asyncio.run()` per command or a single async REPL

Bridge lifecycle, retry, dispose, and MCP re-injection on resume live in the facade. See [ADR-002](decisions/ADR-002-async-sdk-facade.md).

---

## Tool profiles

The SDK does not disable native tools (`shell`, `edit`, …). Real control comes from **hooks**, **MCP configuration**, and **profile selection**.

| Profile | Use case | Posture |
|---------|----------|---------|
| `coding` | Local development, trusted operator | SDK auto-approve; optional dev hooks; project/user MCP preserved |
| `messaging` | Gateways, bots, untrusted input | Read-only workspace; deny hooks; empty MCP; sandbox network off |

MVP ships only `coding` and `messaging` ([ADR-014](decisions/ADR-014-tool-profiles-mvp.md)). Gateways **must** use `messaging` and refuse to start with `coding`.

### MCP and sandbox by profile (create and resume)

The SDK facade applies profile policy on **both** agent create and resume — not only on first launch.

| Profile | Agent create | Agent resume |
|---------|--------------|--------------|
| `coding` | Omits `mcp_servers` so Cursor **project** (`.cursor/mcp.json`) and **user** MCP settings apply | Omits `mcp_servers` so persisted SDK/project MCP settings apply |
| `messaging` | Passes `mcp_servers: {}` and enables sandbox (network off) | Re-injects `mcp_servers: {}` and sandbox for defense in depth |

Local `coding` runs also pass `setting_sources: ["project", "user"]` so workspace and user-level Cursor settings load. `messaging` still deploys deny hooks to the workspace before the first pool use.

Threat model, hook layout and acceptance probes: [SECURITY.md](../SECURITY.md).

---

## Configuration

Typed models loaded via **pydantic-settings** with explicit precedence ([ADR-007](decisions/ADR-007-config-loader.md)):

```text
CLI flags > env (CURSOR_AGENT__*) > ~/.cursor-agent/config.yaml > defaults
```

`${VAR}` expansion uses `os.path.expandvars` after merge (12-factor style).

---

## Memory

Files `~/.cursor-agent/USER.md` and `MEMORY.md` inject up to **8 KB** on the **first turn** after `/new` or `/resume` (when `metadata.memory_injected` is false). Injection runs in `SessionAgentPool.send()` — not CLI-only. Priority: `USER.md` up to 4 KB, then `MEMORY.md` for the remainder; truncate from the **end** when over quota. See [ADR-010](decisions/ADR-010-memory-v1.md).

---

## Public API scope

| Delivered | Out of scope (Phases 0–4) |
|-----------|---------------------------|
| CLI (`cursor-agent`) | Stable third-party Python library (`import cursor_agent` as a product) |
| Testable internal modules | Documented semver library API |

Diagrams and docs treat the **CLI** as the supported entry point until an explicit decision expands scope.

Curated ADRs (facade, sessions, config, memory, profiles, TDD): [docs/decisions/README.md](decisions/README.md).
