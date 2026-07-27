"""Typer handlers for ``cursor-agent sessions`` (PRD-003 FR-9, PRD-017 FR-4).

Owns the full ``sessions`` group so ``app.py`` stays registration-only.
Confirmation for delete/prune follows the LOCKED matrix: ``--yes`` skips the
prompt; interactive ``y``/``yes`` proceeds; ``n``/``no``/empty Enter cancels
with exit 0; ``EOFError`` without ``--yes`` exits 1 and names ``--yes``.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.cli.startup import create_store, session_key_for
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.errors import CursorAgentError
from cursor_agent.sessions.models import SessionRecord
from cursor_agent.sessions.workspace_session_prune import (
    validate_prune_workspace_params,
)

sessions_app = typer.Typer(help="Manage sessions")

_EMPTY_SESSIONS_MESSAGE = "No sessions found for this workspace."
_UNTITLED_PLACEHOLDER = "(untitled)"
_SESSION_NOT_FOUND_MESSAGE = (
    "Session not found for this workspace: received {session_id!r}, "
    "expected an id owned by the current session_key"
)
_PRUNE_CRITERIA_HINT = "sessions prune requires at least one of --older-than or --keep"
_EOF_YES_HINT = (
    "Non-interactive confirmation failed (EOF). Re-run with --yes to proceed."
)
_AFFIRMATIVE_ANSWERS = frozenset({"y", "yes"})


def confirm_session_mutation(*, yes: bool, prompt: str) -> None:
    """Confirm a destructive sessions mutation or exit per the LOCKED matrix.

    Raises:
        typer.Exit: ``0`` on cancel (``n``/``no``/empty Enter); ``1`` on EOF
            without ``--yes`` (message includes ``--yes``).

    Example:
        >>> confirm_session_mutation(yes=True, prompt="Delete? [y/N] ")
    """
    if yes:
        return
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        typer.echo(_EOF_YES_HINT, err=True)
        raise typer.Exit(1) from None
    if answer in _AFFIRMATIVE_ANSWERS:
        return
    raise typer.Exit(0)


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


def _print_session_detail(record: SessionRecord) -> None:
    """Print operator-facing fields for ``sessions show``."""
    title = record.title if record.title is not None else _UNTITLED_PLACEHOLDER
    typer.echo(f"id\t{record.id}")
    typer.echo(f"title\t{title}")
    typer.echo(f"agent_id\t{record.agent_id}")
    typer.echo(f"workspace\t{record.workspace}")
    typer.echo(f"runtime\t{record.runtime}")
    typer.echo(f"tool_profile\t{record.tool_profile}")
    typer.echo(f"created_at\t{record.created_at}")
    typer.echo(f"updated_at\t{record.updated_at}")


def _load_cli_config() -> CursorAgentConfig:
    """Load config or map CursorAgentError to a Typer exit."""
    try:
        return load_config()
    except CursorAgentError as exc:
        raise typer.Exit(exit_code_for_error(exc)) from exc


@sessions_app.command("list")
def sessions_list() -> None:
    """List sessions for the current workspace session key."""
    config = _load_cli_config()
    rows = asyncio.run(_list_sessions_for_config(config))
    if not rows:
        typer.echo(_EMPTY_SESSIONS_MESSAGE)
        return
    for row in rows:
        _print_session_row(row)


@sessions_app.command("show")
def sessions_show(
    session_id: Annotated[str, typer.Argument(help="Session id to inspect.")],
) -> None:
    """Show operator fields for one session in the current workspace.

    Example:
        cursor-agent sessions show <session_id>
    """
    config = _load_cli_config()

    async def _show() -> SessionRecord | None:
        store = create_store(config)
        await store.initialize()
        session_key = session_key_for(config)
        return await store.get(session_key, session_id)

    record = asyncio.run(_show())
    if record is None:
        typer.echo(_SESSION_NOT_FOUND_MESSAGE.format(session_id=session_id), err=True)
        raise typer.Exit(1)
    _print_session_detail(record)


@sessions_app.command("delete")
def sessions_delete(
    session_id: Annotated[str, typer.Argument(help="Session id to delete.")],
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help=(
                "Skip confirmation and delete immediately. "
                "SQLite row only (Q5: does not dispose SDK agents)."
            ),
        ),
    ] = False,
) -> None:
    """Delete one session row for the current workspace (SQLite only; Q5).

    Example:
        cursor-agent sessions delete <session_id> --yes
    """
    confirm_session_mutation(
        yes=yes,
        prompt=f"Delete session {session_id!r}? [y/N] ",
    )
    config = _load_cli_config()

    async def _delete() -> bool:
        store = create_store(config)
        await store.initialize()
        session_key = session_key_for(config)
        return await store.delete(session_key, session_id)

    removed = asyncio.run(_delete())
    if not removed:
        typer.echo(_SESSION_NOT_FOUND_MESSAGE.format(session_id=session_id), err=True)
        raise typer.Exit(1)
    typer.echo(f"Deleted session {session_id}")


@sessions_app.command("prune")
def sessions_prune(
    older_than: Annotated[
        int | None,
        typer.Option(
            "--older-than",
            help="Delete sessions with updated_at older than this many days.",
        ),
    ] = None,
    keep: Annotated[
        int | None,
        typer.Option(
            "--keep",
            help="Keep this many most recently updated sessions; delete the rest.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help=(
                "Skip confirmation and prune immediately. "
                "SQLite rows only (Q5: does not dispose SDK agents)."
            ),
        ),
    ] = False,
) -> None:
    """Prune workspace sessions by age and/or keep window (OR semantics).

    SQLite only (Q5): does not dispose SDK agents / cloud history.

    Example:
        cursor-agent sessions prune --older-than 30 --keep 10 --yes
    """
    # WHY: validate before confirm so negative flags never prompt then traceback.
    try:
        validate_prune_workspace_params(older_than, keep)
    except ValueError as exc:
        if older_than is None and keep is None:
            typer.echo(_PRUNE_CRITERIA_HINT, err=True)
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    confirm_session_mutation(
        yes=yes,
        prompt="Prune matching sessions for this workspace? [y/N] ",
    )
    config = _load_cli_config()

    async def _prune() -> tuple[int, int]:
        store = create_store(config)
        await store.initialize()
        session_key = session_key_for(config)
        deleted_ids = await store.prune_workspace_sessions(
            session_key,
            older_than_days=older_than,
            keep_last=keep,
        )
        remaining = await store.list(session_key)
        return len(deleted_ids), len(remaining)

    deleted_count, kept_count = asyncio.run(_prune())
    typer.echo(f"Deleted {deleted_count}, kept {kept_count}.")
