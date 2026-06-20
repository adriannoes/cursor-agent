"""Unit tests for /compress REPL handler (PRD-004 FR-6, FR-7)."""

from __future__ import annotations

from pathlib import Path

from cursor_agent.cli.compress import load_compress_prompt
from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import drive_repl, line_reader, seed_session
from tests.unit.command_handler_fakes import (
    _CompressSendSpyFacade,
    _SUMMARY_REPLY,
    _capture_command_logs,
    _command_log_payloads,
)


def test_load_compress_prompt_reads_versioned_file() -> None:
    """load_compress_prompt returns the repo prompt with expected section headings."""
    prompt = load_compress_prompt()
    assert "## Goal" in prompt
    assert "## Decisions made" in prompt
    assert "## Current state" in prompt
    assert "## Open questions" in prompt
    assert "## Next steps" in prompt
    assert "injected as the first message" in prompt


def test_load_compress_prompt_reads_packaged_file() -> None:
    """load_compress_prompt resolves the wheel-shipped prompt under cursor_agent."""
    from importlib import resources

    packaged = resources.files("cursor_agent").joinpath("prompts/compress.txt")
    assert packaged.is_file()
    assert load_compress_prompt() == packaged.read_text(encoding="utf-8")


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


async def test_compress_without_active_session_shows_guidance(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/compress with no active session reports guidance and does not run the saga."""
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
        lines=("/compress", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert any("No active session" in line for line in output)
    assert not any("Compressing context" in line for line in output)


async def test_compress_happy_path_confirms_success_without_leaking_bodies(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/compress runs the saga, keeps the same session id, and avoids prompt leakage."""
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
    compress_prompt = load_compress_prompt()
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/compress", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.id == session_id
    assert row_after.agent_id != previous_agent_id
    assert any("Compressing context" in line for line in output)
    assert any("Context compressed" in line for line in output)
    assert compress_prompt not in "\n".join(output)
    assert _SUMMARY_REPLY not in "\n".join(output)


async def test_compress_failure_keeps_active_session_and_shows_error(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/compress failure rolls back agent_id and reports a user-facing error."""
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        fail_on_summary_delivery=True,
    )
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
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
        lines=("/compress", "/quit"),
        writer=output.append,
        auto_resume=True,
    )

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.id == session_id
    assert row_after.agent_id == previous_agent_id
    assert any(line.startswith("Error:") for line in output)
    assert _SUMMARY_REPLY not in "\n".join(output)


async def test_compress_failure_records_error_command_outcome(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Handler-internal /compress failures emit command_end outcome=error (ADR-018)."""
    logger, records = _capture_command_logs()
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        fail_on_summary_delivery=True,
    )
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(tmp_path))
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

    compress_end = next(
        p
        for p in _command_log_payloads(records)
        if p["event"] == "command_end" and p["command"] == "compress"
    )
    assert compress_end["outcome"] == "error"
