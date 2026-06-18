"""Unit tests for skill invocation NDJSON logging (PRD-009 T5, ADR-018)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.startup import session_key_for
from cursor_agent.errors import ConfigError
from cursor_agent.facade_logging import LogContext
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, StreamCallbacks
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import line_reader, seed_session
from tests.unit.test_skills_injection import (
    _project_skills_root,
    _skills_config,
    _write_skill_md,
)


class _FailingSendFacade(FakeSdkFacade):
    """Fake facade that raises after the skill is resolved but before send succeeds."""

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Raise a deterministic facade error for failed skill-send assertions."""
        _ = agent_id, message, callbacks, log_context
        raise ConfigError("send failed: received skill payload, expected test failure")


class _ListLogHandler(logging.Handler):
    """Collect log message strings for NDJSON assertions."""

    def __init__(self, records: list[str]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record.getMessage())


def _capture_skill_logs() -> tuple[logging.Logger, list[str]]:
    """Return a logger and list that collect NDJSON skill log lines."""
    logger = logging.getLogger("test.skills.ndjson")
    records: list[str] = []
    handler = _ListLogHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger, records


def _skill_log_payloads(records: list[str]) -> list[dict[str, Any]]:
    """Parse NDJSON lines whose event is ``skill_invoked``."""
    payloads: list[dict[str, Any]] = []
    for line in records:
        payload = json.loads(line)
        if payload.get("event") == "skill_invoked":
            payloads.append(payload)
    return payloads


def test_emit_skill_invoked_emits_ndjson_with_required_fields() -> None:
    """skill_invoked uses schema v1 fields plus skill_name and source."""
    from cursor_agent.facade_logging import emit_skill_invoked

    logger, records = _capture_skill_logs()

    emit_skill_invoked(
        logger,
        skill_name="canvas",
        source="project",
        session_id="sess-abc",
        session_key="cli:default:deadbeef",
    )

    logger.removeHandler(logger.handlers[0])
    assert len(records) == 1
    payload = json.loads(records[0])
    assert payload["v"] == 1
    assert payload["event"] == "skill_invoked"
    assert payload["level"] == "info"
    assert "ts" in payload
    assert payload["session_id"] == "sess-abc"
    assert payload["session_key"] == "cli:default:deadbeef"
    assert payload["skill_name"] == "canvas"
    assert payload["source"] == "project"


def test_emit_skill_invoked_payload_omits_skill_body_and_absolute_paths() -> None:
    """Serialized skill_invoked must not include skill content or filesystem paths."""
    from cursor_agent.facade_logging import emit_skill_invoked

    home = Path.home().as_posix()
    skill_body_snippet = f"Run playbook from {home}/.cursor/skills/canvas/SKILL.md"

    logger, records = _capture_skill_logs()

    emit_skill_invoked(
        logger,
        skill_name="canvas",
        source="user",
        session_id="sess-1",
        session_key="cli:default:abc12345",
    )

    logger.removeHandler(logger.handlers[0])
    serialized = records[0]
    payload = json.loads(serialized)

    forbidden_keys = {
        "content",
        "body",
        "path",
        "message",
        "skill_path",
        "workspace",
        "skill_body",
    }
    assert forbidden_keys.isdisjoint(payload.keys())
    assert skill_body_snippet not in serialized
    assert home not in serialized


@pytest.mark.asyncio
async def test_repl_skill_invocation_emits_one_skill_invoked_log(
    tmp_path: Path,
) -> None:
    """One successful /skill send emits exactly one skill_invoked via injected logger."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_body = (
        f"Secret playbook at {Path.home()}/.cursor/skills/canvas/SKILL.md "
        f"and workspace {workspace.resolve()}"
    )
    _write_skill_md(
        _project_skills_root(workspace),
        "canvas",
        name="canvas",
        body=skill_body,
    )
    config = _skills_config(tmp_path, workspace=workspace)

    logger, records = _capture_skill_logs()
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(
        store, facade, session_key, workspace=str(workspace)
    )
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/canvas", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
        logger=logger,
    )

    logger.removeHandler(logger.handlers[0])
    payloads = _skill_log_payloads(records)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["v"] == 1
    assert payload["event"] == "skill_invoked"
    assert payload["level"] == "info"
    assert "ts" in payload
    assert payload["session_key"] == session_key
    assert payload["session_id"] == session_id
    assert payload["skill_name"] == "canvas"
    assert payload["source"] == "project"

    log_blob = json.dumps(payloads)
    assert skill_body not in log_blob
    assert str(workspace.resolve()) not in log_blob
    assert Path.home().as_posix() not in log_blob


@pytest.mark.asyncio
async def test_repl_free_text_does_not_emit_skill_invoked(
    tmp_path: Path,
) -> None:
    """Plain user text must not produce skill_invoked events."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _skills_config(tmp_path, workspace=workspace)

    logger, records = _capture_skill_logs()
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("hello agent", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
        logger=logger,
    )

    logger.removeHandler(logger.handlers[0])
    assert _skill_log_payloads(records) == []


@pytest.mark.asyncio
async def test_repl_unknown_slash_does_not_emit_skill_invoked(
    tmp_path: Path,
) -> None:
    """Unknown slash commands must not produce skill_invoked events."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _skills_config(tmp_path, workspace=workspace)

    logger, records = _capture_skill_logs()
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/not-a-real-command", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
        logger=logger,
    )

    logger.removeHandler(logger.handlers[0])
    assert _skill_log_payloads(records) == []


@pytest.mark.asyncio
async def test_repl_failed_skill_send_does_not_emit_skill_invoked(
    tmp_path: Path,
) -> None:
    """A skill_invoked event is emitted only after the skill payload reaches send."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_skill_md(
        _project_skills_root(workspace),
        "canvas",
        name="canvas",
        body="Use the canvas playbook.",
    )
    config = _skills_config(tmp_path, workspace=workspace)

    logger, records = _capture_skill_logs()
    facade = _FailingSendFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("/canvas", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
        logger=logger,
    )

    logger.removeHandler(logger.handlers[0])
    assert _skill_log_payloads(records) == []
