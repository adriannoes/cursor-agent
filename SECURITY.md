# Security — `messaging` tool profile

Threat model and capability matrix for gateway bots (Telegram and future channels). Use this profile for any untrusted or remote input.

---

## Posture

| Context | Posture |
|---------|---------|
| CLI `coding` | SDK auto-approve; trusted local operator only |
| Gateway `messaging` | Allowlist + deny hooks + sandbox (network off) + empty MCP |
| Cron `cloud` | Isolated VM; secrets via `env_vars` |

**Principle:** `messaging` is **read-only over the workspace** — Q&A about code, no mutation.

---

## What a messaging bot **can** do

| Capability | SDK tool | Allowed |
|------------|----------|---------|
| Read files in `cwd` | `read` | Yes |
| Search the repo | `grep`, `glob`, `ls`, `semSearch` | Yes |
| Read-only shell | `shell` (allowlist) | Yes — e.g. `git status`, `ls`, `cat` |
| Natural language replies | assistant | Yes |
| Subagent | `task` | No — denied via `preToolUse` |

---

## What a messaging bot **cannot** do

| Threat | Mitigation |
|--------|------------|
| Write/edit files | `preToolUse` denies `Write`, `StrReplace`, `Delete`, `Task` |
| Destructive shell (`rm -rf`, `curl \| bash`) | `beforeShellExecution` denylist |
| Arbitrary MCP | `mcp_servers: {}` + `beforeMCPExecution` deny |
| Read secrets | `beforeReadFile` denies `.env`, `~/.ssh`, `*.pem` |
| Network exfiltration | `sandbox_options.enabled: true` |
| Access without allowlist | Gateway auth — e.g. Telegram `allowed_users` (PRD-006) |

---

## Hook layout

**Source (versioned in repo):** `hooks/messaging/`

**User install target:** `~/.cursor-agent/hooks/messaging/`

**Workspace deploy (active project):**

- Manifest: `{workspace}/.cursor/hooks.json` — project-root-relative command paths
- Scripts: `{workspace}/.cursor/hooks/messaging/*.sh`

On startup with `tool_profile == "messaging"`, the CLI installs hooks to the user directory, then deploys into the workspace **before** the first pool/facade use. The `coding` profile does **not** auto-deploy messaging deny hooks.

Deployed manifest command paths are project-root-relative, e.g. `.cursor/hooks/messaging/shell-gate.sh`.

```text
hooks/messaging/                          # repo source of truth
├── hooks.json
├── pre-tool-deny-write.sh
├── shell-gate.sh
├── mcp-deny.sh
├── read-sensitive-deny.sh
└── sensitive-paths.sh                    # shared helper sourced by shell/read hooks

~/.cursor-agent/hooks/messaging/          # staged install copy

{workspace}/.cursor/
├── hooks.json                            # active project manifest
└── hooks/messaging/
    ├── pre-tool-deny-write.sh
    ├── shell-gate.sh
    ├── mcp-deny.sh
    ├── read-sensitive-deny.sh
    └── sensitive-paths.sh
```

### MCP and sandbox on create and resume

Profile policy applies on **both** agent create and resume:

| Profile | Create | Resume |
|---------|--------|--------|
| `coding` | Omits `mcp_servers` — Cursor project (`.cursor/mcp.json`) and user MCP settings apply | Omits `mcp_servers` — persisted SDK/project MCP settings apply |
| `messaging` | `mcp_servers: {}` + `sandbox_options.enabled: true` (network off) | Re-injects `mcp_servers: {}` + sandbox (defense in depth alongside hooks) |

`coding` is not gateway-safe even when MCP is preserved; `messaging` layers empty MCP, sandbox, and deny hooks together.

---

## Known limitations

1. **Hooks are file-based** — not programmatic per run ([Cursor SDK](https://cursor.com/docs/sdk/python)).
2. **Sandbox does not block file edits** — relies on `preToolUse` deny hooks.
3. **Reading source code** may expose business logic — accepted for Q&A; sensitive paths are denied.
4. **Windows:** hooks may be flaky — test on Linux/macOS VPS targets.
5. **SDK classifier auto-review** is a convenience, not a security boundary.

---

## Acceptance probes

Minimum gate uses **hook-level probes** with representative JSON stdin (exit code `2` = deny, `0` = allow). Full live SDK prompt acceptance is optional when `CURSOR_API_KEY` is available.

| # | Scenario | Expected | Evidence |
|---|----------|----------|----------|
| 1 | `rm -rf /` via `beforeShellExecution` | Hook blocks (rc 2) | `shell-gate.sh` deny |
| 2 | Edit `README.md` via `preToolUse` | Deny (rc 2) | `pre-tool-deny-write.sh` |
| 3 | `git status` via `beforeShellExecution` | Allow (rc 0) | `shell-gate.sh` allow |
| 4 | Read `.env` via `beforeReadFile` | Deny (rc 2); secret not echoed | `read-sensitive-deny.sh` |
| 5 | Gateway with `tool_profile: coding` | Process refuses to start | PRD-006 enforcement |

**Supplemental probes (denied):** MCP execution; standalone `curl` / `wget` / `nc`; pipe-to-shell; `Task` subagent; shell chaining (`git status && curl …`); command substitution (`$(curl …)`, backticks); unsafe `find` (`-delete`, `-exec`); sensitive shell reads (`cat .env`, `head -n 1 .env`, `cat ~/.ssh/id_rsa`, `cat deploy.pem`); broad or sensitive `grep` / `rg` probes; git history/diff reads (`git show`, `git log`, `git diff`); pre-tool empty or lowercase mutation tool names (`write`).

**Automated unit suite:**

```bash
uv run pytest tests/unit/test_cli_profile.py tests/unit/test_messaging_profile.py \
  tests/unit/test_messaging_hooks_deploy.py tests/unit/test_hook_workspace_deploy.py \
  tests/unit/test_cli_bootstrap.py tests/unit/test_pool.py -v
```

---

## References

- [Cursor Hooks](https://cursor.com/docs/hooks)
- [Cursor Python SDK](https://cursor.com/docs/sdk/python)
- [AGENTS.md](AGENTS.md) — agent entry point and verification commands
