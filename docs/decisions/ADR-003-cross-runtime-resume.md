# ADR-003: Disallow cross-runtime resume

**Status:** Accepted

## Context

The Cursor SDK detects runtime from the `agent_id` prefix (`bc-` = cloud, otherwise local). Local persistence is workspace-scoped. The SQLite `sessions` table stores a `runtime` column, but resume rules were undefined — allowing cross-runtime resume produces obscure SDK errors.

## Decision

`/resume` succeeds only when `session.runtime == config.runtime.mode` at resume time.

- **Mismatch** → clear error message; suggest `/new`.
- Legacy cloud rows never share a `session_key` with chat, but cloud execution is not supported because the current facade constructs local SDK options.
- PRD-019 makes `v1.3.2` reject new cloud configuration before SDK or persistence side effects; a future ADR must define real cloud repositories and SDK options.
- `agent_id` is immutable for a session row; changing runtime requires `/new`.

## Consequences

**Positive**

- Predictable behavior across CLI, gateway, and cron.
- Aligns with SDK runtime auto-detection on resume.
- Uses existing schema without migration.

**Negative**

- Existing cloud-tagged rows cannot execute or resume until a future cloud-specific design is implemented.

## See also

- [ADR-004](ADR-004-session-key-workspace.md) — session key format
- [architecture.md](../architecture.md) — dual persistence model
