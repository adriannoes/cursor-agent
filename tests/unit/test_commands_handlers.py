"""Unit tests for P0 slash command handlers via the REPL (PRD-004 FR-3)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli.repl_session import run_repl
from cursor_agent.errors import InvalidAgentError
from cursor_agent.cli.compress import load_compress_prompt
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.memory import LocalMemoryStore
from cursor_agent.memory.store import USER_MEMORY_SECTION_MARKER
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, RunStatus, StreamCallbacks
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

from tests.unit.test_commands_compress import (
    _SUMMARY_REPLY,
    _CompressSendSpyFacade,
)

from tests.unit.cli_repl_helpers import (
    CreateAgentTrackingFacade,
    GetSpyPool,
    SendSpyPool,
    drive_repl,
    line_reader,
    seed_session,
)


class SendCapturingFacade(FakeSdkFacade):
    """FakeSdkFacade that records outgoing messages passed to send()."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.captured_send_messages: list[str] = []

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Record the composed outgoing message before delegating."""
        self.captured_send_messages.append(message)
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,  # type: ignore[arg-type]
        )


class CancelTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records cancel invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.cancel_calls: list[str] = []

    async def cancel(self, agent_id: str) -> None:
        """Record cancel parameters and delegate to the parent fake."""
        self.cancel_calls.append(agent_id)
        await super().cancel(agent_id)


class ResumeTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records resume_agent invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.resume_calls: list[dict[str, Any]] = []

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Record resume parameters and delegate to the parent fake."""
        self.resume_calls.append(
            {
                "agent_id": agent_id,
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
                "runtime_mode": runtime_mode,
            }
        )
        return await super().resume_agent(
            agent_id,
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )


class UsageReportingFacade(FakeSdkFacade):
    """FakeSdkFacade that attaches usage data to every send result."""

    def __init__(self, *, usage: dict[str, Any], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._usage = usage

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Return a finished run with scripted usage metadata."""
        _ = log_context
        result = await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,  # type: ignore[arg-type]
        )
        return RunResult(
            run_id=result.run_id,
            status=result.status,
            text=result.text,
            usage=self._usage,
        )


class _ListLogHandler(logging.Handler):
    """Capture log records as raw message strings for NDJSON assertions."""

    def __init__(self, records: list[str]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record.getMessage())


def _capture_command_logs() -> tuple[logging.Logger, list[str]]:
    """Return a logger and list that collect NDJSON command log lines."""
    logger = logging.getLogger("test.commands.ndjson")
    records: list[str] = []
    handler = _ListLogHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger, records


def _command_log_payloads(records: list[str]) -> list[dict[str, Any]]:
    """Parse NDJSON lines whose events are command_start or command_end."""
    payloads: list[dict[str, Any]] = []
    for line in records:
        payload = json.loads(line)
        if payload.get("event") in {"command_start", "command_end"}:
            payloads.append(payload)
    return payloads


class CancelErrorFacade(FakeSdkFacade):
    """FakeSdkFacade that raises InvalidAgentError on cancel."""

    async def cancel(self, agent_id: str) -> None:
        """Raise a domain error so command boundary logging can record failure."""
        raise InvalidAgentError(f"cancel failed for agent_id={agent_id!r}")


class ErrorReturningFacade(FakeSdkFacade):
    """FakeSdkFacade that returns RunStatus.ERROR on send."""

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Return an error terminal status without raising."""
        _ = agent_id, message, callbacks, log_context
        return RunResult(
            run_id="fake-run-error",
            status=RunStatus.ERROR,
            text="",
            usage=None,
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


def _write_memory_files(
    memory_root: Path,
    *,
    user_text: str,
    memory_text: str,
) -> None:
    """Write USER.md and MEMORY.md under a temporary memory root."""
    memory_root.mkdir(parents=True, exist_ok=True)
    (memory_root / "USER.md").write_text(user_text, encoding="utf-8")
    (memory_root / "MEMORY.md").write_text(memory_text, encoding="utf-8")


async def _seed_session_with_metadata(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    metadata: dict[str, object],
    workspace: str = "/tmp/workspace",
) -> str:
    """Create a session row with explicit metadata for lifecycle regressions."""
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


async def test_new_session_row_has_no_stale_memory_injected_metadata(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Existing behavior: /new creates a row without memory_injected set."""
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
        lines=("/new", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    rows = await store.list(session_key)
    assert len(rows) == 1
    assert rows[0].metadata.get("memory_injected") is not True


async def test_new_creates_fresh_session_eligible_for_memory_injection(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/new after an injected session creates a fresh row that receives memory on first send."""
    memory_root = tmp_path / "memory"
    workspace = str(tmp_path / "workspace")
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )
    facade = SendCapturingFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    old_session_id = await _seed_session_with_metadata(
        store,
        facade,
        session_key,
        metadata={"memory_injected": True},
        workspace=workspace,
    )
    pool = SendSpyPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/new", "hello after new", "/quit"),
        writer=output.append,
        auto_resume=True,
        memory_root=memory_root,
    )

    rows = await store.list(session_key)
    assert len(rows) == 2
    new_row = next(row for row in rows if row.id != old_session_id)
    assert new_row.metadata.get("memory_injected") is True
    old_row = await store.resolve(session_key, session_id=old_session_id)
    assert old_row is not None
    assert old_row.metadata.get("memory_injected") is True
    assert len(pool.send_calls) == 1
    assert pool.send_calls[0]["session_id"] == new_row.id
    assert len(facade.captured_send_messages) == 1
    sent_message = facade.captured_send_messages[0]
    assert USER_MEMORY_SECTION_MARKER in sent_message
    assert "hello after new" in sent_message


async def test_resume_preserves_memory_injected_and_skips_reinjection(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume keeps durable memory_injected metadata and does not re-inject memory."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )
    facade = SendCapturingFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await _seed_session_with_metadata(
        store,
        facade,
        session_key,
        metadata={"memory_injected": True},
    )
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/resume", "follow-up after resume", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=memory_root,
    )

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is True
    assert len(facade.captured_send_messages) == 1
    sent_message = facade.captured_send_messages[0]
    assert USER_MEMORY_SECTION_MARKER not in sent_message
    assert sent_message == "follow-up after resume"


async def test_resume_without_memory_injected_eligible_for_injection(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/resume on a row without memory_injected injects memory on the first send."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )
    facade = SendCapturingFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(store, facade, session_key)
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/resume", "first question", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=memory_root,
    )

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is True
    assert len(facade.captured_send_messages) == 1
    sent_message = facade.captured_send_messages[0]
    assert USER_MEMORY_SECTION_MARKER in sent_message
    assert "first question" in sent_message


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
