"""Unit tests for CLI REPL streaming output (PRD-003)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.rich_display import RichDisplay
from cursor_agent.cli.startup import session_key_for
from cursor_agent.cli.stream_renderer import build_display_stream_callbacks
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.errors import ConfigError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import (
    FakeSdkFacade,
    LogContext,
    RunResult,
    StreamCallbacks,
)
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import (
    FakeThinkingDisplay,
    TimelineSendSpyPool,
    drive_repl,
    line_reader,
    seed_session,
)


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


_SENSITIVE_TOOL_ARGS: dict[str, Any] = {
    "pattern": "SECRET_TOKEN_xyz",
    "path": "/home/user/.ssh/id_rsa",
}


@pytest.mark.asyncio
async def test_run_repl_uses_injected_stream_callbacks_for_tool_badges(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Injected Rich stream callbacks route tool badges to the line writer only."""
    facade = FakeSdkFacade(
        scripted_replies={"default": "ok"},
        scripted_tool_events=[("grep", _SENSITIVE_TOOL_ARGS)],
    )
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    line_sink: list[str] = []
    delta_sink: list[str] = []
    display = RichDisplay(
        stream_writer=delta_sink.append,
        status_writer=line_sink.append,
    )
    stream_callbacks = build_display_stream_callbacks(display)

    await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader("ping", "/quit"),
        writer=line_sink.append,
        stream_writer=delta_sink.append,
        stream_callbacks=stream_callbacks,
        auto_resume=True,
    )

    assert delta_sink == ["o", "k", "\n"]
    badge_lines = [line for line in line_sink if line.startswith("[tool]")]
    assert len(badge_lines) == 2
    assert all("grep" in line for line in badge_lines)
    assert "SECRET_TOKEN_xyz" not in " ".join(badge_lines)


class _AlwaysRaisingSendFacade(FakeSdkFacade):
    """FakeSdkFacade that always raises on send (thinking finally-path coverage)."""

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Raise a domain error so the REPL/send site must still stop thinking."""
        _ = agent_id, message, callbacks, log_context
        raise ConfigError(
            "send failed: received free-text payload, expected test failure"
        )


def _workspace_skills_config(tmp_path: Path, *, workspace: Path) -> CursorAgentConfig:
    """Build config with ``runtime.local.cwd`` pointed at an injectable workspace."""
    return load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={"runtime": {"local": {"cwd": str(workspace)}}},
    )


def _write_project_skill(
    workspace: Path,
    *,
    name: str = "canvas",
    body: str = "Use the canvas skill playbook.",
) -> None:
    """Create ``.cursor/skills/{name}/SKILL.md`` under an injectable workspace."""
    skill_dir = workspace / ".cursor" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: Test skill {name}.",
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


async def test_run_repl_free_text_starts_thinking_before_send_and_stops_in_finally(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """FR-1: free-text turns start thinking before pool.send and stop in finally."""
    events: list[str] = []
    thinking = FakeThinkingDisplay(events)
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = TimelineSendSpyPool(store=store, facade=facade, config=config, events=events)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hello agent", "/quit"),
        writer=output.append,
        auto_resume=True,
        thinking=thinking,
    )

    assert events == ["start_thinking", "pool.send", "stop_thinking"]
    assert len(pool.send_calls) == 1


async def test_run_repl_free_text_stops_thinking_when_send_raises(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """FR-1: free-text thinking stops in finally even when pool.send raises."""
    events: list[str] = []
    thinking = FakeThinkingDisplay(events)
    facade = _AlwaysRaisingSendFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)
    pool = TimelineSendSpyPool(store=store, facade=facade, config=config, events=events)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("trigger error", "/quit"),
        writer=output.append,
        auto_resume=True,
        thinking=thinking,
    )

    assert events == ["start_thinking", "pool.send", "stop_thinking"]


async def test_run_repl_skill_starts_thinking_before_send_and_stops_in_finally(
    tmp_path: Path,
) -> None:
    """FR-1: skill invoke path starts thinking before pool.send and stops in finally."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_project_skill(workspace)
    config = _workspace_skills_config(tmp_path, workspace=workspace)

    events: list[str] = []
    thinking = FakeThinkingDisplay(events)
    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = TimelineSendSpyPool(store=store, facade=facade, config=config, events=events)

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/canvas", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
        thinking=thinking,
    )

    assert events == ["start_thinking", "pool.send", "stop_thinking"]
    assert len(pool.send_calls) == 1
    assert "## Skill: canvas" in str(pool.send_calls[0]["message"])
