"""REPL session loop (PRD-003)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable

from cursor_agent.cli.command_router import (
    CommandContext,
    CommandResult,
    QuitRequested,
    ReplState,
    SessionActivated,
    UnknownSlashCommand,
    execute_builtin_command,
)
from cursor_agent.cli.error_display import format_error
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.cli.stream_renderer import build_stream_callbacks
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import CursorAgentError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import RunStatus, SdkFacade, StreamCallbacks
from cursor_agent.sessions.store import SessionStore

_NO_SESSION_GUIDANCE = "No active session. Use /new to start one."
_NO_ACTIVE_SESSION_GUIDANCE = "No active session. Use /new or /resume to continue."
_RUN_FAILED_NOTICE = "Run failed (status=error). You can retry or continue."


def _apply_command_result(
    result: CommandResult | None,
    state: ReplState,
) -> bool:
    """Update ``ReplState`` from handler output; return True when loop should exit."""
    if isinstance(result, QuitRequested):
        return True
    if isinstance(result, SessionActivated) and result.session_id is not None:
        state.active_session_id = result.session_id
    return False


async def run_repl(
    pool: SessionAgentPool,
    session_key: str,
    store: SessionStore,
    *,
    config: CursorAgentConfig,
    facade: SdkFacade,
    reader: AsyncIterator[str],
    writer: Callable[[str], None],
    stream_writer: Callable[[str], None] | None = None,
    stream_callbacks: StreamCallbacks | None = None,
    auto_resume: bool = True,
    logger: logging.Logger | None = None,
) -> RunStatus | None:
    """Run the interactive REPL loop until ``/quit`` or reader exhaustion.

    ``writer`` is the line-oriented sink (one message per call). ``stream_writer``
    receives assistant text deltas without trailing newlines so streaming renders
    inline (FR-6); it defaults to ``writer`` for tests. Domain errors raised inside
    the loop are printed and the loop continues (PRD-003 §9); the returned
    ``RunStatus`` is the last turn's status, consumed by the CLI for the exit code.

    Example:
        status = await run_repl(
            pool, key, store, config=config, facade=facade,
            reader=lines(), writer=print,
        )
    """
    stream_sink = stream_writer if stream_writer is not None else writer
    send_callbacks = (
        stream_callbacks
        if stream_callbacks is not None
        else build_stream_callbacks(stream_sink)
    )
    state = ReplState()
    router = build_repl_command_router()
    ctx = CommandContext(
        pool=pool,
        store=store,
        config=config,
        facade=facade,
        session_key=session_key,
        state=state,
        stream_callbacks=send_callbacks,
        stream_writer=stream_sink,
        logger=logger,
    )

    if auto_resume:
        # Resume goes through pool.get so the lazy resume + runtime guard
        # (ADR-003) always run (PRD-003 §7). On failure, fall back to a cheap
        # existence probe only to choose between the "/new" hint and the error.
        try:
            row = await pool.get(session_key)
            state.active_session_id = row.id
            writer(f"Resumed session {state.active_session_id}")
        except CursorAgentError as exc:
            if await store.resolve(session_key) is None:
                writer(_NO_SESSION_GUIDANCE)
            else:
                writer(format_error(exc))

    async for line in reader:
        stripped = line.strip()
        if not stripped:
            continue
        resolved = router.resolve(stripped)
        if resolved is not None:
            if isinstance(resolved, UnknownSlashCommand):
                writer(resolved.message)
                continue
            command_result = await execute_builtin_command(
                resolved,
                ctx,
                writer,
                on_error=format_error,
            )
            if _apply_command_result(command_result, state):
                break
            continue
        if state.active_session_id is None:
            writer(_NO_ACTIVE_SESSION_GUIDANCE)
            continue
        try:
            send_result = await pool.send(
                session_key,
                stripped,
                session_id=state.active_session_id,
                callbacks=send_callbacks,
                blocking=True,
            )
        except CursorAgentError as exc:
            writer(format_error(exc))
            continue
        state.last_user_message = stripped
        state.last_status = send_result.status
        state.last_usage = send_result.usage
        stream_sink("\n")
        if send_result.status == RunStatus.ERROR:
            writer(_RUN_FAILED_NOTICE)

    return state.last_status
