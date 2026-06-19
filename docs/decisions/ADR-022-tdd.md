# ADR-022: Test-driven development

**Status:** Accepted

## Context

The project targets headless CI, grep-friendly modules, and agent-driven development loops. Implementing features before tests leads to inadequate fakes, missed edge cases, and regressions that surface late — especially around SDK timing and session semantics.

## Decision

**Test-first is mandatory for functional changes:**

1. Write a **failing** pytest test that expresses the requirement (mirror `tests/` layout over `src/`).
2. Implement the minimum code to make the test pass.
3. Refactor while keeping the suite green.

**Additional rules:**

- Every new public function gets a test; every bug fix gets a regression test.
- Unit tests use `FakeSdkFacade` and fakes — no `CURSOR_API_KEY` required.
- Integration tests (`@pytest.mark.integration`) skip when `CURSOR_API_KEY` is unset.
- Inject dependencies through constructors, parameters, or context — not hidden globals.

**Verification gate** (same as CI):

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest -m "not integration" -v
```

## Consequences

**Positive**

- Regressions caught early; CI stays deterministic without API keys for unit scope.
- Fakes stay aligned with the SDK facade contract.
- Contributors and AI agents share one documented loop (Red → Green → Refactor).

**Negative**

- Slightly higher upfront cost per feature.
- Fakes must be updated when facade behavior changes.

## See also

- [AGENTS.md](../../AGENTS.md) — how to work and verify locally
- [CONTRIBUTING.md](../../CONTRIBUTING.md) — PR verification gate
