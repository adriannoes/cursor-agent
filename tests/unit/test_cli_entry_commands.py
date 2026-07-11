"""Unit tests for documented CLI command smoke checks (PRD-012 Task 6.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.core import TyperOption
from typer.main import get_command
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.sdk_facade import RunStatus


def test_help_shows_sessions_subcommand() -> None:
    """Root --help lists the sessions subcommand group."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sessions" in result.stdout


# --- PRD-012 Task 6.3: documented CLI command smoke checks ---


def test_documented_root_help_exposes_product_subcommands() -> None:
    """examples/README.md commands: root CLI registers gateway, sessions, cron, and --profile."""
    # Introspect registered options/commands instead of --help stdout: Rich formatting
    # varies by terminal width and CI runner environment (see test_cli_registers_no_banner_option).
    root_command = get_command(app)
    registered_subcommands = set(root_command.commands)
    assert {"gateway", "sessions", "cron"} <= registered_subcommands

    profile_option = next(
        (
            param
            for param in root_command.params
            if isinstance(param, TyperOption) and "--profile" in param.opts
        ),
        None,
    )
    assert profile_option is not None
    assert profile_option.name == "profile"


def test_documented_profile_messaging_invokes_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """examples/README.md: --profile messaging is a registered CLI entry."""
    captured: dict[str, object] = {"profile": None}

    async def stub_run_default(
        config: CursorAgentConfig,
        *,
        no_banner: bool = False,
    ) -> RunStatus | None:
        _ = no_banner
        captured["profile"] = config.tool_profile
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, ["--profile", "messaging"])
    assert result.exit_code == 0
    assert captured["profile"] == "messaging"


def test_documented_sessions_list_command_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """examples/README.md: sessions list runs without CURSOR_API_KEY."""

    async def stub_list_sessions(_config: CursorAgentConfig) -> list[object]:
        return []

    monkeypatch.setattr(
        "cursor_agent.cli.app._list_sessions_for_config",
        stub_list_sessions,
    )

    result = CliRunner().invoke(app, ["sessions", "list"])
    assert result.exit_code == 0
    assert "No sessions found" in result.stdout


def test_documented_gateway_command_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """examples/README.md: gateway subcommand is registered and invokable."""

    async def stub_run_gateway(config_path: Path | None = None) -> int:
        _ = config_path
        return 0

    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)

    result = CliRunner().invoke(app, ["gateway"])
    assert result.exit_code == 0


def test_documented_cron_list_command_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """examples/README.md: cron list runs without CURSOR_API_KEY."""
    cron_root = tmp_path / "cron"
    cron_root.mkdir()
    monkeypatch.setattr(
        "cursor_agent.cli.cron_commands.resolve_cron_root",
        lambda _config: cron_root,
    )

    result = CliRunner().invoke(app, ["cron", "list"])
    assert result.exit_code == 0
    assert "No cron jobs configured" in result.stdout
