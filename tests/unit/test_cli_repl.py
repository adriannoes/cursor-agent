"""Unit tests for CLI REPL slash commands and error handling (PRD-003)."""

from __future__ import annotations

from pathlib import Path

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import ConfigError, NetworkError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, RunStatus, StreamCallbacks
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import (
    CreateAgentTrackingFacade,
    GetSpyPool,
    SendSpyPool,
    drive_repl,
    seed_session,
)


def test_build_repl_command_router_registers_core_slash_commands() -> None:
    """/new, /resume, and /quit dispatch through CommandRouter."""
    router = build_repl_command_router()
    for command in ("new", "resume", "quit"):
        resolved = router.resolve(f"/{command}")
        assert isinstance(resolved, BuiltinMatch)
        assert resolved.canonical_name == command
    help_resolved = router.resolve("/help")
    assert isinstance(help_resolved, BuiltinMatch)
    assert help_resolved.canonical_name == "help"


async def test_run_repl_free_text_send_uses_active_session_id(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free text send passes active session_id to pool.send."""
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await drive_repl(
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

    await drive_repl(
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

    await drive_repl(
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


async def test_run_repl_resume_without_arg_calls_pool_get(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume with no arg calls pool.get(session_key)."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = GetSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
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
    session_id = await seed_session(store, facade, session_key)
    pool = GetSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
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
    await seed_session(store, facade, session_key, runtime="cloud")
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await drive_repl(
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
        model_override: str | None = None,
    ) -> RunResult:
        _ = session_key, message, session_id, callbacks, blocking, model_override
        raise ConfigError(
            "runtime mismatch: received 'cloud', expected 'local'; "
            "start a new session with /new"
        )

    pool.send = raising_send  # type: ignore[method-assign]

    status = await drive_repl(
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


async def test_run_repl_send_run_error_status_notifies_and_continues(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """RunStatus.ERROR is shown to the user and the loop keeps running."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def error_send(
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
        model_override: str | None = None,
    ) -> RunResult:
        _ = session_key, message, session_id, callbacks, blocking, model_override
        return RunResult(run_id="run-error", status=RunStatus.ERROR, text="boom")

    pool.send = error_send  # type: ignore[method-assign]

    status = await drive_repl(
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
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def network_failure_send(
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
        model_override: str | None = None,
    ) -> RunResult:
        _ = session_key, message, session_id, callbacks, blocking, model_override
        raise NetworkError("connection reset by peer")

    pool.send = network_failure_send  # type: ignore[method-assign]

    status = await drive_repl(
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
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    async def failing_get(
        session_key: str,
        session_id: str | None = None,
    ) -> object:
        _ = session_key, session_id
        raise NetworkError("bridge unavailable")

    pool.get = failing_get  # type: ignore[method-assign]

    status = await drive_repl(
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
