"""Unit tests for CLI exit code mapping (PRD-003 FR-10)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.exit_codes import exit_code_for_error, exit_code_for_status
from cursor_agent.errors import AuthError, ConfigError, CursorAgentError, NetworkError
from cursor_agent.sdk_facade import RunStatus


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RunStatus.FINISHED, 0),
        (RunStatus.CANCELLED, 0),
        (None, 0),
    ],
)
def test_exit_code_for_status_success_and_cancel(
    status: RunStatus | None,
    expected: int,
) -> None:
    """FINISHED, CANCELLED, and None map to exit code 0."""
    assert exit_code_for_status(status) == expected


def test_exit_code_for_status_error() -> None:
    """RunStatus.ERROR maps to exit code 2."""
    assert exit_code_for_status(RunStatus.ERROR) == 2


@pytest.mark.parametrize(
    "exc",
    [
        ConfigError("invalid config"),
        AuthError("invalid api key"),
        NetworkError("connection reset"),
        CursorAgentError("generic pre-run failure"),
    ],
)
def test_exit_code_for_error_cursor_agent_errors(exc: CursorAgentError) -> None:
    """CursorAgentError subclasses map to exit code 1."""
    assert exit_code_for_error(exc) == 1


def test_exit_code_for_error_non_domain_exception() -> None:
    """Non-domain exceptions still map to exit code 1 as a safe default."""
    assert exit_code_for_error(ValueError("unexpected")) == 1


def test_sessions_list_exits_1_on_broken_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One-shot subcommand with invalid config exits 1 before touching the store."""
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__MODE", "invalid")
    result = CliRunner().invoke(app, ["sessions", "list"])
    assert result.exit_code == 1


def test_default_invoke_exits_1_on_broken_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default REPL invoke with invalid config exits 1 (startup failure, FR-10)."""
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__MODE", "invalid")
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 1


def test_default_invoke_exits_2_on_run_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default REPL ending after a RunStatus.ERROR turn exits 2 (FR-10)."""

    async def fake_run_default(config: object) -> RunStatus:
        _ = config
        return RunStatus.ERROR

    monkeypatch.setattr("cursor_agent.cli.app.run_default", fake_run_default)
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 2
