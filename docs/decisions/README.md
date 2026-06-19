# Architecture decisions

Curated **Architecture Decision Records (ADRs)** for external contributors. Each ADR captures context, the decision, and consequences in a concise MADR-style format.

Status values: **Accepted** means the decision is in effect in the current codebase.

| ADR | Summary |
|-----|---------|
| [ADR-002](ADR-002-async-sdk-facade.md) | Single async SDK facade with Protocol contract and fake for unit tests |
| [ADR-003](ADR-003-cross-runtime-resume.md) | `/resume` only when session runtime matches current config |
| [ADR-004](ADR-004-session-key-workspace.md) | Composite `session_key` includes workspace hash for project isolation |
| [ADR-007](ADR-007-config-loader.md) | Typed config via pydantic-settings with CLI > env > YAML precedence |
| [ADR-010](ADR-010-memory-v1.md) | Memory v1: 8 KB first-turn injection with `memory_injected` flag |
| [ADR-014](ADR-014-tool-profiles-mvp.md) | MVP ships `coding` and `messaging` profiles only |
| [ADR-022](ADR-022-tdd.md) | Mandatory test-first development for functional changes |

For system overview and diagrams, see [architecture.md](../architecture.md).

When proposing architectural changes, align with these records or add a new ADR in a follow-up PR.
