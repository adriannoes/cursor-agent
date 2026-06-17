"""Streaming output helpers for the CLI REPL (PRD-003)."""

from __future__ import annotations

from collections.abc import Callable

from cursor_agent.cli.rich_display import RichDisplay
from cursor_agent.sdk_facade import StreamCallbacks


def build_stream_callbacks(writer: Callable[[str], None]) -> StreamCallbacks:
    """Build ``StreamCallbacks`` that emit assistant text deltas via ``writer``.

    Each delta is written individually (not accumulated). Tool lifecycle events
    are intentionally omitted so PRD-003 text-only streaming stays unchanged.

    Example:
        callbacks = build_stream_callbacks(print)
    """

    async def on_assistant_text(delta: str) -> None:
        writer(delta)

    return StreamCallbacks(on_assistant_text=on_assistant_text)


def build_display_stream_callbacks(display: RichDisplay) -> StreamCallbacks:
    """Build ``StreamCallbacks`` that forward streaming events to a display adapter.

    Assistant deltas route to the display ``stream_writer``; tool lifecycle events
    emit line-oriented badges on the display ``status_writer`` without rendering
    raw tool arguments (PRD-004 FR-8).

    Example:
        display = RichDisplay(stream_writer=print, status_writer=print)
        callbacks = build_display_stream_callbacks(display)
    """
    return display.build_stream_callbacks()
