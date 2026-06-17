"""Unit tests for CLI --profile override (PRD-005 FR-12)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.sdk_facade import RunStatus


def test_profile_messaging_passes_cli_override_to_load_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--profile messaging reaches load_config with tool_profile CLI override."""
    captured: dict[str, object] = {"cli_overrides": None, "invoked": False}

    def stub_load_config(
        config_path: object = None,
        cli_overrides: Mapping[str, object] | None = None,
    ) -> CursorAgentConfig:
        captured["cli_overrides"] = dict(cli_overrides) if cli_overrides else None
        return load_config(config_path=config_path, cli_overrides=cli_overrides)

    async def stub_run_default(_config: CursorAgentConfig) -> RunStatus | None:
        captured["invoked"] = True
        return None

    monkeypatch.setattr("cursor_agent.cli.app.load_config", stub_load_config)
    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, ["--profile", "messaging"])
    assert result.exit_code == 0
    assert captured["cli_overrides"] == {"tool_profile": "messaging"}
    assert captured["invoked"] is True


def test_profile_coding_passes_cli_override_to_load_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--profile coding reaches load_config with tool_profile CLI override."""
    captured: dict[str, object] = {"cli_overrides": None}

    def stub_load_config(
        config_path: object = None,
        cli_overrides: Mapping[str, object] | None = None,
    ) -> CursorAgentConfig:
        captured["cli_overrides"] = dict(cli_overrides) if cli_overrides else None
        return load_config(config_path=config_path, cli_overrides=cli_overrides)

    async def stub_run_default(_config: CursorAgentConfig) -> RunStatus | None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.load_config", stub_load_config)
    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, ["--profile", "coding"])
    assert result.exit_code == 0
    assert captured["cli_overrides"] == {"tool_profile": "coding"}


def test_profile_invalid_fails_before_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid --profile values fail at Typer boundary before startup."""
    called: dict[str, bool] = {"load_config": False, "run_default": False}

    def stub_load_config(*_args: object, **_kwargs: object) -> CursorAgentConfig:
        called["load_config"] = True
        raise AssertionError("load_config must not run for invalid --profile")

    async def stub_run_default(_config: CursorAgentConfig) -> RunStatus | None:
        called["run_default"] = True
        return None

    monkeypatch.setattr("cursor_agent.cli.app.load_config", stub_load_config)
    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, ["--profile", "gateway"])
    assert result.exit_code != 0
    assert called["load_config"] is False
    assert called["run_default"] is False
    assert "profile" in result.stdout.lower() or "profile" in result.stderr.lower()


def test_default_invocation_omits_tool_profile_cli_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invoking without --profile does not pass tool_profile in cli_overrides."""
    captured: dict[str, Any] = {"cli_overrides": "unset"}

    def stub_load_config(
        config_path: object = None,
        cli_overrides: Mapping[str, object] | None = None,
    ) -> CursorAgentConfig:
        captured["cli_overrides"] = cli_overrides
        return load_config(config_path=config_path, cli_overrides=cli_overrides)

    async def stub_run_default(_config: CursorAgentConfig) -> RunStatus | None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.load_config", stub_load_config)
    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert captured["cli_overrides"] is None
