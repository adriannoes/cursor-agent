# Security Audit

**Source:** [hamzafer/cursor-commands](https://github.com/hamzafer/cursor-commands) (MIT) — adapted for cursor-agent.

Comprehensive security review focused on Python CLI, SDK integration, config/secrets, and gateway threat model.

**Related docs:** [gateway-security.md](../docs/gateway-security.md) · [ADR-001](../docs/decisions/ADR-001-messaging-security.md) · [secure-dev-python rule](../rules/secure-dev-python.mdc)

---

## When to run

- Before merge of gateway / messaging profile code (PRD-005+)
- After adding subprocess, shell, or MCP integration
- Before closing a PRD that touches auth, config, or allowlists
- On user request: `/security-audit`

---

## Step 1 — Dependency audit

```bash
uv pip list --outdated 2>/dev/null || uv tree
```

- Check `cursor-sdk` pin matches [ADR-017](../docs/decisions/ADR-017-sdk-version-pin.md)
- Review new dependencies in `pyproject.toml` for necessity and license
- No secrets in `uv.lock` or committed env files

---

## Step 2 — Secrets and config

Search for hardcoded credentials:

```bash
rg -i "(api_key|secret|password|token|private_key)\s*=\s*['\"]" src tests examples --glob '!*.example'
```

Verify:

- [ ] No real secrets in source, tests, or docs
- [ ] `.env` is gitignored; only `.env.example` is committed
- [ ] Config uses `CURSOR_AGENT__*` prefix ([.env.example](../.env.example))
- [ ] Logs do not print `CURSOR_API_KEY` or tokens ([ADR-018](../docs/decisions/ADR-018-observability-logs.md))
- [ ] `hmac.compare_digest()` for secret comparison (not `==`)

---

## Step 3 — Python code security

Apply [secure-dev-python.mdc](../rules/secure-dev-python.mdc). Focus areas for cursor-agent:

| Area | Check |
|------|-------|
| **Subprocess / shell** | No user input in shell commands; gateway uses allowlist |
| **File paths** | No unsanitized Telegram/chat input in paths |
| **Pickle / eval** | No `pickle`, `eval`, `exec` on untrusted data |
| **Dynamic imports** | No user-controlled `importlib` |
| **SQLite / sessions** | Parameterized queries; no string-concat SQL |

```bash
rg "subprocess|os\.system|eval\(|exec\(|pickle\.load|__import__" src/
```

---

## Step 4 — SDK and facade boundary

```bash
rg "cursor_sdk" src/
```

- [ ] `cursor_sdk` imports only in `sdk_facade.py` (once facade exists)
- [ ] No API keys passed through user-visible CLI args
- [ ] Integration tests skip without key — never embed key in test files

---

## Step 5 — MCP security

**Dev profile:** [secure-mcp-dev.mdc](../rules/secure-mcp-dev.mdc)

**Messaging / gateway profile:** [secure-mcp-messaging.mdc](../rules/secure-mcp-messaging.mdc) + [gateway-security.md](../docs/gateway-security.md)

- [ ] Gateway runs with `tool_profile: messaging` only
- [ ] `mcp_servers: {}` for messaging runs
- [ ] Hooks deny write tools and sensitive file reads (`.env`, `~/.ssh`)
- [ ] Telegram allowlist enforced ([ADR-001](../docs/decisions/ADR-001-messaging-security.md))

---

## Step 6 — Report

Deliver findings as:

```markdown
## Security audit — <date/branch>

### Critical (must fix before merge)
- ...

### Warning (fix soon)
- ...

### Info / accepted risk
- ...

### Checklist
- [ ] No hardcoded secrets
- [ ] Input validation on external input
- [ ] Subprocess/shell gated
- [ ] MCP posture correct for profile
- [ ] Gateway threat model scenarios tested (if applicable)
```

**Verdict:** Pass / Fail — Fail blocks merge for gateway-related PRs.
