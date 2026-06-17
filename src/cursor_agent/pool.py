"""Session agent pool — lazy resume, locks, and send wrapper (PRD-002 FR-6–FR-8)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import AgentBusyError, ConfigError
from cursor_agent.facade_logging import LogContext
from cursor_agent.messaging_hooks import (
    ensure_messaging_hooks,
    messaging_hook_source_fingerprint,
)
from cursor_agent.sdk_facade import RunResult, SdkFacade, StreamCallbacks
from cursor_agent.tool_profile_policy import (
    effective_tool_profile,
    requires_messaging_hooks,
)
from cursor_agent.sessions.models import SessionRecord, title_from_first_user_message
from cursor_agent.sessions.store import SessionStore


def _runtime_mismatch_message(session_runtime: str, config_runtime: str) -> str:
    """Build a ConfigError message for cross-runtime resume (ADR-003)."""
    return (
        f"runtime mismatch: received {session_runtime!r}, expected {config_runtime!r}; "
        "start a new session with /new"
    )


def _session_not_found_message(session_key: str, session_id: str | None) -> str:
    """Build a ConfigError message when resolve returns no row."""
    if session_id is None:
        return (
            f"session not found: received session_key={session_key!r}, "
            "expected existing session for key"
        )
    return (
        f"session not found: received session_key={session_key!r}, "
        f"session_id={session_id!r}, expected existing session"
    )


async def _try_acquire_lock(lock: asyncio.Lock) -> bool:
    """Attempt non-blocking lock acquisition (ADR-008; no TOCTOU via ``locked()``)."""
    try:
        await asyncio.wait_for(lock.acquire(), timeout=0)
    except TimeoutError:
        return False
    return True


def _validate_send_message(message: str) -> None:
    """Reject empty user messages before SDK send or store side effects."""
    if not message.strip():
        raise ConfigError(
            f"invalid message: received {message!r}, expected non-empty string after strip"
        )


class SessionAgentPool:
    """Serialize SDK access per session_key with lazy resume from SessionStore.

    Example:
        pool = SessionAgentPool(store=store, facade=facade, config=config)
        row = await pool.get("cli:default:abc12345")
        result = await pool.send(row.session_key, "hello")
    """

    def __init__(
        self,
        store: SessionStore,
        facade: SdkFacade,
        config: CursorAgentConfig,
    ) -> None:
        """Bind store, facade, and validated config."""
        self._store = store
        self._facade = facade
        self._config = config
        self._locks: dict[str, asyncio.Lock] = {}
        self._resumed_models: dict[str, str] = {}
        self._messaging_hooks_deployed: dict[str, str] = {}

    def _resolve_model(self, model_override: str | None) -> str:
        """Return the effective model for resume/send (override wins over config)."""
        if model_override is not None and model_override.strip():
            return model_override.strip()
        return self._config.model

    def _lock_for(self, session_key: str) -> asyncio.Lock:
        """Return the asyncio lock for ``session_key``, creating it lazily."""
        if session_key not in self._locks:
            self._locks[session_key] = asyncio.Lock()
        return self._locks[session_key]

    def _assert_runtime_match(self, row: SessionRecord) -> None:
        """Raise ConfigError when persisted runtime differs from config (ADR-003)."""
        expected = self._config.runtime.mode
        if row.runtime != expected:
            raise ConfigError(_runtime_mismatch_message(row.runtime, expected))

    async def _resolve_or_raise(
        self,
        session_key: str,
        session_id: str | None,
    ) -> SessionRecord:
        """Resolve a session row or raise ConfigError when missing."""
        row = await self._store.resolve(session_key, session_id=session_id)
        if row is None:
            raise ConfigError(_session_not_found_message(session_key, session_id))
        return row

    async def _ensure_messaging_hooks_for_row(self, row: SessionRecord) -> None:
        """Deploy messaging hooks once per workspace and hook-source fingerprint."""
        if not requires_messaging_hooks(
            self._config.tool_profile,
            row.tool_profile,
        ):
            return
        workspace_key = str(Path(row.workspace).resolve())
        fingerprint = messaging_hook_source_fingerprint()
        if self._messaging_hooks_deployed.get(workspace_key) == fingerprint:
            return
        try:
            await asyncio.to_thread(ensure_messaging_hooks, row.workspace)
        except (ConfigError, FileNotFoundError) as exc:
            raise ConfigError(str(exc)) from exc
        self._messaging_hooks_deployed[workspace_key] = fingerprint

    async def _ensure_resumed(
        self,
        row: SessionRecord,
        *,
        model_override: str | None = None,
    ) -> None:
        """Resume the SDK agent when missing or when the effective resume key changed."""
        model = self._resolve_model(model_override)
        tool_profile = effective_tool_profile(
            self._config.tool_profile, row.tool_profile
        )
        resume_key = f"{model}:{tool_profile}"
        if self._resumed_models.get(row.agent_id) == resume_key:
            return
        await self._ensure_messaging_hooks_for_row(row)
        await self._facade.resume_agent(
            row.agent_id,
            workspace=row.workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=row.runtime,
        )
        self._resumed_models[row.agent_id] = resume_key

    def forget_resumed_agent(self, agent_id: str) -> None:
        """Drop resume cache for ``agent_id`` after agent swaps (e.g. /compress)."""
        self._resumed_models.pop(agent_id, None)

    async def get(
        self,
        session_key: str,
        session_id: str | None = None,
        *,
        model_override: str | None = None,
    ) -> SessionRecord:
        """Resolve and lazily resume the session for ``session_key``."""
        row = await self._resolve_or_raise(session_key, session_id)
        self._assert_runtime_match(row)
        await self._ensure_resumed(row, model_override=model_override)
        return row

    async def send(
        self,
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
        model_override: str | None = None,
    ) -> RunResult:
        """Send a message with per-key locking, logging context, and store updates."""
        _validate_send_message(message)
        row = await self._resolve_or_raise(session_key, session_id)
        self._assert_runtime_match(row)

        lock = self._lock_for(session_key)
        if blocking:
            await lock.acquire()
            acquired = True
        else:
            acquired = await _try_acquire_lock(lock)
            if not acquired:
                raise AgentBusyError(
                    f"session busy: received active run on session_key={session_key!r}, "
                    "expected idle session for non-blocking send"
                )

        try:
            await self._ensure_resumed(row, model_override=model_override)
            log_context = LogContext(
                session_id=row.id,
                session_key=row.session_key,
                agent_id=row.agent_id,
            )
            result = await self._facade.send(
                row.agent_id,
                message,
                callbacks=callbacks,
                log_context=log_context,
            )
            if not row.title:
                title = title_from_first_user_message(message)
                await self._store.update_title(row.id, title)
            await self._store.touch(row.id)
            await self._store.update_metadata(
                row.id,
                {
                    "last_run_id": result.run_id,
                    "last_status": result.status.value,
                },
            )
            return result
        finally:
            if acquired:
                lock.release()
