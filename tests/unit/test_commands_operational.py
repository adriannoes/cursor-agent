"""Unit tests for P1/P2 slash commands: stop, model, retry, usage (PRD-004)."""

from __future__ import annotations

from pathlib import Path

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunStatus
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import (
    CreateAgentTrackingFacade,
    SendSpyPool,
    drive_repl,
    seed_session,
)
from tests.unit.command_handler_fakes import (
    CancelTrackingFacade,
    ErrorReturningFacade,
    ResumeTrackingFacade,
    UsageReportingFacade,
    _CompressSendSpyFacade,
    _SUMMARY_REPLY,
)


def test_build_repl_command_router_registers_p1_p2_handlers() -> None:
    """P1/P2 commands register through slash_commands for operational control."""
    router = build_repl_command_router()
    for command in ("stop", "model", "retry", "usage", "compress"):
        resolved = router.resolve(f"/{command}")
        assert isinstance(resolved, BuiltinMatch), f"/{command} should be registered"
        assert resolved.canonical_name == command


async def test_free_text_captures_state_for_retry(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free-text turns persist last_user_message so /retry resends the same text."""
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hello agent", "/retry", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert len(pool.send_calls) == 2
    assert pool.send_calls[0]["message"] == "hello agent"
    assert pool.send_calls[1]["message"] == "hello agent"
    assert pool.send_calls[0]["session_id"] == session_id
    assert pool.send_calls[1]["session_id"] == session_id
    assert pool.send_calls[0]["callbacks"] is not None
    assert pool.send_calls[1]["callbacks"] is pool.send_calls[0]["callbacks"]


async def test_repl_exit_status_reflects_last_error_turn(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """run_repl returns RunStatus.ERROR from state after a failed free-text turn."""
    facade = ErrorReturningFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("trigger error", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert status == RunStatus.ERROR
    assert any("Run failed" in line for line in output)


async def test_stop_calls_facade_cancel_for_active_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/stop resolves the active session agent and calls facade.cancel."""
    facade = CancelTrackingFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/stop", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert facade.cancel_calls == [row.agent_id]
    assert status == RunStatus.CANCELLED


async def test_model_sets_override_and_resumes_agent(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/model <id> stores override on ReplState and resumes the active agent."""
    facade = ResumeTrackingFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/model composer-2.5-fast", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    model_calls = [
        call for call in facade.resume_calls if call["model"] == "composer-2.5-fast"
    ]
    assert len(model_calls) == 1
    assert model_calls[0]["agent_id"] == row.agent_id


async def test_model_override_applies_to_new_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/model then /new creates the agent with the override instead of config.model."""
    facade = CreateAgentTrackingFacade(scripted_replies={"default": "ok"})
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
        lines=("/model composer-2.5-fast", "/new", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert len(facade.create_agent_calls) == 1
    assert facade.create_agent_calls[0]["model"] == "composer-2.5-fast"


async def test_repl_free_text_passes_model_override_to_pool(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free-text sends thread ReplState.model_override into pool.send."""
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/model composer-2.5-fast", "hello", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert len(pool.send_calls) == 1
    assert pool.send_calls[0]["model_override"] == "composer-2.5-fast"


async def test_post_compress_free_text_targets_new_agent(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """A free-text turn after /compress resumes and sends via the swapped agent_id."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    facade._status_session_id = session_id
    row_before = await store.resolve(session_key, session_id=session_id)
    assert row_before is not None
    previous_agent_id = row_before.agent_id
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/compress", "follow-up", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.agent_id != previous_agent_id
    assert facade.send_calls[-1]["agent_id"] == row_after.agent_id


async def test_retry_without_previous_message_does_not_send(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/retry with no prior free-text turn does not call pool.send."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/retry", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert len(pool.send_calls) == 0


async def test_retry_without_previous_message_shows_guidance(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/retry with empty last_user_message reports a clear user-facing message."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/retry", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert any("No previous message to retry." in line for line in output)


async def test_usage_reports_no_data_when_empty(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/usage before any turn reports that no usage data is available."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/usage", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    assert any("No usage data" in line for line in output)


async def test_usage_shows_last_turn_usage(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/usage displays usage captured from the last free-text send result."""
    usage = {"duration_ms": 120, "tokens": 42}
    facade = UsageReportingFacade(usage=usage, scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hello", "/usage", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    usage_line = next(line for line in output if "duration_ms" in line)
    assert "120" in usage_line
    assert "tokens" in usage_line
