"""Typer application entry point for the cursor-agent CLI (PRD-003)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator

import typer

from cursor_agent.cli.exit_codes import exit_code_for_error, exit_code_for_status
from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.startup import create_store, repl_runtime, session_key_for
from cursor_agent.config.loader import CursorAgentConfig, load_config
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
        return await run_repl(
            pool,
            session_key,
            store,
            config=config,
            facade=facade,
            reader=_stdin_line_reader(),
            writer=typer.echo,
            stream_writer=_echo_delta,
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


@app.callback(invoke_without_command=True)
def cli_entry(ctx: typer.Context) -> None:
    """Interactive Cursor agent CLI."""
    if ctx.invoked_subcommand is not None:
        return
    try:
        config = load_config()
        status = asyncio.run(run_default(config))
    except CursorAgentError as exc:
        # Startup/bootstrap failures (config, auth, bridge, network) -> exit 1 (FR-10).
        raise typer.Exit(exit_code_for_error(exc)) from exc
    raise typer.Exit(exit_code_for_status(status))


def main() -> None:
    """Console-script entry point for the cursor-agent CLI."""
    app()  # pragma: no cover
