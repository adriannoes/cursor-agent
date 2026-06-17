"""Rich-backed display adapter for CLI streaming (PRD-004)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.text import Text

from cursor_agent.sdk_facade import StreamCallbacks


def _format_tool_badge(tool_name: str, state: str) -> Text:
    """Return a Rich text badge that omits tool args and payloads."""
    state_style = "green" if state == "done" else "yellow"
    return Text.assemble(
        ("[tool]", "cyan"),
        f" {tool_name} ",
        (state, state_style),
    )


class RichDisplay:
    """Display boundary for assistant streaming and tool badges.

    Keeps Rich ``Console`` usage inside this module so ``repl_session.py`` does not
    import Rich directly. ``stream_writer`` receives inline assistant deltas;
    ``status_writer`` receives line-oriented status such as tool badge updates
    (PRD-003 two-sink contract).

    Example:
        display = RichDisplay(stream_writer=print, status_writer=print)
        callbacks = display.build_stream_callbacks()
    """

    def __init__(
        self,
        *,
        stream_writer: Callable[[str], None],
        status_writer: Callable[[str], None],
        console: Console | None = None,
    ) -> None:
        self._stream_writer = stream_writer
        self._status_writer = status_writer
        self._console = console if console is not None else Console()
        self._last_tool_badge: tuple[str, str] | None = None

    def build_stream_callbacks(self) -> StreamCallbacks:
        """Build SDK stream callbacks wired to this display boundary."""
        display = self

        async def on_assistant_text(delta: str) -> None:
            display._stream_writer(delta)

        async def on_tool_start(tool_name: str, _args: dict[str, Any]) -> None:
            display._write_tool_badge(tool_name, "running")

        async def on_tool_end(tool_name: str, _payload: dict[str, Any]) -> None:
            display._write_tool_badge(tool_name, "done")

        return StreamCallbacks(
            on_assistant_text=on_assistant_text,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
        )

    def _write_tool_badge(self, tool_name: str, state: str) -> None:
        """Render a Rich badge and forward the captured line to the status sink."""
        badge_key = (tool_name, state)
        if self._last_tool_badge == badge_key:
            return
        self._last_tool_badge = badge_key
        with self._console.capture() as capture:
            self._console.print(_format_tool_badge(tool_name, state), end="")
        self._status_writer(capture.get())
