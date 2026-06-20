## Summary

<!-- What changed and why? Link issues: Fixes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor / docs / tooling
- [ ] Test update

## Checklist

- [ ] `uv run ruff check src tests` passes
- [ ] `uv run ruff format --check src tests` passes
- [ ] `uv run mypy --strict src` passes
- [ ] `uv run pytest -m "not integration and not package_smoke" -v` passes
- [ ] New or updated tests for behavior changes
- [ ] Docs updated if user-facing behavior changed (README, `docs/`, or docstrings)

### Release / launch PRs (add when tagging or shipping V1)

- [ ] `uv run pytest -m package_smoke -v` passes
- [ ] `uv run pytest tests/test_package_metadata.py -v` passes
- [ ] Public setup docs and `.env.example` match supported env names
- [ ] No secrets in diffs or logs
- [ ] Optional: `uv run pytest -m integration -v` with `CURSOR_API_KEY`

## Notes

<!-- Tool profile tested (coding / messaging), integration test status, screenshots, etc. -->
