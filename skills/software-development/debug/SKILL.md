---
name: debug
description: Reproduce a bug, isolate the cause, apply a minimal fix, and verify with a focused check or test.
---

# Debug

## When to use

Use when something is wrong or unexpected: a failing test, runtime error, incorrect output, hang, or regression the operator can describe (even partially).

## Procedure

1. **Reproduce:** capture the exact symptom, command, inputs, and environment. Prefer a minimal failing case over a full app walkthrough.
2. **Isolate:** bisect with logs, assertions, or smaller inputs until one cause remains. State the failing hypothesis and what would disprove it.
3. **Fix:** change the smallest surface that addresses the root cause — not symptoms alone. Prefer a regression test when the stack supports it.
4. **Verify:** re-run the reproduction and related tests; confirm the original failure is gone and nearby behavior still works.
5. Report: root cause in one short paragraph, what changed, and how you verified.

## Tools to prefer

- Tool profile: any local (`coding` or `full`).
- SDK shell/tests and workspace reads; debugger or logging only as needed.
- Avoid drive-by refactors and unrelated dependency upgrades while debugging.

## Pitfalls

- Fixing without a reliable reproduction.
- Patching symptoms (extra null checks) while leaving the real bug.
- Changing many files “just in case”.
- Declaring success without re-running the failing case.

## Verification

- Reproduction steps are written and were re-run after the fix.
- Root cause is stated (not only “it works now”).
- Focused tests or checks pass; no unexplained new failures.
- Diff stays scoped to the bug.
