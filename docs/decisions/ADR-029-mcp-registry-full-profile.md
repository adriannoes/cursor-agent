# ADR-029: MCP registry and full tool profile

**Status:** Proposed

> Design lock for PRD-012 Wave 0. Promote to **Accepted** when `tool_profile: full` and `mcp_registry` are implemented in the codebase (PRD-012 closeout). Until then, `ToolProfile` remains `coding` | `messaging` only.

## Context

v1.0 ships two tool profiles ([ADR-014](ADR-014-tool-profiles-mvp.md)): `coding` (omit `mcp_servers` so project/user `.cursor/mcp.json` applies) and `messaging` (force empty MCP + sandbox + deny hooks). Trusted local operators need a documented, product-owned MCP allowlist (search / GitHub / browser) without weakening the gateway-safe messaging invariant.

The Cursor SDK is already the MCP host via `mcp_servers` on create/resume. This ADR locks the registry path, three-profile matrix, secrets, and gateway rules before implementation (PRD-012).

## Decision

**Thin in-repo `mcp_registry` → Cursor SDK `mcp_servers`.** No FastMCP, official `mcp` package, or mcporter as a runtime dependency.

| Profile | MCP create/resume | Sandbox | Where |
|---------|-------------------|---------|-------|
| `messaging` | always `{}` | on | Gateway / untrusted |
| `coding` | omit (`None`) — preserve project/user MCP | off | Trusted local |
| `full` | curated allowlist map (re-inject on resume) | off | **Local-only**; never on gateway |

**Key rules**

- `effective_tool_profile`: messaging wins; else session `coding`/`full` wins over config. Example: `config=full`, `session=coding` → `coding`.
- Allowlist: `mcp.full.servers: [github, brave-search, playwright]` (default = all curated ids).
- Secrets: env only (`GITHUB_PERSONAL_ACCESS_TOKEN`, `BRAVE_API_KEY`); no YAML plaintext; no interactive OAuth in v1.1.
- Missing required env: omit that server + warn once (never silent; never hard-fail REPL for optional MCP).
- Gateway refuses any `tool_profile != messaging` (including `full`) with an actionable `ConfigError`.
- Observability: log `mcp_servers_injected` with server **names only**, never tokens.
- This ADR **supersedes** ADR-014’s “MVP two profiles only / `full` deferred” clause. Messaging security: [SECURITY.md](../../SECURITY.md).

**Curated MVP servers (stdio):** `github` (Docker + PAT), `brave-search` (`npx @brave/brave-search-mcp-server` + `BRAVE_API_KEY`), `playwright` (`npx @playwright/mcp@latest`, no API key).

## Consequences

**Positive**

- Local operators get a clear `full` profile; messaging empty-MCP and gateway refuse stay intact; `coding` mcp.json workflows unchanged.

**Negative**

- `full` needs Docker and/or Node on the machine; partial maps when env is incomplete; no merge of curated + custom mcp.json under `full` in v1.1.

## See also

- [ADR-014](ADR-014-tool-profiles-mvp.md) — historical MVP two-profile decision (matrix superseded here)
- [Architecture — MCP and sandbox by profile](../architecture.md#mcp-and-sandbox-by-profile-create-and-resume)
- [SECURITY.md](../../SECURITY.md) — messaging threat model
- [ADR-007](ADR-007-config-loader.md) — config precedence
- [docs/setup.md](../setup.md) — enabling `full` (to be updated in the PRD-012 docs wave)
