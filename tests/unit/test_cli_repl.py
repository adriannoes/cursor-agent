"""Unit tests for CLI bootstrap and REPL session loop (PRD-003)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.startup import (
    create_store,
    repl_runtime,
    session_key_for,
)
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.errors import ConfigError, NetworkError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, RunStatus, StreamCallbacks
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


@pytest.fixture
def config(tmp_path: Path) -> CursorAgentConfig:
    """Default config loaded from a missing YAML path."""
    return load_config(config_path=tmp_path / "missing.yaml")


def _expected_session_key(cwd: str) -> str:
    absolute = str(Path(cwd).resolve())
    workspace_hash = hashlib.sha256(absolute.encode()).hexdigest()[:8]
    return f"cli:default:{workspace_hash}"


async def _line_reader(*lines: str) -> AsyncIterator[str]:
    for line in lines:
        yield line


async def _seed_session(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    workspace: str = "/tmp/workspace",
    runtime: str = "local",
) -> str:
    """Create a facade agent and persist a matching session row."""
    agent_id = await facade.create_agent(workspace=workspace)
    record = await session_store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=runtime,
        )
    )
    return record.id


class SendSpyPool(SessionAgentPool):
    """SessionAgentPool that records send keyword arguments."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.send_calls: list[dict[str, object]] = []

    async def send(
        self,
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
    ) -> RunResult:
        """Record send parameters and delegate to the parent pool."""
        self.send_calls.append(
            {
                "session_key": session_key,
                "message": message,
                "session_id": session_id,
                "callbacks": callbacks,
                "blocking": blocking,
            }
        )
        return await super().send(
            session_key,
            message,
            session_id=session_id,
            callbacks=callbacks,
            blocking=blocking,
        )


class GetSpyPool(SessionAgentPool):
    """SessionAgentPool that records get invocations."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.get_calls: list[dict[str, object]] = []

    async def get(
        self,
        session_key: str,
        session_id: str | None = None,
    ) -> object:
        """Record get parameters and delegate to the parent pool."""
        self.get_calls.append({"session_key": session_key, "session_id": session_id})
        return await super().get(session_key, session_id=session_id)


class CreateAgentTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records create_agent invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.create_agent_calls: list[dict[str, object]] = []

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Record create_agent parameters and delegate to the parent fake."""
        self.create_agent_calls.append(
            {
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
                "runtime_mode": runtime_mode,
            }
        )
        return await super().create_agent(
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )


async def _run_repl(
    pool: SessionAgentPool,
    session_key: str,
    store: SessionStore,
    config: CursorAgentConfig,
    facade: FakeSdkFacade,
    *,
    lines: tuple[str, ...],
    writer: object,
    auto_resume: bool = False,
) -> RunStatus | None:
    """Invoke ``run_repl`` with the PRD-003 keyword-only contract."""
    return await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=_line_reader(*lines),
        writer=writer,  # type: ignore[arg-type]
        auto_resume=auto_resume,
    )


# --- Task 2.1 + 2.2: startup bootstrap ---


def test_session_key_for_returns_cli_default_hex(config: CursorAgentConfig) -> None:
    """session_key_for returns cli:default:{8hex} for config workspace."""
    key = session_key_for(config)
    expected = _expected_session_key(config.runtime.local.cwd)
    assert key == expected
    assert key.startswith("cli:default:")
    assert len(key.split(":")[2]) == 8


def test_create_store_uses_override_path(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """create_store honors store_path override."""
    db_path = tmp_path / "custom.db"
    store = create_store(config, store_path=db_path)
    assert store._db_path == db_path


async def test_repl_runtime_yields_pool_and_closes_facade(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """repl_runtime initializes store, yields pool, and closes injected facade."""
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    async with repl_runtime(
        config,
        store_path=db_path,
        facade=facade,
    ) as (pool, session_key, store, yielded_facade):
        assert isinstance(pool, SessionAgentPool)
        assert session_key == session_key_for(config)
        assert isinstance(store, SessionStore)
        assert yielded_facade is facade
        assert db_path.exists()
        assert facade._closed is False

    assert facade._closed is True


# --- Task 2.3 + 2.4: REPL loop skeleton ---


async def test_run_repl_auto_resume_with_existing_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """auto_resume sets active session and writes Resumed when store has a row."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=output.append,
        auto_resume=True,
    )

    assert status is None
    assert any("Resumed session" in line for line in output)


async def test_run_repl_no_session_writes_new_guidance(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """When no session exists, writer contains /new guidance."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=output.append,
        auto_resume=True,
    )

    assert any("/new" in line for line in output)


async def test_run_repl_quit_exits_and_returns_none(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/quit breaks the loop and returns None."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=lambda _line: None,
        auto_resume=False,
    )

    assert status is None


async def test_run_repl_unknown_slash_command_placeholder(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Unknown slash commands write placeholder until routing is implemented."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/help", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert any("Command not available yet" in line for line in output)


async def test_run_repl_free_text_without_session_guidance(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free text without active session prompts /new or /resume."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hello", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert any("/new" in line and "/resume" in line for line in output)
    assert pool.send_calls == []


# --- Task 3.1 + 3.2: free-text send with session_id ---


async def test_run_repl_free_text_send_uses_active_session_id(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free text send passes active session_id to pool.send."""
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await _seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hello agent", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert status == RunStatus.FINISHED
    assert len(pool.send_calls) == 1
    assert pool.send_calls[0]["session_id"] == session_id
    assert pool.send_calls[0]["message"] == "hello agent"
    assert pool.send_calls[0]["blocking"] is True


# --- Task 3.3 + 3.4: /new orchestration ---


async def test_run_repl_new_creates_agent_and_session_with_null_title(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/new orchestrates facade.create_agent and store.create with title=None."""
    facade = CreateAgentTrackingFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/new", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert len(facade.create_agent_calls) == 1
    create_call = facade.create_agent_calls[0]
    assert create_call["model"] == config.model
    assert create_call["tool_profile"] == config.tool_profile
    assert create_call["runtime_mode"] == config.runtime.mode

    rows = await store.list(session_key)
    assert len(rows) == 1
    assert rows[0].title is None
    assert any("Created session" in line for line in output)


async def test_run_repl_new_then_send_fills_title_via_pool(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """First free-text send after /new fills session title via the pool."""
    facade = FakeSdkFacade(scripted_replies={"default": "reply"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/new", "fix the failing test", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    rows = await store.list(session_key)
    assert len(rows) == 1
    assert rows[0].title == "fix the failing test"


# --- Task 3.5 + 3.6: /resume and /quit ---


async def test_run_repl_resume_without_arg_calls_pool_get(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume with no arg calls pool.get(session_key)."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await _seed_session(store, facade, session_key)
    pool = GetSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/resume", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert len(pool.get_calls) == 1
    assert pool.get_calls[0]["session_key"] == session_key
    assert pool.get_calls[0]["session_id"] is None
    assert any("Resumed session" in line for line in output)


async def test_run_repl_resume_with_uuid_calls_pool_get_with_id(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume <uuid> calls pool.get(session_key, session_id=<uuid>)."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await _seed_session(store, facade, session_key)
    pool = GetSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=(f"/resume {session_id}", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert len(pool.get_calls) == 1
    assert pool.get_calls[0]["session_id"] == session_id


async def test_run_repl_resume_runtime_mismatch_prints_guidance_and_continues(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """ConfigError from /resume prints guidance and the REPL loop continues."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await _seed_session(store, facade, session_key, runtime="cloud")
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/resume", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert status is None
    assert any("/new" in line for line in output)


async def test_run_repl_send_config_error_prints_guidance_and_continues(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """ConfigError from free-text send prints guidance and the loop continues."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def raising_send(
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
    ) -> RunResult:
        _ = session_key, message, session_id, callbacks, blocking
        raise ConfigError(
            "runtime mismatch: received 'cloud', expected 'local'; "
            "start a new session with /new"
        )

    pool.send = raising_send  # type: ignore[method-assign]

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/new", "hello", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert status is None
    assert any("/new" in line for line in output)


# --- Task 3.7 + 3.8: streaming renderer ---


async def test_run_repl_free_text_streams_assistant_deltas_in_order(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free-text turn streams assistant deltas to writer in order."""
    facade = FakeSdkFacade(scripted_replies={"default": "abc"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await _seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("ping", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    stream_deltas = [line for line in output if line in {"a", "b", "c"}]
    assert stream_deltas == ["a", "b", "c"]


# --- Code-review fixes: REPL error handling (PRD-003 §9) ---


async def test_run_repl_send_run_error_status_notifies_and_continues(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """RunStatus.ERROR is shown to the user and the loop keeps running."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await _seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def error_send(
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
    ) -> RunResult:
        _ = session_key, message, session_id, callbacks, blocking
        return RunResult(run_id="run-error", status=RunStatus.ERROR, text="boom")

    pool.send = error_send  # type: ignore[method-assign]

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("trigger error", "still alive", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    _ = session_id
    assert status == RunStatus.ERROR
    assert any("Run failed" in line for line in output)


async def test_run_repl_send_network_error_prints_and_continues(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Non-config CursorAgentError from send is printed; the loop continues."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await _seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def network_failure_send(
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
    ) -> RunResult:
        _ = session_key, message, session_id, callbacks, blocking
        raise NetworkError("connection reset by peer")

    pool.send = network_failure_send  # type: ignore[method-assign]

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hi", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert status is None
    assert any("connection reset by peer" in line for line in output)


async def test_run_repl_auto_resume_network_error_continues(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Auto-resume failure (CursorAgentError) is printed and the loop survives."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await _seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def failing_get(
        session_key: str,
        session_id: str | None = None,
    ) -> object:
        _ = session_key, session_id
        raise NetworkError("bridge unavailable")

    pool.get = failing_get  # type: ignore[method-assign]

    status = await _run_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=output.append,
        auto_resume=True,
    )

    assert status is None
    assert any("bridge unavailable" in line for line in output)
