"""Unit tests for decomposed SDK streaming helpers."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from cursor_agent.sdk_facade_models import RunStatus, StreamCallbacks
from cursor_agent.sdk_streaming import (
    dispatch_stream_message,
    invoke_callback,
    map_run_status,
)


def test_map_run_status_maps_cancelled_and_failed_aliases() -> None:
    assert map_run_status("cancelled") is RunStatus.CANCELLED
    assert map_run_status("failed") is RunStatus.ERROR
    assert map_run_status(RunStatus.FINISHED) is RunStatus.FINISHED


@pytest.mark.asyncio
async def test_invoke_callback_awaits_coroutine_callbacks() -> None:
    events: list[str] = []

    async def on_event(value: str) -> None:
        events.append(value)

    await invoke_callback(on_event, "done")

    assert events == ["done"]


@dataclass
class _ToolCallMessage:
    type: str
    name: str
    status: str
    args: dict[str, Any]
    result: object | None = None


@pytest.mark.asyncio
async def test_dispatch_stream_message_invokes_on_tool_end_for_error_status() -> None:
    ended: list[tuple[str, dict[str, object]]] = []

    async def on_tool_end(name: str, payload: dict[str, object]) -> None:
        ended.append((name, payload))

    callbacks = StreamCallbacks(on_tool_end=on_tool_end)
    message = _ToolCallMessage(
        type="tool_call",
        name="grep",
        status="error",
        args={"pattern": "missing"},
        result={"detail": "not found"},
    )

    await dispatch_stream_message(message, callbacks)

    assert ended == [
        (
            "grep",
            {
                "args": {"pattern": "missing"},
                "result": {"detail": "not found"},
            },
        )
    ]


@pytest.mark.asyncio
async def test_dispatch_stream_message_invokes_on_tool_start_for_running_status() -> None:
    started: list[tuple[str, dict[str, object]]] = []

    async def on_tool_start(name: str, args: dict[str, object]) -> None:
        started.append((name, args))

    callbacks = StreamCallbacks(on_tool_start=on_tool_start)
    message = _ToolCallMessage(
        type="tool_call",
        name="read",
        status="running",
        args={"path": "src/main.py"},
    )

    await dispatch_stream_message(message, callbacks)

    assert started == [("read", {"path": "src/main.py"})]


@pytest.mark.asyncio
async def test_dispatch_stream_message_invokes_on_tool_end_for_completed_status() -> None:
    ended: list[tuple[str, dict[str, object]]] = []

    async def on_tool_end(name: str, payload: dict[str, object]) -> None:
        ended.append((name, payload))

    callbacks = StreamCallbacks(on_tool_end=on_tool_end)
    message = _ToolCallMessage(
        type="tool_call",
        name="write",
        status="completed",
        args={"path": "out.txt"},
        result={"bytes": 42},
    )

    await dispatch_stream_message(message, callbacks)

    assert ended == [
        (
            "write",
            {
                "args": {"path": "out.txt"},
                "result": {"bytes": 42},
            },
        )
    ]


@pytest.mark.asyncio
async def test_dispatch_stream_message_invokes_on_assistant_text() -> None:
    deltas: list[str] = []

    async def on_assistant_text(delta: str) -> None:
        deltas.append(delta)

    callbacks = StreamCallbacks(on_assistant_text=on_assistant_text)
    message = SimpleNamespace(
        type="assistant",
        message=SimpleNamespace(
            content=[SimpleNamespace(text="Hello "), SimpleNamespace(text="world")],
        ),
    )

    delta = await dispatch_stream_message(message, callbacks)

    assert delta == "Hello world"
    assert deltas == ["Hello world"]
