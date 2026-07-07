# ADR-028: Config persistence for setup wizard

**Status:** Accepted

## Context

PRD-013 ships `cursor-agent setup` — an opt-in CLI that writes local configuration (API key and non-secret settings) so operators reach a working REPL without hand-editing multiple artifacts. The project already **reads** config via [ADR-007](ADR-007-config-loader.md) and CWD dotenv loading; this ADR locks the **write** contract for secrets, atomicity, permissions, and inspection semantics.

Constraints:

- Secrets policy: `CURSOR_API_KEY` belongs in env or gitignored `.env`, never in YAML, logs, or `setup show` output.
- [ADR-027](ADR-027-onboarding-first-run.md): first-run banner and `first_run_complete` marker stay unchanged; setup does not gate REPL startup.
- Setup writes only **lower-precedence** artifacts; exported shell env still wins.

## Decision

### Secrets in env only

| Field | Write target | Never |
|-------|--------------|-------|
| `CURSOR_API_KEY` | CWD `.env` (or `--env-file`) | `config.yaml`, logs, `setup show` |
| `CURSOR_AGENT_SESSIONS_DB` | CWD `.env` | YAML |
| Non-secret settings (`model`, `memory_root`, `tool_profile`, `runtime.local.cwd`) | `config.yaml` (or `--config-path`) | `.env` unless allowlisted |

### Atomic writes

YAML and `.env` persistence use temp file in the **same parent directory** + `os.replace` (same discipline as cron store and first-run marker). Direct truncate-in-place is forbidden.

### Permissions

| Path | Mode | Notes |
|------|------|-------|
| `~/.cursor-agent/` | `0o700` | Create when missing |
| CWD `.env` | `0o600` | Best-effort `chmod` after write |

### Idempotency and `--force` backup

- If persisted state already matches requested values → no mutation, explicit no-op, exit `0`.
- Env key present with a **different** value and no `--force` → refuse; suggest `cursor-agent setup show`.
- With `--force` → create one timestamped `{env_file}.bak.{YYYYMMDD-HHMMSS}` before merge-write.

### Setup does not export to the shell

Setup writes files only. Precedence remains:

```text
Shell export  >  CWD .env  >  config.yaml  >  defaults
```

Operators must `source .env` or open a new terminal for in-session exports.

### Source labels (`setup show`)

Per-field provenance uses exactly: `shell` | `env` | `yaml` | `default`.

### No messaging hooks; no first-run marker

- Setup does **not** deploy messaging deny hooks or write workspace hook manifests.
- Setup does **not** create, update, or delete `first_run_complete`.

### Dotenv before `setup show` / `setup check`

Subcommand entry **must** call `load_cwd_dotenv()` before loading config or rendering effective settings. `setup apply` re-loads after successful write.

### Duplicate `.env` keys

- **Write:** update the **first** matching `KEY=` line; do not whole-file dedupe.
- **Read:** last-wins (typical dotenv parsers).

## Consequences

**Positive**

- Secret handling stays aligned with project secrets policy; persistence is crash-safe and grep-friendly.
- Operators can attribute each field to shell / env / yaml / default.

**Negative**

- Setup cannot fix the current shell session; duplicate `.env` keys are operator-owned until a future dedupe feature.

## See also

- [docs/setup.md](../setup.md) — Interactive setup section
- [ADR-007](ADR-007-config-loader.md) — config precedence
- [ADR-022](ADR-022-tdd.md) — test-first changes to setup behavior
- [ADR-027](ADR-027-onboarding-first-run.md) — first-run UX (setup remains opt-in)
- `src/cursor_agent/config/writer.py` — atomic YAML + env merge
- `src/cursor_agent/cli/startup.py` — `load_cwd_dotenv()`
