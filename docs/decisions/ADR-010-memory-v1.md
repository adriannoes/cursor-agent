# ADR-010: Memory v1 — injection and memory_injected flag

**Status:** Accepted

## Context

Memory v1 reads `~/.cursor-agent/USER.md` and `MEMORY.md`. An 8 KB cap applies on the first turn of a session. Truncation order, injection point, and `/resume` behavior needed explicit rules so CLI, gateway, and tests agree.

## Decision

1. **Injection point:** `SessionAgentPool.send()` immediately before SDK send — not CLI-only or adapter-specific.
2. **Priority:** `USER.md` up to 4 KB, then `MEMORY.md` for the remainder of the 8 KB total budget.
3. **Truncation:** from the **end** of a section when it exceeds its quota.
4. **Section markers:** `## User memory` and `## Memory` (locked in tests).
5. **When:** first turn after `/new` or `/resume` when `metadata.memory_injected != true`.
6. After injection, set `metadata.memory_injected = true` in SQLite.
7. `/new` resets the flag; `/compress` does **not** re-inject (summary seeds the new agent).

## Consequences

**Positive**

- Deterministic, testable behavior across entry points.
- User preferences (`USER.md`) preserved over factual memory (`MEMORY.md`).
- Token cost controlled — no re-injection on every resume.

**Negative**

- Edits to memory files mid-session do not appear until `/new` or a fresh session row.
- Future semantic search or MCP-backed memory is out of scope for v1.

## See also

- [README.md](../../README.md) — Memory section for operator notes
- [architecture.md](../architecture.md) — memory overview
