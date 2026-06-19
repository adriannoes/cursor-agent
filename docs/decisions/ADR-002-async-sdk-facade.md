# ADR-002: Async SDK facade with Protocol and test fake

**Status:** Accepted

## Context

All access to `cursor-sdk` must flow through a single module (`sdk_facade.py`). CLI, gateway, and cron share the same async API. Most tests must run without `CURSOR_API_KEY`. SDK breaking changes should be absorbed at one boundary rather than scattered across the codebase.

## Decision

1. Define `SdkFacade` as a `typing.Protocol` describing the async contract (`create_agent`, `resume_agent`, `send`, `cancel`, …).
2. Implement `AsyncSdkFacade` as the real adapter over `AsyncClient.launch_bridge`.
3. Implement `FakeSdkFacade` for unit tests (pool, commands, session store).
4. One `AsyncClient` per process; dispose on shutdown.
5. **No** `cursor_sdk` imports outside `sdk_facade.py`.

Sync CLI entry points call `asyncio.run()` per command or run a single async REPL. Gateway and cron use the same facade — no parallel sync implementation.

## Consequences

**Positive**

- Stable contract isolated from SDK breaking changes.
- Fast, deterministic unit tests in CI without API keys.
- Bridge lifecycle, retry, dispose, and MCP re-injection on resume are centralized.

**Negative**

- `FakeSdkFacade` must stay aligned with the Protocol when the SDK evolves.
- Slight duplication of types if upstream SDK shapes change frequently.

## See also

- [architecture.md](../architecture.md) — layer diagram and facade boundary
- [Cursor Python SDK](https://cursor.com/docs/sdk/python)
