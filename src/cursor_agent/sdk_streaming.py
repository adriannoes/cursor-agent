"""Stream message parsing and callback dispatch (no cursor_sdk import)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from cursor_agent.sdk_facade_models import RunResult, RunStatus, StreamCallbacks


def map_run_status(raw_status: object) -> RunStatus:
    """Map SDK or string statuses onto facade ``RunStatus`` values."""
    if isinstance(raw_status, RunStatus):
        return raw_status
    normalized = str(raw_status).lower()
    if normalized == RunStatus.FINISHED.value:
        return RunStatus.FINISHED
    if normalized == RunStatus.CANCELLED.value:
        return RunStatus.CANCELLED
    if normalized in {RunStatus.ERROR.value, "failed"}:
        return RunStatus.ERROR
    return RunStatus.ERROR


def map_run_result(wait_result: object, *, text: str | None = None) -> RunResult:
    """Map an SDK ``run.wait()`` payload onto ``RunResult``."""
    run_id = getattr(wait_result, "id", None) or getattr(wait_result, "run_id", None)
    if not run_id:
        msg = (
            f"wait_result missing run id: received {wait_result!r}, "
            "expected attribute 'id' or 'run_id'"
        )
        raise ValueError(msg)

    status = map_run_status(getattr(wait_result, "status", RunStatus.ERROR.value))
    usage = getattr(wait_result, "usage", None)
    if usage is None:
        duration_ms = getattr(wait_result, "duration_ms", None)
        if duration_ms is not None:
            usage = {"duration_ms": duration_ms}

    final_text = text
    if final_text is None:
        final_text = getattr(wait_result, "result", None)

    return RunResult(
        run_id=str(run_id),
        status=status,
        text=final_text,
        usage=usage if isinstance(usage, dict) else None,
    )


def extract_assistant_delta(message: object) -> str | None:
    """Extract assistant text delta from a single streamed SDK message."""
    message_body = getattr(message, "message", None)
    if message_body is None:
        return None
    content_blocks = getattr(message_body, "content", None) or []
    parts: list[str] = []
    for block in content_blocks:
        block_text = getattr(block, "text", None)
        if isinstance(block_text, str) and block_text:
            parts.append(block_text)
    if not parts:
        return None
    return "".join(parts)


def extract_text_from_messages(messages: list[object]) -> str:
    """Concatenate assistant text deltas from drained SDK messages."""
    parts: list[str] = []
    for message in messages:
        delta = extract_assistant_delta(message)
        if delta:
            parts.append(delta)
    return "".join(parts)


async def invoke_callback(
    callback: Callable[..., Awaitable[None] | None] | None,
    *args: object,
) -> None:
    """Invoke a stream callback, awaiting when it returns a coroutine."""
    if callback is None:
        return
    result = callback(*args)
    if asyncio.iscoroutine(result):
        await result


async def dispatch_stream_message(
    message: object,
    callbacks: StreamCallbacks | None,
) -> str | None:
    """Dispatch one streamed SDK message to callbacks; return assistant delta."""
    if callbacks is not None:
        message_type = getattr(message, "type", None)
        if message_type == "tool_call":
            tool_name = str(getattr(message, "name", "unknown"))
            tool_status = str(getattr(message, "status", ""))
            tool_args = getattr(message, "args", None) or {}
            if not isinstance(tool_args, dict):
                tool_args = {}
            if tool_status == "running":
                await invoke_callback(callbacks.on_tool_start, tool_name, tool_args)
            elif tool_status in {"completed", "error"}:
                payload = {
                    "args": tool_args,
                    "result": getattr(message, "result", None),
                }
                await invoke_callback(callbacks.on_tool_end, tool_name, payload)

    delta = extract_assistant_delta(message)
    if delta and callbacks is not None:
        await invoke_callback(callbacks.on_assistant_text, delta)
    return delta
