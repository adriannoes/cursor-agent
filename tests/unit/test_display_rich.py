"""Unit tests for Rich display boundary (PRD-004)."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from rich.console import Console

from cursor_agent.cli.rich_display import RichDisplay
from cursor_agent.cli.stream_renderer import build_display_stream_callbacks
from cursor_agent.sdk_facade import FakeSdkFacade


@pytest.fixture
def sinks() -> tuple[list[str], list[str]]:
    """Return separate stream and status capture lists."""
    return [], []


@pytest.fixture
def display(sinks: tuple[list[str], list[str]]) -> RichDisplay:
    """Build a RichDisplay with injectable sinks and a terminal-free console."""
    stream_sink, status_sink = sinks
    fake_console = Console(
        file=StringIO(),
        force_terminal=False,
        color_system=None,
    )
    return RichDisplay(
        stream_writer=stream_sink.append,
        status_writer=status_sink.append,
        console=fake_console,
    )


@pytest.mark.asyncio
async def test_rich_display_streams_assistant_text_to_stream_writer(
    display: RichDisplay,
    sinks: tuple[list[str], list[str]],
) -> None:
    """Assistant deltas route to stream_writer without touching status_writer."""
    stream_sink, status_sink = sinks
    callbacks = display.build_stream_callbacks()

    assert callbacks.on_assistant_text is not None
    await callbacks.on_assistant_text("hel")
    await callbacks.on_assistant_text("lo")

    assert stream_sink == ["hel", "lo"]
    assert status_sink == []


@pytest.mark.asyncio
async def test_rich_display_tool_badges_go_to_status_writer_only(
    display: RichDisplay,
    sinks: tuple[list[str], list[str]],
) -> None:
    """Tool lifecycle events emit line-oriented badge output on status_writer."""
    stream_sink, status_sink = sinks
    callbacks = display.build_stream_callbacks()

    assert callbacks.on_tool_start is not None
    assert callbacks.on_tool_end is not None
    await callbacks.on_tool_start("grep", {"pattern": "x"})
    await callbacks.on_tool_end("grep", {"result": "ok"})

    assert stream_sink == []
    assert len(status_sink) == 2
    assert all("grep" in line for line in status_sink)
    assert "running" in status_sink[0].lower()
    assert "done" in status_sink[1].lower()


@pytest.mark.asyncio
async def test_rich_display_separates_text_and_badges_in_mixed_stream(
    display: RichDisplay,
    sinks: tuple[list[str], list[str]],
) -> None:
    """Mixed assistant and tool events keep the PRD-003 two-sink contract."""
    stream_sink, status_sink = sinks
    callbacks = display.build_stream_callbacks()

    assert callbacks.on_tool_start is not None
    assert callbacks.on_assistant_text is not None
    assert callbacks.on_tool_end is not None

    await callbacks.on_tool_start("Shell", {})
    await callbacks.on_assistant_text("a")
    await callbacks.on_tool_end("Shell", {})
    await callbacks.on_assistant_text("b")

    assert stream_sink == ["a", "b"]
    assert not any(delta in status_sink for delta in ("a", "b"))
    assert len(status_sink) == 2
    assert all("Shell" in line for line in status_sink)


_SENSITIVE_TOOL_ARGS: dict[str, Any] = {
    "pattern": "SECRET_TOKEN_xyz",
    "path": "/home/user/.ssh/id_rsa",
}


@pytest.mark.asyncio
async def test_display_stream_callbacks_tool_badges_exclude_raw_args(
    display: RichDisplay,
    sinks: tuple[list[str], list[str]],
) -> None:
    """Stream callbacks wired via stream_renderer must not leak tool argument payloads."""
    stream_sink, status_sink = sinks
    callbacks = build_display_stream_callbacks(display)
    facade = FakeSdkFacade(
        scripted_replies={"default": ""},
        scripted_tool_events=[("grep", _SENSITIVE_TOOL_ARGS)],
    )
    agent_id = await facade.create_agent(workspace="/tmp/ws")

    await facade.send(agent_id, "go", callbacks=callbacks)

    assert stream_sink == []
    assert len(status_sink) == 2
    for line in status_sink:
        assert "grep" in line
        assert "SECRET_TOKEN_xyz" not in line
        assert "id_rsa" not in line
        assert "pattern" not in line


@pytest.mark.asyncio
async def test_display_stream_callbacks_tool_badges_track_lifecycle_via_fake_facade(
    display: RichDisplay,
    sinks: tuple[list[str], list[str]],
) -> None:
    """FakeSdkFacade tool events drive running/done badges using only tool names."""
    stream_sink, status_sink = sinks
    callbacks = build_display_stream_callbacks(display)
    facade = FakeSdkFacade(
        scripted_replies={"default": "x"},
        scripted_tool_events=[("Shell", {"command": "rm -rf /"})],
    )
    agent_id = await facade.create_agent(workspace="/tmp/ws")

    await facade.send(agent_id, "go", callbacks=callbacks)

    assert stream_sink == ["x"]
    assert len(status_sink) == 2
    assert "Shell" in status_sink[0]
    assert "running" in status_sink[0].lower()
    assert "Shell" in status_sink[1]
    assert "done" in status_sink[1].lower()
    assert "rm -rf" not in " ".join(status_sink)
    assert "command" not in " ".join(status_sink)
