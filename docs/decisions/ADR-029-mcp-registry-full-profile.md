# ADR-029: MCP registry and full tool profile

**Status:** Accepted

> Shipped with PRD-012 closeout. Runtime `ToolProfile` is `coding` | `messaging` | `full`.
>
> **Amendment (2026-07-09):** Curated `github` **default** = official remote HTTP (`https://api.githubcopilot.com/mcp/`) with `Authorization: Bearer <PAT>` from `GITHUB_PERSONAL_ACCESS_TOKEN`. Docker **stdio** is an **operator opt-in** (`mcp.full.github_transport: stdio` / `CURSOR_AGENT__MCP__FULL__GITHUB_TRANSPORT`), not a silent fallback. Unset → always `http`. Messaging / gateway rules unchanged ([SECURITY.md](../../SECURITY.md)). No interactive OAuth; no FastMCP/`mcp` runtime dep. Detailed spike evidence lives in the internal ADR Appendix B.

> **Amendment (2026-07-10):** Warm `resume_agent` short-circuits for every profile when the agent is already in the facade with the same `model:tool_profile` (SDK warm resume invalidates the live handle). Messaging/full MCP re-inject applies on **create** and **cold resume** only — not on every warm get/send. Mid-process `full` env/allowlist changes take effect on the next cold resume.

## Context

v1.0 ships two tool profiles ([ADR-014](ADR-014-tool-profiles-mvp.md)): `coding` (omit `mcp_servers` so project/user `.cursor/mcp.json` applies) and `messaging` (force empty MCP + sandbox + deny hooks). Trusted local operators need a documented, product-owned MCP allowlist (search / GitHub / browser) without weakening the gateway-safe messaging invariant.

The Cursor SDK is already the MCP host via `mcp_servers` on create and cold resume. This ADR locks the registry path, three-profile matrix, secrets, and gateway rules before implementation (PRD-012).

## Decision

**Thin in-repo `mcp_registry` → Cursor SDK `mcp_servers`.** No FastMCP, official `mcp` package, or mcporter as a runtime dependency.

| Profile | MCP create | MCP cold resume | Sandbox | Where |
|---------|------------|-----------------|---------|-------|
| `messaging` | always `{}` | re-inject `{}` | on | Gateway / untrusted |
| `coding` | omit (`None`) — preserve project/user MCP | omit | off | Trusted local |
| `full` | curated allowlist map | re-inject curated map (re-read environ) | off | **Local-only**; never on gateway |

Warm resume (agent already in facade, same `model:tool_profile`) short-circuits without SDK `agents.resume` for all profiles; create-time MCP remains until cold resume.

**Key rules**

- `effective_tool_profile`: messaging wins; else session `coding`/`full` wins over config. Example: `config=full`, `session=coding` → `coding`.
- Allowlist: `mcp.full.servers: [github, brave-search, playwright]` (default = all curated ids).
- GitHub transport: `mcp.full.github_transport: http|stdio` (default `http`; env `CURSOR_AGENT__MCP__FULL__GITHUB_TRANSPORT`). Invalid → `ConfigError` with received + allowed set.
- Secrets: env only (`GITHUB_PERSONAL_ACCESS_TOKEN`, `BRAVE_API_KEY`); no YAML plaintext; no interactive OAuth in v1.1.
- Missing required env: omit that server + warn once (never silent; never hard-fail REPL for optional MCP).
- Gateway refuses any `tool_profile != messaging` (including `full`) with an actionable `ConfigError`.
- Observability: log `mcp_servers_injected` with server **names only**, never tokens.
- This ADR **supersedes** ADR-014’s “MVP two profiles only / `full` deferred” clause. Messaging security: [SECURITY.md](../../SECURITY.md).

**Curated MVP servers:** `github` (default remote HTTP + PAT Bearer; Docker stdio opt-in), `brave-search` (`npx @brave/brave-search-mcp-server` + `BRAVE_API_KEY`), `playwright` (`npx @playwright/mcp@0.0.78`, pinned; no API key).

## Consequences

**Positive**

- Local operators get a clear `full` profile; messaging empty-MCP and gateway refuse stay intact; `coding` mcp.json workflows unchanged.
- Default `github` path works with a PAT and no Docker daemon.

**Negative**

- `full` still needs Node/`npx` for Brave and Playwright; Docker only if the operator chooses github `stdio`. Partial maps when env is incomplete; no merge of curated + custom mcp.json under `full` in v1.1.
- Warm `full` sessions do not re-read process environ/allowlist until cold resume (intentional tradeoff vs SDK warm-resume invalidation).

## See also

- [ADR-014](ADR-014-tool-profiles-mvp.md) — historical MVP two-profile decision (matrix superseded here)
- [Architecture — MCP and sandbox by profile](../architecture.md#mcp-and-sandbox-by-profile-create-and-resume)
- [SECURITY.md](../../SECURITY.md) — messaging threat model (unchanged by Wave 5 github HTTP amendment)
- [ADR-007](ADR-007-config-loader.md) — config precedence
- [docs/setup.md](../setup.md) — enabling `full`
