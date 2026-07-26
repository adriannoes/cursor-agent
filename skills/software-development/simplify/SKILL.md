---
name: simplify
description: Cleanup pass that reduces complexity and duplication without changing observable behavior.
---

# Simplify

## When to use

Use when the operator wants a focused cleanup: tangled control flow, duplicated logic, unclear names, or leftover spike/debug code — and behavior must stay the same.

## Procedure

1. Lock the **behavior contract**: which tests, CLI outputs, or APIs must remain unchanged. Run the relevant suite first as a baseline.
2. Identify hotspots (long functions, deep nesting, copy-paste, dead code) in the agreed scope only.
3. Apply small, behavior-preserving edits: extract helpers, flatten conditionals, delete dead paths, tighten names. One concern per change set when practical.
4. Re-run the same verification after each meaningful chunk. Prefer existing tests; add characterization tests only when coverage is too thin to refactor safely.
5. Stop when complexity is down or the operator’s scope is done — do not expand into features or drive-by redesigns.

## Tools to prefer

- Tool profile: any local (`coding` or `full`).
- Project tests and linters as the safety net; targeted reads/grep for call sites.
- Avoid new dependencies “for cleanliness” unless the operator asks.

## Pitfalls

- Mixing refactors with behavior changes or new features.
- Renaming widely without updating all call sites/tests.
- “Simplifying” by inventing abstractions with a single use.
- Skipping the baseline/post test run.

## Verification

- Agreed tests (or manual checks) pass before and after.
- Diff is explainable as complexity reduction only.
- No intentional API/CLI/output changes unless the operator approved them separately.
- Scope stayed within the files/areas named up front.
