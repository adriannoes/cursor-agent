---
name: tdd
description: Red–green–refactor for a behavior change — failing test first, minimal code, then cleanup with tests green.
---

# TDD

## When to use

Use for new behavior, bug fixes, or refactors that change contracts — whenever a failing automated check can define “done”. Prefer this over coding first.

## Procedure

1. **Red:** write one minimal failing test for a single behavior. Name it after the intended outcome.
2. **Watch it fail:** run only that test (or a tight subset). Confirm it fails for the right reason (missing feature), not a typo or import error.
3. **Green:** write the smallest production change that makes the test pass. Do not add extra features.
4. **Refactor:** clean names, duplication, and structure while keeping tests green. No new behavior in this step.
5. Repeat for the next behavior. For **Python**, use **pytest** first (`tests/` layout, typed tests). Match the project’s documented test command when present.

## Tools to prefer

- Tool profile: any local (`coding` or `full`).
- Project test runner (pytest for Python); linters after green when the repo expects them.
- Fakes/mocks only at I/O boundaries — prefer real units under test.

## Pitfalls

- Writing production code before a failing test.
- A test that passes on the first run (it never proved anything).
- Giant tests covering many behaviors at once.
- Refactoring and adding features in the same step.

## Verification

- Each new behavior had a failing test observed before implementation.
- Targeted tests pass; broader suite or documented unit gate is green when practical.
- Diff separates “make it pass” from optional cleanup.
- Bug fixes include a regression test that would have caught the issue.
