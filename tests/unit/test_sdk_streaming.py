"""Unit tests for decomposed SDK streaming helpers."""

from __future__ import annotations

from dataclasses import dataclass
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
