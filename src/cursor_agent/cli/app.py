"""Typer application entry point for the cursor-agent CLI (PRD-003)."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Annotated

import typer

from cursor_agent.cli.auth_command import auth_app
from cursor_agent.cli.cron_commands import cron_app
from cursor_agent.cli.doctor_command import doctor_command
from cursor_agent.cli.error_display import format_startup_error
from cursor_agent.cli.exit_codes import exit_code_for_error, exit_code_for_status
from cursor_agent.cli.first_run_marker import (
    default_marker_home,
    is_first_run,
    mark_complete,
)
from cursor_agent.cli.gateway_check import GatewayConfigPathOpt, gateway_app
from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.rich_display import RichDisplay
from cursor_agent.cli.sessions_commands import sessions_app
from cursor_agent.cli.setup_commands import setup_app
from cursor_agent.cli.skills_commands import skills_app
from cursor_agent.cli.startup import load_cwd_dotenv, repl_runtime
from cursor_agent.cli.stream_renderer import build_display_stream_callbacks
from cursor_agent.cli.usage_command import usage_command
from cursor_agent.cli.welcome import render_welcome
from cursor_agent.config.loader import CursorAgentConfig, ToolProfile, load_config
from cursor_agent.errors import CursorAgentError
from cursor_agent.gateway.runner import run_gateway
from cursor_agent.sdk_facade import RunStatus

app = typer.Typer()

app.add_typer(sessions_app, name="sessions")
app.add_typer(cron_app, name="cron")
app.add_typer(setup_app, name="setup")
app.add_typer(skills_app, name="skills")
app.add_typer(auth_app, name="auth")
app.add_typer(gateway_app, name="gateway")
app.command("usage")(usage_command)
app.command("doctor")(doctor_command)


async def _stdin_line_reader() -> AsyncIterator[str]:  # pragma: no cover
    """Read UTF-8 lines from stdin for the interactive REPL."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        yield line.rstrip("\n")


def _echo_delta(text: str) -> None:  # pragma: no cover
    """Write a streaming assistant delta inline (no trailing newline)."""
    typer.echo(text, nl=False)


def _stdout_is_tty() -> bool:
    """Return whether stdout is an interactive terminal."""
    return sys.stdout.isatty()


_CI_DISABLED_VALUES = frozenset({"", "0", "false", "no", "off"})


def _is_ci_environment() -> bool:
    """Return whether CI suppression is active via a truthy ``CI`` env value."""
    raw = os.environ.get("CI")
    if raw is None:
        return False
    return raw.strip().lower() not in _CI_DISABLED_VALUES


async def run_default(
    config: CursorAgentConfig,
    *,
    no_banner: bool = False,
    marker_home: Path | None = None,
    is_tty: bool | None = None,
    is_ci: bool | None = None,
) -> RunStatus | None:  # pragma: no cover
    """Open REPL runtime and run the default interactive session."""
    home = default_marker_home() if marker_home is None else marker_home
    tty = _stdout_is_tty() if is_tty is None else is_tty
    ci = _is_ci_environment() if is_ci is None else is_ci
    first_run = is_first_run(marker_home=home)

    welcome_written = render_welcome(
        typer.echo,
        first_run=first_run,
        is_tty=tty,
        no_banner=no_banner,
        is_ci=ci,
    )
    pending_first_run_marker = first_run and welcome_written

    async with repl_runtime(config) as (pool, session_key, store, facade):
        if pending_first_run_marker:
            mark_complete(marker_home=home, is_ci=ci)
        display = RichDisplay(
            stream_writer=_echo_delta,
            status_writer=typer.echo,
        )
        return await run_repl(
            pool,
            session_key,
            store,
            config=config,
            facade=facade,
            reader=_stdin_line_reader(),
            writer=typer.echo,
            stream_writer=_echo_delta,
            stream_callbacks=build_display_stream_callbacks(display),
        )


@gateway_app.callback(invoke_without_command=True)
def gateway_callback(
    ctx: typer.Context,
    config: GatewayConfigPathOpt = None,
) -> None:
    """Run the long-running messaging gateway (default when no subcommand)."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        # WHY: call ``run_gateway`` from this module so tests that monkeypatch
        # ``cursor_agent.cli.app.run_gateway`` keep working after the Typer group.
        exit_code = asyncio.run(run_gateway(config_path=config))
    except CursorAgentError as exc:
        raise typer.Exit(exit_code_for_error(exc)) from exc
    raise typer.Exit(exit_code)


def _cli_overrides_for_profile(
    profile: ToolProfile | None,
) -> Mapping[str, object] | None:
    """Build load_config CLI overrides when --profile is present."""
    if profile is None:
        return None
    return {"tool_profile": profile}


@app.callback(invoke_without_command=True)
def cli_entry(
    ctx: typer.Context,
    profile: Annotated[
        ToolProfile | None,
        typer.Option(
            "--profile",
            help="Tool profile override (coding, messaging, or full).",
        ),
    ] = None,
    no_banner: Annotated[
        bool,
        typer.Option(
            "--no-banner",
            help="Suppress the interactive welcome banner.",
        ),
    ] = False,
) -> None:
    """Interactive Cursor agent CLI."""
    load_cwd_dotenv()
    if ctx.invoked_subcommand is not None:
        return
    try:
        config = load_config(cli_overrides=_cli_overrides_for_profile(profile))
        status = asyncio.run(run_default(config, no_banner=no_banner))
    except CursorAgentError as exc:
        typer.echo(format_startup_error(exc))
        raise typer.Exit(exit_code_for_error(exc)) from exc
    raise typer.Exit(exit_code_for_status(status))


def main() -> None:
    """Console-script entry point for the cursor-agent CLI."""
    load_cwd_dotenv()
    app()  # pragma: no cover
