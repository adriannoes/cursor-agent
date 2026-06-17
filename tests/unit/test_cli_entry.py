"""Unit tests for CLI Typer entry point (PRD-003)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.sdk_facade import RunStatus


def test_help_shows_sessions_subcommand() -> None:
    """Root --help lists the sessions subcommand group."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sessions" in result.stdout


def test_default_invokes_run_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoking with no subcommand runs the default REPL bootstrap."""
    called: dict[str, object] = {"invoked": False, "config": None}

    async def stub_run_default(config: CursorAgentConfig) -> RunStatus | None:
        called["invoked"] = True
        called["config"] = config
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert called["invoked"] is True
    assert isinstance(called["config"], CursorAgentConfig)
