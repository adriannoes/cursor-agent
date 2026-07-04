"""Unit tests for CLI /memory show command (PRD-008)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli.slash_commands import build_repl_command_router, handle_new
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.memory import (
    TOTAL_MEMORY_BUDGET_BYTES,
    USER_MEMORY_BUDGET_BYTES,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.memory import LocalMemoryStore
from cursor_agent.memory.store import USER_MEMORY_SECTION_MARKER
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

from cursor_agent.cli.startup import session_key_for

from tests.unit.cli_repl_helpers import (
    CreateAgentTrackingFacade,
    SendSpyPool,
    drive_repl,
    seed_session,
)
from tests.unit.command_handler_fakes import CancelTrackingFacade, SendCapturingFacade


class _SessionCreateFailingStore(SessionStore):
    """SessionStore whose ``create`` always fails to simulate a persist error."""

    async def create(self, params: object) -> object:  # type: ignore[override]
        raise RuntimeError("simulated session store failure")


def _write_bytes(path: Path, byte_count: int, fill: str = "a") -> None:
    """Write exactly ``byte_count`` UTF-8 bytes using a single-byte fill character."""
    path.write_text(fill * byte_count, encoding="utf-8")


def test_build_repl_command_router_registers_memory_handler() -> None:
    """/memory registers as a built-in command for CLI inspection."""
    router = build_repl_command_router()
    resolved = router.resolve("/memory show")
    assert isinstance(resolved, BuiltinMatch)
    assert resolved.canonical_name == "memory"
    assert resolved.arg == "show"


async def test_memory_show_prints_effective_payload_from_temp_root(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/memory show prints the effective payload from an injected memory root."""
    memory_root = tmp_path / "memory-root"
    memory_root.mkdir()
    (memory_root / "USER.md").write_text("prefer dark mode", encoding="utf-8")
    (memory_root / "MEMORY.md").write_text("project uses uv", encoding="utf-8")

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
        lines=("/memory show", "/quit"),
        writer=output.append,
        auto_resume=True,
        memory_root=memory_root,
    )

    combined = "\n".join(output)
    assert "prefer dark mode" in combined
    assert "project uses uv" in combined
    assert "USER.md" in combined
    assert "MEMORY.md" in combined


async def test_memory_update_rejects_unsupported_subcommand(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/memory update is rejected with an explicit unsupported-subcommand error."""
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
        lines=("/memory update", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=tmp_path / "unused-memory-root",
    )

    combined = "\n".join(output).lower()
    assert "unsupported" in combined or "not supported" in combined
    assert "update" in combined


async def test_memory_show_reports_section_quotas_and_byte_counts(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/memory show reports per-section quotas and effective byte counts."""
    memory_root = tmp_path / "memory-root"
    memory_root.mkdir()
    (memory_root / "USER.md").write_text("user-prefs", encoding="utf-8")
    (memory_root / "MEMORY.md").write_text("memory-notes", encoding="utf-8")

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
        lines=("/memory show", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=memory_root,
    )

    combined = "\n".join(output)
    assert f"Quota: {USER_MEMORY_BUDGET_BYTES} bytes" in combined
    memory_quota = TOTAL_MEMORY_BUDGET_BYTES - len("user-prefs".encode("utf-8"))
    assert f"Quota: {memory_quota} bytes" in combined
    assert "Effective: 10 bytes" in combined
    assert "Effective: 12 bytes" in combined
    assert f"Total effective: 22 / {TOTAL_MEMORY_BUDGET_BYTES} bytes" in combined


async def test_memory_show_marks_truncated_sections(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/memory show marks sections truncated by the Memory v1 byte budget."""
    memory_root = tmp_path / "memory-root"
    memory_root.mkdir()
    _write_bytes(memory_root / "USER.md", USER_MEMORY_BUDGET_BYTES + 500)
    _write_bytes(memory_root / "MEMORY.md", 2000)

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
        lines=("/memory show", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=memory_root,
    )

    combined = "\n".join(output)
    assert "Truncated: yes" in combined
    assert "original" in combined.lower()


async def test_memory_show_uses_tilde_cursor_agent_paths_not_absolute(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Missing files are labeled with ~/.cursor-agent/, not expanded absolute paths."""
    memory_root = tmp_path / "memory-root"
    memory_root.mkdir()

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
        lines=("/memory show", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=memory_root,
    )

    combined = "\n".join(output)
    assert "~/.cursor-agent/USER.md" in combined
    assert "~/.cursor-agent/MEMORY.md" in combined
    assert str(memory_root) not in combined
    assert "Status: missing" in combined


async def test_memory_show_reports_invalid_utf8_as_user_facing_error(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Invalid memory files show an actionable error instead of a traceback."""
    memory_root = tmp_path / "memory-root"
    memory_root.mkdir()
    (memory_root / "USER.md").write_bytes(b"\xff\xfe\xfa")

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
        lines=("/memory show", "/quit"),
        writer=output.append,
        auto_resume=False,
        memory_root=memory_root,
    )

    combined = "\n".join(output)
    assert "Error:" in combined
    assert "USER.md" in combined
    assert "expected UTF-8" in combined


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


async def test_handle_new_cancels_agent_when_store_create_fails(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Persist failure after create_agent must cancel the orphaned SDK agent."""
    facade = CancelTrackingFacade()
    store = _SessionCreateFailingStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)

    with pytest.raises(RuntimeError, match="simulated session store failure"):
        await handle_new(
            facade=facade,
            store=store,
            config=config,
            session_key=session_key,
            writer=lambda _line: None,
        )

    assert len(facade.cancel_calls) == 1


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
