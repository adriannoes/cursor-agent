"""Slash command handlers for the CLI REPL (PRD-003)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import CursorAgentError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


async def handle_new(
    *,
    facade: SdkFacade,
    store: SessionStore,
    config: CursorAgentConfig,
    session_key: str,
    writer: Callable[[str], None],
) -> str:
    """Create a new SDK agent and session row; return the new session id."""
    workspace = str(Path(config.runtime.local.cwd).resolve())
    agent_id = await facade.create_agent(
        workspace=workspace,
        model=config.model,
        tool_profile=config.tool_profile,
        runtime_mode=config.runtime.mode,
    )
    row = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=config.runtime.mode,
            tool_profile=config.tool_profile,
            title=None,
        )
    )
    writer(f"Created session {row.id}")
    return row.id


async def handle_resume(
    *,
    pool: SessionAgentPool,
    session_key: str,
    arg: str | None,
    writer: Callable[[str], None],
) -> str | None:
    """Resume a session via ``pool.get``; return session id or ``None`` on failure."""
    try:
        row = await pool.get(session_key, session_id=arg or None)
    except CursorAgentError as exc:
        writer(str(exc))
        return None
    writer(f"Resumed session {row.id}")
    return row.id
