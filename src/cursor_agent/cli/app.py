"""Typer application entry point for the cursor-agent CLI (PRD-003)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Mapping
from typing import Annotated

import typer

from cursor_agent.cli.exit_codes import exit_code_for_error, exit_code_for_status
from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.rich_display import RichDisplay
from cursor_agent.cli.startup import create_store, repl_runtime, session_key_for
from cursor_agent.cli.stream_renderer import build_display_stream_callbacks
from cursor_agent.config.loader import CursorAgentConfig, ToolProfile, load_config
from cursor_agent.errors import CursorAgentError
from cursor_agent.sdk_facade import RunStatus
from cursor_agent.sessions.models import SessionRecord

app = typer.Typer()

sessions_app = typer.Typer(help="Manage sessions")
app.add_typer(sessions_app, name="sessions")

_EMPTY_SESSIONS_MESSAGE = "No sessions found for this workspace."
_UNTITLED_PLACEHOLDER = "(untitled)"


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


async def run_default(
    config: CursorAgentConfig,
) -> RunStatus | None:  # pragma: no cover
    """Open REPL runtime and run the default interactive session."""
    async with repl_runtime(config) as (pool, session_key, store, facade):
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


async def _list_sessions_for_config(config: CursorAgentConfig) -> list[SessionRecord]:
    """Initialize the store and list sessions for the config workspace key."""
    store = create_store(config)
    await store.initialize()
    session_key = session_key_for(config)
    return await store.list(session_key)


def _print_session_row(record: SessionRecord) -> None:
    """Print one session row as id, title, and updated_at."""
    title = record.title if record.title is not None else _UNTITLED_PLACEHOLDER
    typer.echo(f"{record.id}\t{title}\t{record.updated_at}")


@sessions_app.command("list")
def sessions_list() -> None:
    """List sessions for the current workspace session key."""
    try:
        config = load_config()
    except CursorAgentError as exc:
        raise typer.Exit(exit_code_for_error(exc)) from exc

    rows = asyncio.run(_list_sessions_for_config(config))
    if not rows:
        typer.echo(_EMPTY_SESSIONS_MESSAGE)
        return

    for row in rows:
        _print_session_row(row)


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
            help="Tool profile override (coding or messaging).",
        ),
    ] = None,
) -> None:
    """Interactive Cursor agent CLI."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        config = load_config(cli_overrides=_cli_overrides_for_profile(profile))
        status = asyncio.run(run_default(config))
    except CursorAgentError as exc:
        # Startup/bootstrap failures (config, auth, bridge, network) -> exit 1 (FR-10).
        raise typer.Exit(exit_code_for_error(exc)) from exc
    raise typer.Exit(exit_code_for_status(status))


def main() -> None:
    """Console-script entry point for the cursor-agent CLI."""
    app()  # pragma: no cover
