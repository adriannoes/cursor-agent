"""Unit tests for CLI /memory show command (PRD-008 Wave 2B)."""

from __future__ import annotations

from pathlib import Path

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.memory import (
    TOTAL_MEMORY_BUDGET_BYTES,
    USER_MEMORY_BUDGET_BYTES,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from cursor_agent.cli.startup import session_key_for

from tests.unit.cli_repl_helpers import drive_repl, seed_session


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
