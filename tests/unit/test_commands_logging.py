"""Unit tests for slash command NDJSON logging (ADR-018)."""

from __future__ import annotations

import json
from pathlib import Path

from cursor_agent.cli.compress import load_compress_prompt
from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import line_reader, seed_session
from tests.unit.command_handler_fakes import (
    CancelErrorFacade,
    _CompressSendSpyFacade,
    _SUMMARY_REPLY,
    _capture_command_logs,
    _command_log_payloads,
)


async def test_command_log_emits_start_and_end_ndjson(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Built-in commands emit NDJSON command_start/end with ADR-018 schema fields."""
    logger, records = _capture_command_logs()
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/help", "/quit"),
        writer=output.append,
        auto_resume=True,
        logger=logger,
    )

    payloads = _command_log_payloads(records)
    help_start = next(
        p for p in payloads if p["event"] == "command_start" and p["command"] == "help"
    )
    help_end = next(
        p for p in payloads if p["event"] == "command_end" and p["command"] == "help"
    )

    for payload in (help_start, help_end):
        assert payload["v"] == 1
        assert payload["level"] == "info"
        assert "ts" in payload
        assert payload["session_key"] == session_key
        assert payload["session_id"] == session_id

    assert help_end["outcome"] == "success"
    assert isinstance(help_end["duration_ms"], int)


async def test_command_log_quit_outcome(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/quit records outcome=quit on command_end without logging prompt bodies."""
    logger, records = _capture_command_logs()
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/quit"),
        writer=output.append,
        auto_resume=False,
        logger=logger,
    )

    quit_end = next(
        p
        for p in _command_log_payloads(records)
        if p["event"] == "command_end" and p["command"] == "quit"
    )
    assert quit_end["outcome"] == "quit"
    assert "must not send" not in json.dumps(_command_log_payloads(records))


async def test_command_log_error_outcome_on_boundary_failure(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Unhandled CursorAgentError at the command boundary records outcome=error."""
    logger, records = _capture_command_logs()
    facade = CancelErrorFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/stop", "/quit"),
        writer=output.append,
        auto_resume=True,
        logger=logger,
    )

    stop_end = next(
        p
        for p in _command_log_payloads(records)
        if p["event"] == "command_end" and p["command"] == "stop"
    )
    assert stop_end["outcome"] == "error"
    assert isinstance(stop_end["duration_ms"], int)


async def test_command_log_omits_prompt_bodies_and_tool_args(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Command logs must not include compress prompts, summaries, or tool arguments."""
    logger, records = _capture_command_logs()
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
    compress_prompt = load_compress_prompt()
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/compress", "/quit"),
        writer=output.append,
        auto_resume=True,
        logger=logger,
    )

    log_blob = json.dumps(_command_log_payloads(records))
    assert compress_prompt not in log_blob
    assert _SUMMARY_REPLY not in log_blob
    assert "pattern" not in log_blob
    compress_end = next(
        p
        for p in _command_log_payloads(records)
        if p["event"] == "command_end" and p["command"] == "compress"
    )
    assert compress_end["outcome"] == "success"
    assert compress_end["session_id"] == session_id
