"""Streaming output helpers for the CLI REPL (PRD-003)."""

from __future__ import annotations

from collections.abc import Callable

from cursor_agent.sdk_facade import StreamCallbacks


def build_stream_callbacks(writer: Callable[[str], None]) -> StreamCallbacks:
    """Build ``StreamCallbacks`` that emit assistant text deltas via ``writer``.

    Each delta is written individually (not accumulated).

    Example:
        callbacks = build_stream_callbacks(print)
    """

    async def on_assistant_text(delta: str) -> None:
        writer(delta)

    return StreamCallbacks(on_assistant_text=on_assistant_text)
