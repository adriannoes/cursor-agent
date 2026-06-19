"""Unit tests for CLI Typer entry point (PRD-003)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import typer
from typer.core import TyperOption
from typer.main import get_command
from typer.testing import CliRunner

from cursor_agent.cli.app import _echo_delta, _is_ci_environment, app, run_default
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import AuthError
from cursor_agent.product_copy import CURSOR_API_KEY_SETUP_HINT
from cursor_agent.sdk_facade import RunStatus


def test_help_shows_sessions_subcommand() -> None:
    """Root --help lists the sessions subcommand group."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sessions" in result.stdout


def test_cli_registers_no_banner_option() -> None:
    """Root CLI registers the --no-banner suppression flag."""
    # Introspect registered options instead of --help stdout: Rich formatting
    # varies by terminal width and CI runner environment.
    no_banner_option = next(
        (
            param
            for param in get_command(app).params
            if isinstance(param, TyperOption) and "--no-banner" in param.opts
        ),
        None,
    )
    assert no_banner_option is not None
    assert no_banner_option.name == "no_banner"


def test_default_invokes_run_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invoking with no subcommand runs the default REPL bootstrap."""
    called: dict[str, object] = {"invoked": False, "config": None, "no_banner": None}

    async def stub_run_default(
        config: CursorAgentConfig,
        *,
        no_banner: bool = False,
    ) -> RunStatus | None:
        called["invoked"] = True
        called["config"] = config
        called["no_banner"] = no_banner
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert called["invoked"] is True
    assert isinstance(called["config"], CursorAgentConfig)
    assert called["no_banner"] is False


def test_no_banner_passed_to_run_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """--no-banner reaches run_default as a typed suppression flag."""
    called: dict[str, object] = {"invoked": False, "no_banner": None}

    async def stub_run_default(
        config: CursorAgentConfig,
        *,
        no_banner: bool = False,
    ) -> RunStatus | None:
        _ = config
        called["invoked"] = True
        called["no_banner"] = no_banner
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, ["--no-banner"])
    assert result.exit_code == 0
    assert called["invoked"] is True
    assert called["no_banner"] is True


def test_gateway_does_not_call_render_welcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gateway subcommand stays headless and never renders the welcome banner."""
    welcome_called = {"value": False}

    def stub_render_welcome(*_args: object, **_kwargs: object) -> bool:
        welcome_called["value"] = True
        return True

    async def stub_run_gateway(config_path: Path | None = None) -> int:
        _ = config_path
        return 0

    monkeypatch.setattr("cursor_agent.cli.app.render_welcome", stub_render_welcome)
    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)

    result = CliRunner().invoke(app, ["gateway"])
    assert result.exit_code == 0
    assert welcome_called["value"] is False


def test_default_invoke_suppresses_banner_when_ci_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CI=1 suppresses welcome output through the real CLI wiring path."""
    fake_pool = object()
    fake_store = object()
    fake_facade = object()
    session_key = "cli:default:test"

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        yield fake_pool, session_key, fake_store, fake_facade

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)
    monkeypatch.setattr(
        "cursor_agent.cli.app.is_first_run",
        lambda *, marker_home: True,
    )

    result = CliRunner().invoke(app, [], env={"CI": "1"})
    assert result.exit_code == 0
    assert "CURSOR AGENT" not in result.stdout


def test_default_invoke_suppresses_banner_when_stdout_not_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-TTY CliRunner stdout suppresses the banner without mocking isatty()."""
    fake_pool = object()
    fake_store = object()
    fake_facade = object()
    session_key = "cli:default:test"

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        yield fake_pool, session_key, fake_store, fake_facade

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)
    monkeypatch.setattr(
        "cursor_agent.cli.app.is_first_run",
        lambda *, marker_home: False,
    )

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert "CURSOR AGENT" not in result.stdout


def test_default_invoke_auth_error_includes_api_key_setup_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap AuthError output includes the shared CURSOR_API_KEY setup hint."""

    async def stub_run_default(
        _config: CursorAgentConfig,
        *,
        no_banner: bool = False,
    ) -> RunStatus | None:
        _ = no_banner
        raise AuthError("invalid api key")

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 1
    assert "invalid api key" in result.stdout
    assert CURSOR_API_KEY_SETUP_HINT.strip() in result.stdout


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
    monkeypatch.setattr(
        "cursor_agent.cli.app.render_welcome",
        lambda *_args, **_kwargs: False,
    )

    await run_default(config)

    kwargs = captured["kwargs"]
    assert kwargs["writer"] is typer.echo
    assert kwargs["stream_writer"] is _echo_delta
    stream_callbacks = kwargs.get("stream_callbacks")
    assert stream_callbacks is not None
    assert stream_callbacks.on_assistant_text is not None
    assert stream_callbacks.on_tool_start is not None
    assert stream_callbacks.on_tool_end is not None


@pytest.mark.asyncio
async def test_run_default_renders_welcome_before_run_repl(
    monkeypatch: pytest.MonkeyPatch,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Welcome rendering runs before the REPL loop starts."""
    call_order: list[str] = []

    def stub_render_welcome(
        _writer: object,
        *,
        first_run: bool,
        is_tty: bool,
        no_banner: bool,
        is_ci: bool,
    ) -> bool:
        _ = (first_run, is_tty, no_banner, is_ci)
        call_order.append("render_welcome")
        return False

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        yield object(), "cli:default:test", object(), object()

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        call_order.append("run_repl")
        return None

    monkeypatch.setattr("cursor_agent.cli.app.render_welcome", stub_render_welcome)
    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)

    await run_default(config, marker_home=tmp_path, is_tty=True, is_ci=False)

    assert call_order.index("render_welcome") < call_order.index("run_repl")


@pytest.mark.asyncio
async def test_run_default_welcome_output_before_repl_session_line(
    monkeypatch: pytest.MonkeyPatch,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Banner text appears before REPL auto-resume guidance on interactive TTY."""
    echo_calls: list[str] = []

    def capture_echo(message: str, *, nl: bool = True) -> None:
        _ = nl
        echo_calls.append(message)

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        yield object(), "cli:default:test", object(), object()

    async def stub_run_repl(*_args: object, **kwargs: object) -> None:
        writer = kwargs["writer"]
        writer("Resumed session test-session")

    monkeypatch.setattr("cursor_agent.cli.app.typer.echo", capture_echo)
    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)
    monkeypatch.setattr(
        "cursor_agent.cli.app.is_first_run",
        lambda *, marker_home: False,
    )

    await run_default(
        config,
        marker_home=tmp_path,
        is_tty=True,
        is_ci=False,
    )

    joined = "\n".join(echo_calls)
    assert "CURSOR AGENT" in joined
    assert "Resumed session" in joined
    assert joined.index("CURSOR AGENT") < joined.index("Resumed session")


@pytest.mark.asyncio
async def test_run_default_marks_first_run_complete_after_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """First-run marker persists only after repl_runtime bootstrap succeeds."""
    mark_calls: list[dict[str, object]] = []

    def stub_mark_complete(**kwargs: object) -> bool:
        mark_calls.append(dict(kwargs))
        return True

    monkeypatch.setattr("cursor_agent.cli.app.mark_complete", stub_mark_complete)
    monkeypatch.setattr(
        "cursor_agent.cli.app.is_first_run",
        lambda *, marker_home: True,
    )

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        yield object(), "cli:default:test", object(), object()

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)

    await run_default(
        config,
        marker_home=tmp_path,
        is_tty=True,
        is_ci=False,
    )

    assert len(mark_calls) == 1
    assert mark_calls[0]["marker_home"] == tmp_path
    assert mark_calls[0]["is_ci"] is False


@pytest.mark.asyncio
async def test_run_default_skips_marker_when_repl_bootstrap_fails(
    monkeypatch: pytest.MonkeyPatch,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """First-run marker is not persisted when repl_runtime bootstrap fails."""
    mark_called = {"value": False}

    def stub_mark_complete(**_kwargs: object) -> bool:
        mark_called["value"] = True
        return True

    monkeypatch.setattr("cursor_agent.cli.app.mark_complete", stub_mark_complete)
    monkeypatch.setattr(
        "cursor_agent.cli.app.is_first_run",
        lambda *, marker_home: True,
    )

    @asynccontextmanager
    async def failing_repl_runtime(_cfg: CursorAgentConfig):
        raise AuthError("missing api key")
        yield object(), "cli:default:test", object(), object()  # pragma: no cover

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", failing_repl_runtime)

    with pytest.raises(AuthError, match="missing api key"):
        await run_default(
            config,
            marker_home=tmp_path,
            is_tty=True,
            is_ci=False,
        )

    assert mark_called["value"] is False


@pytest.mark.parametrize(
    ("ci_value", "expected"),
    [
        (None, False),
        ("", False),
        ("0", False),
        ("false", False),
        ("1", True),
        ("true", True),
    ],
)
def test_is_ci_environment_uses_truthy_ci_values(
    monkeypatch: pytest.MonkeyPatch,
    ci_value: str | None,
    expected: bool,
) -> None:
    """CI suppression follows truthy CI env values per ADR-027 §6."""
    if ci_value is None:
        monkeypatch.delenv("CI", raising=False)
    else:
        monkeypatch.setenv("CI", ci_value)
    assert _is_ci_environment() is expected


@pytest.mark.asyncio
async def test_run_default_no_banner_skips_marker_on_first_run(
    monkeypatch: pytest.MonkeyPatch,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Suppressed first-run sessions do not persist the first-run marker."""
    mark_called = {"value": False}

    def stub_mark_complete(**_kwargs: object) -> bool:
        mark_called["value"] = True
        return True

    monkeypatch.setattr("cursor_agent.cli.app.mark_complete", stub_mark_complete)
    monkeypatch.setattr(
        "cursor_agent.cli.app.is_first_run",
        lambda *, marker_home: True,
    )

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        yield object(), "cli:default:test", object(), object()

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)

    await run_default(
        config,
        no_banner=True,
        marker_home=tmp_path,
        is_tty=True,
        is_ci=False,
    )

    assert mark_called["value"] is False
