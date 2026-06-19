# ADR-003: Disallow cross-runtime resume

**Status:** Accepted

## Context

The Cursor SDK detects runtime from the `agent_id` prefix (`bc-` = cloud, otherwise local). Local persistence is workspace-scoped. The SQLite `sessions` table stores a `runtime` column, but resume rules were undefined — allowing cross-runtime resume produces obscure SDK errors.

## Decision

`/resume` succeeds only when `session.runtime == config.runtime.mode` at resume time.

- **Mismatch** → clear error message; suggest `/new`.
- Cloud cron jobs record `runtime: cloud` and **never** share a `session_key` with chat.
- `agent_id` is immutable for a session row; changing runtime requires `/new`.

## Consequences

**Positive**

- Predictable behavior across CLI, gateway, and cron.
- Aligns with SDK runtime auto-detection on resume.
- Uses existing schema without migration.

**Negative**

- A user cannot continue a cloud session on a local CLI without starting a new local session.

## See also

- [ADR-004](ADR-004-session-key-workspace.md) — session key format
- [architecture.md](../architecture.md) — dual persistence model
