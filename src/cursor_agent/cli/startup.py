"""CLI startup bootstrap helpers (PRD-003)."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.messaging_hooks import ensure_messaging_hooks
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import AsyncSdkFacade, SdkFacade
from cursor_agent.sessions.models import build_cli_session_key
from cursor_agent.sessions.store import SessionStore
from cursor_agent.tool_profile_policy import requires_messaging_hooks

DEFAULT_DB_PATH = Path.home() / ".cursor-agent" / "sessions.db"
_MODULE_LOGGER = logging.getLogger(__name__)
_CWD_DOTENV_FILENAME = ".env"

# Captured once before the first dotenv load so ``setup show`` can attribute
# keys present only in ``.env`` as ``env`` rather than ``shell`` (FR-4).
_PRE_DOTENV_PROCESS_ENVIRON: dict[str, str] | None = None


def snapshot_process_environ_before_dotenv() -> Mapping[str, str]:
    """Return (and lazily capture) process env before any CWD dotenv merge.

    The first call freezes the mapping; later dotenv loads must not change it.
    Callers that never touch dotenv get a snapshot of the current environ.

    Example:
        >>> # snapshot_process_environ_before_dotenv()
    """
    global _PRE_DOTENV_PROCESS_ENVIRON
    if _PRE_DOTENV_PROCESS_ENVIRON is None:
        _PRE_DOTENV_PROCESS_ENVIRON = {
            str(key): str(value) for key, value in os.environ.items()
        }
    return _PRE_DOTENV_PROCESS_ENVIRON


def load_cwd_dotenv() -> None:
    """Load gitignored CWD ``.env`` into ``os.environ`` without overriding exports.

    Called during CLI bootstrap so values like ``CURSOR_API_KEY`` are visible to the
    SDK facade via ``os.environ`` (Pydantic ``env_file`` alone does not populate it).
    Snapshots process environ once before the first load for ``setup show`` provenance.

    Example:
        >>> load_cwd_dotenv()  # doctest: +SKIP
    """
    snapshot_process_environ_before_dotenv()
    env_path = Path.cwd() / _CWD_DOTENV_FILENAME
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def resolve_sessions_db_path() -> Path:
    """Return the SQLite session store path from env or the default location.

    Honors ``CURSOR_AGENT_SESSIONS_DB`` (spike flat env per ``.env.example``).

    Example:
        >>> resolve_sessions_db_path()  # doctest: +SKIP
        PosixPath('/Users/me/.cursor-agent/sessions.db')
    """
    load_cwd_dotenv()
    override = os.environ.get("CURSOR_AGENT_SESSIONS_DB", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_DB_PATH


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
    return SessionStore(store_path or resolve_sessions_db_path())


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
    load_cwd_dotenv()
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
            mcp_full_servers=config.mcp.full.servers,
            mcp_full_github_transport=config.mcp.full.github_transport,
        ) as real:
            pool = SessionAgentPool(store=store, facade=real, config=config)
            yield pool, session_key, store, real
