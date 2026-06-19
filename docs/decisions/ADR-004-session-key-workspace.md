# ADR-004: Composite session_key with workspace hash

**Status:** Accepted

## Context

A key like `telegram:{chat_id}` ignored workspace. Changing `cwd` in config could resume a conversation from a different project. The SDK persists agent state per workspace — session identity must match that scope.

## Decision

Use a composite key format:

```text
cli:{profile}:{workspace_hash}
telegram:{chat_id}:{workspace_hash}
```

- `workspace_hash = sha256(abs(cwd))[:8]`
- `profile` defaults to `default` for CLI
- `/resume` with no id → last session for the **current** `session_key` (includes hash)

Changing `cwd` creates a new session namespace; previous sessions remain in SQLite but are not selected by default resume.

## Consequences

**Positive**

- Project isolation in CLI and gateway — no cross-contamination when `cwd` changes.
- `sessions list` can filter by workspace without ambiguity.
- Aligns with SDK workspace-scoped persistence.

**Negative**

- Users must understand that changing `cwd` starts a new session namespace.
- Keys are longer and less human-readable than bare chat IDs.

## See also

- [architecture.md](../architecture.md) — session model overview
- [ADR-003](ADR-003-cross-runtime-resume.md) — runtime matching on resume
