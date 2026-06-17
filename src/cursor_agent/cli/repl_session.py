"""REPL session loop (PRD-003)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from cursor_agent.cli.error_display import format_error
from cursor_agent.cli.slash_commands import handle_new, handle_resume
from cursor_agent.cli.stream_renderer import build_stream_callbacks
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import CursorAgentError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import RunStatus, SdkFacade
from cursor_agent.sessions.store import SessionStore

_NO_SESSION_GUIDANCE = "No active session. Use /new to start one."
_NO_ACTIVE_SESSION_GUIDANCE = "No active session. Use /new or /resume to continue."
_SLASH_PLACEHOLDER = "Command not available yet"
_RUN_FAILED_NOTICE = "Run failed (status=error). You can retry or continue."


def _parse_resume_arg(line: str) -> str | None:
    """Return the optional UUID argument from a ``/resume`` line."""
    parts = line.split(maxsplit=1)
    if len(parts) < 2:
        return None
    arg = parts[1].strip()
    return arg or None


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
    auto_resume: bool = True,
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
    active_session_id: str | None = None
    last_status: RunStatus | None = None

    if auto_resume:
        # Resume goes through pool.get so the lazy resume + runtime guard
        # (ADR-003) always run (PRD-003 §7). On failure, fall back to a cheap
        # existence probe only to choose between the "/new" hint and the error.
        try:
            row = await pool.get(session_key)
            active_session_id = row.id
            writer(f"Resumed session {active_session_id}")
        except CursorAgentError as exc:
            if await store.resolve(session_key) is None:
                writer(_NO_SESSION_GUIDANCE)
            else:
                writer(format_error(exc))

    async for line in reader:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "/quit":
            break
        if stripped.startswith("/"):
            if stripped == "/new":
                try:
                    active_session_id = await handle_new(
                        facade=facade,
                        store=store,
                        config=config,
                        session_key=session_key,
                        writer=writer,
                    )
                except CursorAgentError as exc:
                    writer(format_error(exc))
                continue
            if stripped == "/resume" or stripped.startswith("/resume "):
                resume_arg = (
                    None if stripped == "/resume" else _parse_resume_arg(stripped)
                )
                new_id = await handle_resume(
                    pool=pool,
                    session_key=session_key,
                    arg=resume_arg,
                    writer=writer,
                )
                if new_id is not None:
                    active_session_id = new_id
                continue
            writer(_SLASH_PLACEHOLDER)
            continue
        if active_session_id is None:
            writer(_NO_ACTIVE_SESSION_GUIDANCE)
            continue
        try:
            result = await pool.send(
                session_key,
                stripped,
                session_id=active_session_id,
                callbacks=build_stream_callbacks(stream_sink),
                blocking=True,
            )
        except CursorAgentError as exc:
            writer(format_error(exc))
            continue
        last_status = result.status
        stream_sink("\n")
        if result.status == RunStatus.ERROR:
            writer(_RUN_FAILED_NOTICE)

    return last_status
