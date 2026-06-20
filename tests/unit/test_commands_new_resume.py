"""Unit tests for /new, /reset, /resume, /quit, and /help (PRD-004 FR-3)."""

from __future__ import annotations

from pathlib import Path

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import (
    CreateAgentTrackingFacade,
    GetSpyPool,
    SendSpyPool,
    drive_repl,
    seed_session,
)


def test_build_repl_command_router_registers_p0_handlers() -> None:
    """P0 commands register through slash_commands, including /help and /reset alias."""
    router = build_repl_command_router()
    for command in ("new", "resume", "quit", "help"):
        resolved = router.resolve(f"/{command}")
        assert isinstance(resolved, BuiltinMatch)
    reset_resolved = router.resolve("/reset")
    assert isinstance(reset_resolved, BuiltinMatch)
    assert reset_resolved.canonical_name == "new"


async def test_p0_new_creates_session_and_activates_for_send(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/new creates a session row and subsequent free text uses the new session id."""
    facade = CreateAgentTrackingFacade(scripted_replies={"default": "ok"})
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
        lines=("/new", "hello after new", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert len(facade.create_agent_calls) == 1
    rows = await store.list(session_key)
    assert len(rows) == 1
    assert pool.send_calls[0]["session_id"] == rows[0].id
    assert any("Created session" in line for line in output)


async def test_p0_reset_aliases_new_creates_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/reset behaves like /new: creates agent, session row, and writer confirmation."""
    facade = CreateAgentTrackingFacade()
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
        lines=("/reset", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert len(facade.create_agent_calls) == 1
    rows = await store.list(session_key)
    assert len(rows) == 1
    assert any("Created session" in line for line in output)


async def test_p0_resume_without_arg_activates_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume with no arg resumes via pool.get and activates the session."""
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
        lines=("/resume", "follow-up", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert any("Resumed session" in line for line in output)
    assert len(pool.send_calls) == 1
    assert pool.send_calls[0]["session_id"] == session_id


async def test_p0_resume_with_id_activates_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume <uuid> passes session_id to pool.get and activates that session."""
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
    assert any("Resumed session" in line for line in output)


async def test_help_lists_p0_p1_p2_commands(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/help lists built-in commands grouped by P0, P1, and P2 priority."""
    facade = FakeSdkFacade()
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
        lines=("/help", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    help_text = "\n".join(output)
    assert "P0" in help_text
    assert "/new" in help_text
    assert "/resume" in help_text
    assert "/help" in help_text
    assert "/quit" in help_text
    assert "P1" in help_text
    assert "/stop" in help_text
    assert "/model" in help_text
    assert "P2" in help_text
    assert "/retry" in help_text
    assert "/usage" in help_text
    assert "/compress" in help_text
    assert "/memory show" in help_text
    assert "Command not available yet" not in help_text


async def test_help_documents_reset_alias(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/help documents that /reset is an alias of /new."""
    facade = FakeSdkFacade()
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
        lines=("/help", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    help_text = "\n".join(output)
    assert "/reset" in help_text
    assert "/new" in help_text
    assert "alias" in help_text.lower()


async def test_p0_quit_exits_repl_loop(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/quit ends the REPL via QuitRequested sentinel without requiring sys.exit."""
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
        lines=("/quit", "must not send"),
        writer=output.append,
        auto_resume=True,
    )

    _ = session_id
    assert status is None
    assert len(pool.send_calls) == 0
    assert "must not send" not in output
