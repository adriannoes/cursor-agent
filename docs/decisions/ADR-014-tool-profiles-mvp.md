# ADR-014: MVP tool profiles — coding and messaging

**Status:** Accepted

## Context

A full profile matrix (`minimal`, `coding`, `full`, `messaging`) is desirable long term. Phases 0–4 need a narrow, shippable scope — especially a security gate before any public bot.

The SDK does not disable native tools. Real restriction requires hooks, MCP configuration, and profile selection.

## Decision

**MVP implements only two profiles:**

| Profile | MCP | Hooks | Use |
|---------|-----|-------|-----|
| `coding` | project/user settings preserved (omit `mcp_servers` on create and resume) | optional dev template | CLI, trusted local dev |
| `messaging` | `{}` on create and resume; sandbox enabled | deny hooks deployed to workspace | Gateway, bots |

On **create**, `coding` omits `mcp_servers` so Cursor project (`.cursor/mcp.json`) and user MCP configuration apply; `messaging` passes an explicit empty map and enables sandbox (network off). On **resume**, the same rule holds: `coding` omits the field so persisted SDK/project MCP settings apply; `messaging` re-injects `mcp_servers: {}` and sandbox for defense in depth.

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
