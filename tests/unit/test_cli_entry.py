"""Unit tests for CLI Typer entry point (PRD-003)."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
import typer
from typer.testing import CliRunner

from cursor_agent.cli.app import _echo_delta, app, run_default
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


@pytest.mark.asyncio
async def test_run_default_passes_rich_stream_callbacks_to_run_repl(
    monkeypatch: pytest.MonkeyPatch,
    config: CursorAgentConfig,
) -> None:
    """Production bootstrap wires Rich display callbacks for streaming and tool badges."""
    captured: dict[str, object] = {}
    fake_pool = object()
    fake_store = object()
    fake_facade = object()
    session_key = "cli:default:test"

    @asynccontextmanager
    async def stub_repl_runtime(cfg: CursorAgentConfig):
        assert cfg is config
        yield fake_pool, session_key, fake_store, fake_facade

    async def stub_run_repl(*args: object, **kwargs: object) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)

    await run_default(config)

    kwargs = captured["kwargs"]
    assert kwargs["writer"] is typer.echo
    assert kwargs["stream_writer"] is _echo_delta
    stream_callbacks = kwargs.get("stream_callbacks")
    assert stream_callbacks is not None
    assert stream_callbacks.on_assistant_text is not None
    assert stream_callbacks.on_tool_start is not None
    assert stream_callbacks.on_tool_end is not None
