# ADR-014: MVP tool profiles — coding and messaging

**Status:** Accepted

## Context

A full profile matrix (`minimal`, `coding`, `full`, `messaging`) is desirable long term. Phases 0–4 need a narrow, shippable scope — especially a security gate before any public bot.

The SDK does not disable native tools. Real restriction requires hooks, MCP configuration, and profile selection.

## Decision

**MVP implements only two profiles:**

| Profile | MCP | Hooks | Use |
|---------|-----|-------|-----|
| `coding` | project/user preserved | optional dev template | CLI, trusted local dev |
| `messaging` | empty + sandbox | deny hooks deployed to workspace | Gateway, bots |

MCP and sandbox policy on create and resume: [Architecture — MCP and sandbox by profile](../architecture.md#mcp-and-sandbox-by-profile-create-and-resume).

Additional profiles (`minimal`, `full`) are deferred until MCP search and related integrations are promoted.

**Gateway rule:** the gateway process **refuses to start** if `tool_profile != messaging`.

For threat model, hook layout, and acceptance probes, see [SECURITY.md](../../SECURITY.md) — do not duplicate that content here.

## Consequences

**Positive**

- Security gate (Phase 2b) deliverable in days, not blocked by extra profiles.
- Clear operator rule: bots always use `messaging`.
- `full` can be defined when concrete MCPs are chosen.

**Negative**

- Advanced users lack a `full` profile until post-MVP work lands.
- `coding` auto-approve is a dev convenience, not a security boundary for untrusted input.

## See also

- [SECURITY.md](../../SECURITY.md) — messaging threat model
- [AGENTS.md](../../AGENTS.md) — tool profile summary for contributors
