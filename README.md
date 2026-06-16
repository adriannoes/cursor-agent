# cursor-agent

> **Agents:** start at **[AGENTS.md](AGENTS.md)**

Clean-room agent inspired by [Hermes Agent](https://github.com/NousResearch/hermes-agent) behavior and [OpenClaw](https://github.com/openclaw/openclaw) gateway patterns — reference docs and codebases may be studied for patterns, with **zero copied code** (not a fork). Powered by the [Cursor Python SDK](https://cursor.com/docs/sdk/python) and **Composer 2.5**.

Orchestration layer only — the SDK owns the agent loop, tools, and inference. Related projects by the same author (e.g. shellclaw) are **separate** — see [STRATEGY.md §1.4](docs/STRATEGY.md#14-relação-com-outros-projetos).

## Status

**Planning** — see [docs/STRATEGY.md](docs/STRATEGY.md) v1.2.

## Documentation

| Document | Description |
|----------|-------------|
| [AGENTS.md](AGENTS.md) | **Agent entry point** — read order, map, conventions |
| [docs/README.md](docs/README.md) | Documentation hub |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Strategy, architecture, Phases 0–4 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Architecture Decision Records (26 ADRs) |
| [docs/prd/README.md](docs/prd/README.md) | PRDs with tasks and subtasks |
| [docs/gateway-security.md](docs/gateway-security.md) | Messaging threat model |
| [docs/contracts/async-sdk-facade.md](docs/contracts/async-sdk-facade.md) | Facade technical contract |
| [docs/BACKLOG-PHASE5.md](docs/BACKLOG-PHASE5.md) | Post-MVP Hermes parity backlog |

Decisions in STRATEGY §2 are expanded in ADRs (including rejected options with pros/cons).

## Prerequisites

- Python 3.11+
- [Cursor API key](https://cursor.com/dashboard/api) → `CURSOR_API_KEY`
- `cursor-sdk-bridge` on PATH (installed with `cursor-sdk`)

## License

MIT — see [ADR-019](docs/decisions/ADR-019-packaging-license.md).
