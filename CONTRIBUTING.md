# Contributing to Cursor Agent

Thanks for helping improve **Cursor Agent**. This guide covers how to report issues and submit pull requests.

## Issues

Use [GitHub Issues](https://github.com/adriannoes/cursor-agent/issues) for bugs, feature requests, and feedback.

- **Bug reports:** describe what you expected, what happened, and how to reproduce it. Include your OS, Python version, and the `cursor-agent` command or profile (`coding` vs `messaging`) if relevant.
- **Feature requests:** explain the problem you are solving and the behavior you want. Link related issues or docs when helpful.
- **Security:** do not open public issues for vulnerabilities. See [SECURITY.md](SECURITY.md) for the messaging threat model and reporting guidance.

Choose the **Bug report** or **Feature request** template when opening an issue — it keeps triage fast.

## Pull requests

1. **Fork and branch** from `main` (`git checkout -b fix/short-description`).
2. **Set up** with [uv](https://docs.astral.sh/uv/):

   ```bash
   git clone https://github.com/adriannoes/cursor-agent.git
   cd cursor-agent
   uv sync --group dev
   ```

3. **Verify** before opening a PR (same gate as CI):

   ```bash
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run mypy --strict src
   uv run pytest -m "not integration" -v
   ```

   Integration tests (`pytest -m integration -v`) need `CURSOR_API_KEY` and skip when it is unset.

   Package smoke (`pytest -m package_smoke -v`) builds a wheel, installs it into a temporary virtualenv, and verifies `cursor-agent --help` plus bundled messaging hooks. It does not need `CURSOR_API_KEY`. CI runs it in a separate job so the default PR gate stays fast.

4. **Commit** with [Conventional Commits](https://www.conventionalcommits.org/) (e.g. `feat(cli): add welcome banner`, `fix(gateway): handle empty allowlist`).
5. **Open a PR** with a clear description, linked issues (`Fixes #123`), and notes on testing.

Keep PRs focused — one functional change per PR when possible.

## Release readiness (public launch / version tags)

Before tagging a release or merging a launch PR, run:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src
uv run pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration and not package_smoke"
uv run pytest -m package_smoke -v
uv run pytest tests/test_package_metadata.py -v
```

Optional when `CURSOR_API_KEY` is available:

```bash
uv run pytest -m integration -v
```

Also confirm:

- Public docs (README, `docs/setup.md`, `.env.example`) match supported env names and setup steps.
- No secrets in diffs, logs, or example files.
- No new source or test files above 500 lines without a written exception in the PR.
- Messaging/gateway changes were exercised with `tool_profile: messaging` where relevant.

## Code style and conventions

- **Python 3.11+**, typed public APIs, English comments and docstrings.
- **Lint / format:** Ruff (`ruff check`, `ruff format`).
- **Types:** `mypy --strict` on `src/`.
- **Tests:** pytest under `tests/`. New behavior needs tests; bug fixes need regression tests.
- **SDK isolation:** import `cursor_sdk` only from `src/cursor_agent/sdk_facade.py`.
- **Tool profiles:** use `messaging` for gateway/bot work; see [SECURITY.md](SECURITY.md).
- **Architecture:** significant design changes should align with [docs/decisions/](docs/decisions/README.md).

For TDD workflow and agent-oriented conventions, see [AGENTS.md](AGENTS.md).

**Using AI coding tools?** Start with [AGENTS.md](AGENTS.md) — it is the primary entry point for Cursor and other assistants working in this repo.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
