# ADR-014: MVP tool profiles — coding and messaging

**Status:** Accepted

## Context

A full profile matrix (`minimal`, `coding`, `full`, `messaging`) is desirable long term. Phases 0–4 need a narrow, shippable scope — especially a security gate before any public bot.

The SDK does not disable native tools. Real restriction requires hooks, MCP configuration, and profile selection.

## Decision

> **See [ADR-029](ADR-029-mcp-registry-full-profile.md)** for the live three-profile MCP matrix (`coding` / `messaging` / `full`). This ADR remains the historical MVP decision that shipped two profiles first.

**MVP implements only two profiles:**

| Profile | MCP | Hooks | Use |
|---------|-----|-------|-----|
| `coding` | project/user preserved | optional dev template | CLI, trusted local dev |
| `messaging` | empty + sandbox | deny hooks deployed to workspace | Gateway, bots |

MCP and sandbox policy on create and resume: [Architecture — MCP and sandbox by profile](../architecture.md#mcp-and-sandbox-by-profile-create-and-resume).

`full` is now defined in [ADR-029](ADR-029-mcp-registry-full-profile.md). `minimal` remains deferred.

**Gateway rule:** the gateway process **refuses to start** if `tool_profile != messaging`.

For threat model, hook layout, and acceptance probes, see [SECURITY.md](../../SECURITY.md) — do not duplicate that content here.

## Consequences

**Positive**

- Security gate (Phase 2b) deliverable in days, not blocked by extra profiles.
- Clear operator rule: bots always use `messaging`.

**Negative**

- `coding` auto-approve is a dev convenience, not a security boundary for untrusted input.

**Supersession note:** The deferred-`full` consequence of this MVP ADR is superseded by [ADR-029](ADR-029-mcp-registry-full-profile.md) (**Accepted**). Messaging empty-MCP and gateway refuse remain in effect.

## See also

- [ADR-029](ADR-029-mcp-registry-full-profile.md) — three-profile MCP matrix (`full`)
- [SECURITY.md](../../SECURITY.md) — messaging threat model
- [AGENTS.md](../../AGENTS.md) — tool profile summary for contributors
