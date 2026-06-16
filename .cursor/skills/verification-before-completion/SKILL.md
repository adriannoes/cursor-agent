---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing in cursor-agent — run verification commands and confirm output before any success claims.
---

# Verification Before Completion

**Source:** [obra/superpowers](https://github.com/obra/superpowers) (MIT) — adapted for cursor-agent.

## cursor-agent verification commands

| Claim | Command |
|-------|---------|
| Unit tests pass | `pytest -m "not integration" -v` |
| Integration smoke (when PRD requires) | `pytest -m integration -v` with `CURSOR_API_KEY` |
| Linter clean | `ruff check src tests` |
| PRD / branch done | `/code-review` per [code-review.md](../../commands/code-review.md) |
| Sub-task done | Mark `[x]` in `engineering/tasks/tasks-PRD-*.md` only after commands above |

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | `pytest -m "not integration" -v`: 0 failures | Previous run, "should pass" |
| Linter clean | `ruff check src tests`: 0 errors | Partial check, extrapolation |
| Bug fixed | Failing test now passes (red-green verified) | Code changed, assumed fixed |
| PRD complete | DoD §10 checklist + `/code-review` Aprovado | Tests passing only |
| FR implemented | Line-by-line FR → file + test mapping | Tests passing |

## Red Flags — STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!")
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Marking task `[x]` before running pytest
- **ANY wording implying success without having run verification**

## Key Patterns

**Tests:**

```
✅ [Run pytest -m "not integration" -v] [See: N/N pass] "All unit tests pass"
❌ "Should pass now" / "Looks correct"
```

**Lint:**

```
✅ [Run ruff check src tests] [See: All checks passed] "Linter clean"
❌ "Tests pass so lint is probably fine"
```

**PRD completion:**

```
✅ Re-read PRD §10 → Run /code-review → Report veredito with evidence
❌ "Tests pass, PRD complete"
```

## When To Apply

**ALWAYS before:**

- ANY variation of success/completion claims
- Committing, PR creation, task completion
- Moving to next sub-task (checkpoints in [development.md](../../commands/development.md))
- Closing a PRD

**No shortcuts for verification.** Run the command. Read the output. THEN claim the result.
