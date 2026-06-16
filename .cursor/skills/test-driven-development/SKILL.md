---
name: test-driven-development
description: Use when implementing any feature or bugfix in cursor-agent, before writing implementation code. Enforces ADR-022 Red-Green-Refactor with pytest.
---

# Test-Driven Development (TDD)

**Source:** [obra/superpowers](https://github.com/obra/superpowers) (MIT) — adapted for cursor-agent.

## cursor-agent context

- **ADR:** [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) — TDD + retro between PRDs.
- **Unit tests (no API key):** `pytest -m "not integration" -v`
- **Integration tests:** `pytest -m integration -v` — requires `CURSOR_API_KEY`; skip when absent ([ADR-005](../../docs/decisions/ADR-005-testing-strategy.md)).
- **SDK boundary:** unit tests use `FakeSdkFacade` or in-memory fakes — never a real bridge ([async-sdk-facade contract](../../docs/contracts/async-sdk-facade.md)).
- **Lint gate:** `ruff check src tests` after green tests.

## Overview

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** If you didn't watch the test fail, you don't know if it tests the right thing.

## When to Use

**Always:** New features, bug fixes, refactoring, behavior changes mapped to PRD functional requirements.

**Exceptions (ask your human partner):** Throwaway prototypes, generated lockfiles, docs-only changes.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write code before the test? Delete it. Start over. No exceptions.

## Red-Green-Refactor

### RED — Write Failing Test

- Write one minimal test showing what should happen
- One behavior, clear name, real code (no mocks unless unavoidable)
- Place under `tests/` mirroring source layout; integration tests in `tests/integration/`

### Verify RED — Watch It Fail

**MANDATORY.** Run the test. Confirm:

- Test fails (not errors)
- Failure message is expected
- Fails because feature missing (not typos)

### GREEN — Minimal Code

- Write simplest code to pass the test
- Don't add features, refactor other code, or "improve" beyond the test

### Verify GREEN — Watch It Pass

**MANDATORY.** Run the test. Confirm:

- Test passes
- Other tests still pass (`pytest -m "not integration" -v`)
- Output pristine (no errors, warnings)

### REFACTOR — Clean Up

After green only: remove duplication, improve names, extract helpers. Keep tests green. Don't add behavior.

## Good Tests

| Quality | Good | Bad |
|---------|------|-----|
| **Minimal** | One thing. "and" in name? Split it. | `test_validates_email_and_domain_and_whitespace` |
| **Clear** | Name describes behavior | `test_1` |
| **Shows intent** | Demonstrates desired API | Obscures what code should do |

## Red Flags — STOP and Start Over

- Code before test
- Test after implementation
- Test passes immediately
- Can't explain why test failed
- Rationalizing "just this once"
- "Keep as reference" or "adapt existing code"
- Using real `cursor_sdk` bridge in unit tests

**All of these mean: Delete code. Start over with TDD.**

## Verification Checklist

Before marking a sub-task complete:

- [ ] Every new public function has a test
- [ ] Watched each test fail before implementing
- [ ] Each test failed for expected reason (feature missing, not typo)
- [ ] Wrote minimal code to pass each test
- [ ] `pytest -m "not integration" -v` passes
- [ ] `ruff check src tests` passes
- [ ] Edge cases and errors covered

## Bug Fixes

Bug found? Write failing test reproducing it. Follow TDD cycle. Test proves fix and prevents regression. Never fix bugs without a test.

## Related

- [testing-anti-patterns.md](./testing-anti-patterns.md) — load when adding mocks or tempted by test-only production hooks
