"""Unit tests for Memory v1 first-turn injection through SessionAgentPool (PRD-008)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config import CursorAgentConfig, load_config
from cursor_agent.errors import ConfigError, InvalidAgentError, SdkInternalError
from cursor_agent.facade_logging import LogContext
from cursor_agent.memory import LocalMemoryStore
from cursor_agent.memory.store import (
    MEMORY_SECTION_MARKER,
    USER_MEMORY_SECTION_MARKER,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, RunStatus, StreamCallbacks
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

_USER_FILENAME = "USER.md"
_MEMORY_FILENAME = "MEMORY.md"


@pytest.fixture
def config() -> CursorAgentConfig:
    """Default local runtime config for memory injection tests."""
    return load_config(config_path=Path("/nonexistent/config.yaml"))


@pytest.fixture
async def store(tmp_path: Path) -> SessionStore:
    """Initialized session store on a temp database."""
    session_store = SessionStore(tmp_path / "sessions.db")
    await session_store.initialize()
    return session_store


def _write_memory_files(
    memory_root: Path,
    *,
    user_text: str,
    memory_text: str,
) -> None:
    """Write USER.md and MEMORY.md under a temporary memory root."""
    memory_root.mkdir(parents=True, exist_ok=True)
    (memory_root / _USER_FILENAME).write_text(user_text, encoding="utf-8")
    (memory_root / _MEMORY_FILENAME).write_text(memory_text, encoding="utf-8")


class SendCapturingFacade(FakeSdkFacade):
    """FakeSdkFacade that records send keyword arguments."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.send_calls: list[dict[str, object]] = []

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Record send parameters and delegate to the parent fake."""
        self.send_calls.append(
            {
                "agent_id": agent_id,
                "message": message,
                "callbacks": callbacks,
                "log_context": log_context,
            }
        )
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,
        )


class FailingSendFacade(SendCapturingFacade):
    """Fake facade that records the outgoing message and then fails the send."""

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Record the composed message, then raise a non-reattached SDK error."""
        self.send_calls.append(
            {
                "agent_id": agent_id,
                "message": message,
                "callbacks": callbacks,
                "log_context": log_context,
            }
        )
        raise SdkInternalError("internal: send failed before completion")


async def _seed_session(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    metadata: dict[str, object] | None = None,
    workspace: str = "/tmp/workspace",
) -> str:
    """Create a facade agent and persist a matching session row."""
    agent_id = await facade.create_agent(workspace=workspace)
    record = await session_store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime="local",
            metadata=metadata,
        )
    )
    return record.id


def _expected_injected_message(
    *,
    user_text: str,
    memory_text: str,
    user_message: str,
) -> str:
    """Build the locked first-turn injection message shape used in production."""
    return (
        f"{USER_MEMORY_SECTION_MARKER}\n"
        f"{user_text}\n\n"
        f"{MEMORY_SECTION_MARKER}\n"
        f"{memory_text}\n\n"
        f"{user_message}"
    )


@pytest.mark.asyncio
async def test_first_turn_injects_memory_prefix_content_and_user_text(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """First send prepends locked memory markers, section content, then user text."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv and pytest"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    session_key = "cli:default:meminj1"
    facade = SendCapturingFacade()
    await _seed_session(store, facade, session_key)

    memory_store = LocalMemoryStore(root=memory_root)
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=memory_store,
    )
    user_message = "what is the test command?"
    await pool.send(session_key, user_message)

    assert len(facade.send_calls) == 1
    sent_message = facade.send_calls[0]["message"]
    expected = _expected_injected_message(
        user_text=user_text,
        memory_text=memory_text,
        user_message=user_message,
    )
    assert sent_message == expected
    assert sent_message.index(USER_MEMORY_SECTION_MARKER) < sent_message.index(
        MEMORY_SECTION_MARKER
    )
    assert sent_message.index(MEMORY_SECTION_MARKER) < sent_message.index(user_message)


@pytest.mark.asyncio
async def test_first_turn_persists_memory_injected_metadata(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Successful first send stores memory_injected=true in session metadata."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )

    session_key = "cli:default:mempersist1"
    facade = SendCapturingFacade()
    session_id = await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    await pool.send(session_key, "first question")

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is True


@pytest.mark.asyncio
async def test_failed_first_turn_does_not_persist_memory_injected_metadata(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """A failed first send must leave the session eligible for a future injection."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    session_key = "cli:default:memsendfail1"
    facade = FailingSendFacade()
    session_id = await _seed_session(store, facade, session_key)
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )

    with pytest.raises(SdkInternalError):
        await pool.send(session_key, "first question")

    assert facade.send_calls[0]["message"] == _expected_injected_message(
        user_text=user_text,
        memory_text=memory_text,
        user_message="first question",
    )
    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is not True


@pytest.mark.asyncio
async def test_invalid_utf8_memory_file_raises_config_error_before_send(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Invalid UTF-8 memory content fails before SDK send with a domain error."""
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / _USER_FILENAME).write_bytes(b"\xff\xfe\xfa")

    session_key = "cli:default:meminvalidutf8"
    facade = SendCapturingFacade()
    session_id = await _seed_session(store, facade, session_key)
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )

    with pytest.raises(ConfigError, match="USER.md"):
        await pool.send(session_key, "first question")

    assert facade.send_calls == []
    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is not True


@pytest.mark.asyncio
async def test_second_turn_skips_memory_and_updates_run_metadata(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Second send delivers only user text while last_run_id and last_status update."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )

    session_key = "cli:default:memsecond1"
    facade = SendCapturingFacade()
    session_id = await _seed_session(
        store, facade, session_key, metadata={"status": "idle"}
    )

    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    first_result = await pool.send(session_key, "first question")
    second_message = "follow-up question"
    second_result = await pool.send(session_key, second_message)

    assert len(facade.send_calls) == 2
    assert facade.send_calls[1]["message"] == second_message
    assert USER_MEMORY_SECTION_MARKER not in facade.send_calls[1]["message"]

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is True
    assert row.metadata["last_run_id"] == second_result.run_id
    assert row.metadata["last_status"] == RunStatus.FINISHED.value
    assert row.metadata.get("status") == "idle"
    assert first_result.run_id != second_result.run_id


class ColdStartSendFailFacade(SendCapturingFacade):
    """Simulates SDK internal failure on first send after cold resume."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._send_attempts = 0

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Register a cold-resumed agent without requiring prior create."""
        self._messages_by_agent.setdefault(agent_id, [])
        return agent_id

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Fail the first send with an internal SDK-style error."""
        self._send_attempts += 1
        if self._send_attempts == 1:
            raise SdkInternalError("internal: internal error")
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,
        )


class InvalidColdResumeFacade(SendCapturingFacade):
    """Simulates stale agent_id that cannot be resumed after process restart."""

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Raise InvalidAgentError as the live SDK does for unknown agents."""
        _ = workspace, model, tool_profile, runtime_mode
        raise InvalidAgentError(f"invalid agent_id: received {agent_id!r}")


@pytest.mark.asyncio
async def test_cold_start_reattach_skips_memory_when_already_injected(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Reattach after cold start must not re-inject when memory_injected is true."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )

    session_key = "cli:default:memreattach1"
    stale_agent_id = "stale-agent-memory-guard"
    await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=stale_agent_id,
            workspace="/tmp/workspace",
            runtime="local",
            metadata={"memory_injected": True, "status": "idle"},
        )
    )

    facade = ColdStartSendFailFacade(default_reply="ok-after-reattach")
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    user_message = "hello after gateway restart"
    result = await pool.send(session_key, user_message)

    assert result.status is RunStatus.FINISHED
    assert facade._send_attempts == 2
    for call in facade.send_calls:
        assert call["message"] == user_message
        assert USER_MEMORY_SECTION_MARKER not in call["message"]

    row = await store.resolve(session_key)
    assert row is not None
    assert row.agent_id != stale_agent_id
    assert row.metadata.get("memory_injected") is True
    assert row.metadata.get("status") == "idle"


@pytest.mark.asyncio
async def test_cold_start_reattach_injects_memory_when_not_yet_injected(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """A cold-start retry keeps first-turn memory injection when the row is eligible."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    session_key = "cli:default:memreattach-pending"
    stale_agent_id = "stale-agent-memory-pending"
    record = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=stale_agent_id,
            workspace="/tmp/workspace",
            runtime="local",
        )
    )

    facade = ColdStartSendFailFacade(default_reply="ok-after-reattach")
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    user_message = "hello after gateway restart"
    await pool.send(session_key, user_message)

    assert facade._send_attempts == 2
    assert len(facade.send_calls) == 1
    assert facade.send_calls[0]["message"] == _expected_injected_message(
        user_text=user_text,
        memory_text=memory_text,
        user_message=user_message,
    )
    row = await store.resolve(session_key, session_id=record.id)
    assert row is not None
    assert row.agent_id != stale_agent_id
    assert row.metadata.get("memory_injected") is True


@pytest.mark.asyncio
async def test_invalid_cold_resume_reattach_skips_memory_when_already_injected(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Invalid-agent reattach keeps memory_injected guard on the refreshed row."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )

    session_key = "cli:default:memreattach2"
    stale_agent_id = "stale-agent-invalid-memory"
    await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=stale_agent_id,
            workspace="/tmp/workspace",
            runtime="local",
            metadata={"memory_injected": True},
        )
    )

    facade = InvalidColdResumeFacade(default_reply="ok-after-invalid-resume")
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    user_message = "hello after invalid resume"
    await pool.send(session_key, user_message)

    assert len(facade.send_calls) == 1
    assert facade.send_calls[0]["message"] == user_message
    assert USER_MEMORY_SECTION_MARKER not in facade.send_calls[0]["message"]

    row = await store.resolve(session_key)
    assert row is not None
    assert row.agent_id != stale_agent_id
    assert row.metadata.get("memory_injected") is True
