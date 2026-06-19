# ADR-027: CLI onboarding first-run UX

**Status:** Accepted

## Context

PRD-011 adds a welcome banner and one-time getting-started hints for interactive CLI launches. Implementation modules cite suppression policy, marker semantics, and width limits — those rules need a public ADR so contributors are not sent to missing internal docs.

## Decision

### §5 First-run marker

- Marker file: `{config_home}/first_run_complete`, where `config_home` is the parent of the session DB path (`~/.cursor-agent` by default).
- Written only after the welcome banner prints **and** `repl_runtime()` bootstrap succeeds (REPL context manager entered).
- Not written when the banner is suppressed (`--no-banner`, non-TTY, CI mode) or when persistence degrades (symlinked config home, unwritable directory).
- Atomic write via temp file in the same parent directory and `os.replace`; resolved marker path must stay under the canonical config home.

### §6 Banner suppression

Suppress welcome output when **any** of:

- `--no-banner` CLI flag is set
- stdout is not a TTY
- `CI` environment variable is set to a truthy value (for example `CI=1`, `CI=true`)

Values `0`, `false`, `no`, `off`, empty, and unset do **not** activate CI suppression.

### §7 Banner width

- Product copy uses a fixed 58-column inner width; every rendered line must stay ≤60 characters (PRD-011).
- Allowed non-ASCII glyphs in banner output: `✓` and `—` only until a post-1.0 ASCII fallback is promoted.

## Consequences

**Positive**

- Users who see the full first-run block but hit a late bootstrap failure (for example `AuthError` inside `repl_runtime`) will see it again on the next launch.
- Suppression and marker rules are grep-friendly and linked from source.
- Width and Unicode constraints are documented for future locale fallback work.

**Negative**

- Marker persistence is slightly delayed relative to banner print (acceptable tradeoff for correct first-run semantics).

## See also

- [README.md](../../README.md) — First run section
- `src/cursor_agent/product_copy.py` — shared banner and hint copy
- [ADR-022](ADR-022-tdd.md) — test-first changes to onboarding behavior
