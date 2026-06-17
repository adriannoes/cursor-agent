"""Unit tests for CLI REPL streaming output (PRD-003)."""

from __future__ import annotations

from pathlib import Path

from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import drive_repl, seed_session


async def test_run_repl_free_text_streams_assistant_deltas_in_order(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free-text turn streams assistant deltas to writer in order."""
    facade = FakeSdkFacade(scripted_replies={"default": "abc"})
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
        lines=("ping", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    stream_deltas = [line for line in output if line in {"a", "b", "c"}]
    assert stream_deltas == ["a", "b", "c"]


async def test_run_repl_streams_deltas_to_separate_sink_from_line_writer(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Assistant deltas route to stream_writer; line messages stay on writer."""
    facade = FakeSdkFacade(scripted_replies={"default": "abc"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    line_sink: list[str] = []
    delta_sink: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("ping", "/quit"),
        writer=line_sink.append,
        stream_writer=delta_sink.append,
        auto_resume=True,
    )

    assert delta_sink == ["a", "b", "c", "\n"]
    assert not any(delta in line_sink for delta in ("a", "b", "c"))
    assert any("Resumed session" in line for line in line_sink)
