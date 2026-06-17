"""CLI startup bootstrap helpers (PRD-003)."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.messaging_hooks import ensure_messaging_hooks
from cursor_agent.tool_profile_policy import requires_messaging_hooks
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import AsyncSdkFacade, SdkFacade
from cursor_agent.sessions.models import build_cli_session_key
from cursor_agent.sessions.store import SessionStore

DEFAULT_DB_PATH = Path.home() / ".cursor-agent" / "sessions.db"
_MODULE_LOGGER = logging.getLogger(__name__)


def resolve_workspace(config: CursorAgentConfig) -> str:
    """Return absolute workspace path from config runtime cwd."""
    return str(Path(config.runtime.local.cwd).resolve())


def session_key_for(config: CursorAgentConfig) -> str:
    """Return CLI session key for the config workspace (ADR-004)."""
    return build_cli_session_key(config.runtime.local.cwd)


def create_store(
    config: CursorAgentConfig,
    *,
    store_path: Path | None = None,
) -> SessionStore:
    """Create a SessionStore at ``store_path`` or the default DB path."""
    _ = config
    return SessionStore(store_path or DEFAULT_DB_PATH)


def bootstrap_messaging_hooks(
    config: CursorAgentConfig,
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Deploy messaging deny hooks before the first agent run when required."""
    if not requires_messaging_hooks(config.tool_profile, config.tool_profile):
        return
    active_logger = logger if logger is not None else _MODULE_LOGGER
    ensure_messaging_hooks(
        resolve_workspace(config),
        logger=active_logger,
    )


@asynccontextmanager
async def repl_runtime(
    config: CursorAgentConfig,
    *,
    store_path: Path | None = None,
    facade: SdkFacade | None = None,
) -> AsyncIterator[tuple[SessionAgentPool, str, SessionStore, SdkFacade]]:
    """Bootstrap pool, session key, store, and facade for the interactive REPL."""
    bootstrap_messaging_hooks(config)
    store = create_store(config, store_path=store_path)
    await store.initialize()
    session_key = session_key_for(config)

    if facade is not None:
        pool = SessionAgentPool(store=store, facade=facade, config=config)
        try:
            yield pool, session_key, store, facade
        finally:
            await facade.close()
    else:
        async with AsyncSdkFacade(  # pragma: no cover
            api_key=os.environ.get("CURSOR_API_KEY"),
            local_setting_sources=config.runtime.local.setting_sources,
        ) as real:
            pool = SessionAgentPool(store=store, facade=real, config=config)
            yield pool, session_key, store, real
