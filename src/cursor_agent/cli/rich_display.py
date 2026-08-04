"""Rich-backed display adapter for CLI streaming (PRD-004 / PRD-018)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from rich.console import Console
from rich.status import Status
from rich.table import Table
from rich.text import Text

from cursor_agent.memory import (
    TOTAL_MEMORY_BUDGET_BYTES,
    EffectiveMemoryPayload,
    EffectiveMemorySection,
)
from cursor_agent.sdk_facade import StreamCallbacks
from cursor_agent.skills.discovery import SkillEntry

DISPLAY_MEMORY_ROOT = "~/.cursor-agent/"
_EMPTY_CONTENT_LABEL = "(empty)"
# LOCKED (PRD-018 Q2): unicode ellipsis U+2026, not ASCII "...".
_THINKING_ELLIPSIS = "\u2026"
_THINKING_LABEL_PREFIX = f"Thinking{_THINKING_ELLIPSIS} · "
# FR-1: Live/Status and fallback ticker refresh the elapsed label ≥1/s.
_THINKING_REFRESH_PER_SECOND = 1.0


class _DynamicThinkingLabel:
    """Rich-cast label that re-reads elapsed seconds on each Live frame.

    WHY: a static string frozen at ``start_thinking`` would stay at ``0s``;
    Status/Live must call back into the display clock every refresh.
    """

    def __init__(self, format_label: Callable[[], str]) -> None:
        self._format_label = format_label

    def __rich__(self) -> str:
        """Return the current ``Thinking… · Ns`` copy for this frame."""
        return self._format_label()


@runtime_checkable
class ThinkingDisplay(Protocol):
    """TTY thinking-indicator surface for REPL / slash streaming sends.

    Example:
        display: ThinkingDisplay = RichDisplay(...)
        display.start_thinking()
        try:
            await pool.send(prompt)
        finally:
            display.stop_thinking()
    """

    def start_thinking(self) -> None:
        """Show or refresh the live ``Thinking… · Ns`` status line."""

    def stop_thinking(self) -> None:
        """Clear the thinking indicator; safe to call when inactive."""


def _format_tool_badge(tool_name: str, state: str) -> Text:
    """Return a Rich text badge that omits tool args and payloads."""
    state_style = "green" if state == "done" else "yellow"
    return Text.assemble(
        ("[tool]", "cyan"),
        f" {tool_name} ",
        (state, state_style),
    )


def _format_memory_section_block(
    section: EffectiveMemorySection,
    *,
    missing: bool,
) -> list[str]:
    """Format one memory section for ``/memory show`` output."""
    display_path = f"{DISPLAY_MEMORY_ROOT}{section.filename}"
    status = "missing" if missing else "present"
    lines = [
        f"--- {section.filename} ({display_path}) ---",
        f"Status: {status}",
        f"Quota: {section.budget_bytes} bytes",
        f"Effective: {section.effective_bytes} bytes",
    ]
    if section.truncated:
        lines.append(
            f"Truncated: yes (original {section.original_bytes} bytes, "
            f"kept tail within quota)"
        )
    else:
        lines.append("Truncated: no")
    content = section.effective_text if section.effective_text else _EMPTY_CONTENT_LABEL
    lines.append("Content:")
    lines.append(content)
    return lines


def format_memory_show_output(
    payload: EffectiveMemoryPayload,
    *,
    user_missing: bool,
    memory_missing: bool,
) -> str:
    """Format the effective Memory v1 payload for operator inspection.

    Example:
        >>> from cursor_agent.memory import LocalMemoryStore
        >>> store = LocalMemoryStore(root=Path("/tmp/memory"))
        >>> print(format_memory_show_output(
        ...     store.build_effective_payload(),
        ...     user_missing=True,
        ...     memory_missing=True,
        ... ))
    """
    lines = [
        "Memory effective payload",
        "",
        *_format_memory_section_block(payload.user, missing=user_missing),
        "",
        *_format_memory_section_block(payload.memory, missing=memory_missing),
        "",
        (
            "Total effective: "
            f"{payload.total_effective_bytes} / {TOTAL_MEMORY_BUDGET_BYTES} bytes"
        ),
    ]
    return "\n".join(lines)


def format_cron_jobs_table(rows: Sequence[Mapping[str, str]]) -> str:
    """Format cron job metadata rows as a Rich table for ``cron list``.

    Example:
        >>> print(format_cron_jobs_table([
        ...     {
        ...         "id": "daily-report",
        ...         "schedule": "0 9 * * *",
        ...         "next_run": "2026-06-19 09:00:00 UTC",
        ...         "runtime": "local",
        ...         "telegram_chat_id": "-",
        ...     },
        ... ]))
    """
    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Schedule")
    table.add_column("Next run (UTC)")
    table.add_column("Runtime")
    table.add_column("Telegram chat_id")

    for row in rows:
        table.add_row(
            row["id"],
            row["schedule"],
            row["next_run"],
            row["runtime"],
            row["telegram_chat_id"],
        )

    console = Console()
    with console.capture() as capture:
        console.print(table)
    return capture.get().rstrip()


def format_skills_list_output(skills: list[SkillEntry]) -> str:
    """Format discovered skills for ``/skills`` terminal output.

    Example:
        >>> from cursor_agent.skills.discovery import SkillEntry
        >>> entry = SkillEntry(
        ...     name="canvas",
        ...     description="Canvas workflows",
        ...     source="project",
        ...     path="canvas/SKILL.md",
        ...     content="",
        ... )
        >>> print(format_skills_list_output([entry]))
    """
    if not skills:
        return "No skills discovered in the configured workspace and user paths."

    lines = [f"Skills ({len(skills)}):", ""]
    for skill in skills:
        description = skill.description if skill.description else "(none)"
        lines.extend(
            [
                skill.name,
                f"  Description: {description}",
                f"  Source: {skill.source}",
                f"  Path: {skill.path}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


class RichDisplay:
    """Display boundary for assistant streaming, tool badges, and thinking status.

    Keeps Rich ``Console`` usage inside this module so ``repl_session.py`` does not
    import Rich directly. ``stream_writer`` receives inline assistant deltas;
    ``status_writer`` receives line-oriented status such as tool badge updates
    (PRD-003 two-sink contract). Thinking indicator is TTY-only (PRD-018).

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
        is_tty: bool = True,
        is_ci: bool = False,
        elapsed_seconds: Callable[[], int] | None = None,
        auto_refresh_thinking: bool = True,
    ) -> None:
        self._stream_writer = stream_writer
        self._status_writer = status_writer
        self._console = console if console is not None else Console()
        self._is_tty = is_tty
        self._is_ci = is_ci
        self._elapsed_seconds = (
            elapsed_seconds
            if elapsed_seconds is not None
            else self._wall_clock_elapsed_seconds
        )
        self._auto_refresh_thinking = auto_refresh_thinking
        self._thinking_started_monotonic: float | None = None
        self._thinking_status: Status | None = None
        self._thinking_fallback_active = False
        self._thinking_ticker_stop: threading.Event | None = None
        self._thinking_ticker_thread: threading.Thread | None = None
        self._last_tool_badge: tuple[str, str] | None = None

    def start_thinking(self) -> None:
        """Show or refresh ``Thinking… · Ns``; no-op when non-TTY or CI."""
        if not self._is_tty or self._is_ci:
            return
        if self._thinking_started_monotonic is None:
            self._thinking_started_monotonic = time.monotonic()
        if self._console_supports_live_status():
            self._start_or_ensure_live_thinking_status()
            return
        # WHY: Rich Live/Status skip refresh on dumb terminals and StringIO
        # test consoles; emit CR frames so the locked label is observable.
        self._thinking_fallback_active = True
        self.refresh_thinking_label()
        self._ensure_thinking_ticker()

    def refresh_thinking_label(self) -> None:
        """Re-render the active thinking label from the current elapsed clock.

        Called by the fallback ticker (≥1/s) and by unit tests with an
        injectable clock — avoids real sleeps while proving FR-1 updates.

        Example:
            display.start_thinking()
            # clock advances via injectable elapsed_seconds
            display.refresh_thinking_label()
        """
        if self._thinking_started_monotonic is None:
            return
        if not self._is_tty or self._is_ci:
            return
        label = self._format_thinking_label()
        if self._thinking_status is not None:
            # Live path uses a dynamic renderable; update keeps Spinner text
            # wired if Rich replaced it with a snapshot string.
            self._thinking_status.update(self._make_thinking_label_renderable())
            return
        if self._thinking_fallback_active:
            self._console.file.write(f"\r{label}")
            self._console.file.flush()

    def stop_thinking(self) -> None:
        """Clear the thinking indicator; idempotent when already stopped."""
        self._stop_thinking_ticker()
        if self._thinking_status is not None:
            self._thinking_status.stop()
            self._thinking_status = None
        if self._thinking_fallback_active:
            # ANSI erase-line (not whitespace) so cleared status does not leave
            # the label as the sole trailing content in captured StringIO output.
            self._console.file.write("\r\x1b[2K")
            self._console.file.flush()
            self._thinking_fallback_active = False
        self._thinking_started_monotonic = None

    def build_stream_callbacks(self) -> StreamCallbacks:
        """Build SDK stream callbacks wired to this display boundary."""
        display = self

        async def on_assistant_text(delta: str) -> None:
            display.stop_thinking()
            display._stream_writer(delta)

        async def on_tool_start(tool_name: str, _args: dict[str, Any]) -> None:
            display.stop_thinking()
            display._write_tool_badge(tool_name, "running")

        async def on_tool_end(tool_name: str, _payload: dict[str, Any]) -> None:
            display._write_tool_badge(tool_name, "done")

        return StreamCallbacks(
            on_assistant_text=on_assistant_text,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
        )

    def _wall_clock_elapsed_seconds(self) -> int:
        """Return seconds since the current thinking start (production clock)."""
        started = self._thinking_started_monotonic
        if started is None:
            return 0
        return int(time.monotonic() - started)

    def _format_thinking_label(self) -> str:
        """Return LOCKED thinking copy for the current elapsed seconds."""
        return f"{_THINKING_LABEL_PREFIX}{self._elapsed_seconds()}s"

    def _console_supports_live_status(self) -> bool:
        """Return True when Rich Live/Status will actually refresh on a real TTY.

        WHY: ``force_terminal=True`` with a ``StringIO`` (unit/CI) makes Rich
        report ``is_terminal`` while Status only emits cursor-hide ANSI and
        never writes the label into the capture buffer. Require ``isatty()``.
        """
        if not self._console.is_terminal or self._console.is_dumb_terminal:
            return False
        console_file = self._console.file
        isatty = getattr(console_file, "isatty", None)
        if not callable(isatty):
            return False
        return bool(isatty())

    def _make_thinking_label_renderable(self) -> _DynamicThinkingLabel:
        """Return a Live-frame renderable bound to this display's clock."""
        return _DynamicThinkingLabel(self._format_thinking_label)

    def _start_or_ensure_live_thinking_status(self) -> None:
        """Start Rich Status with a dynamic label, or leave an active one running."""
        if self._thinking_status is not None:
            return
        status = Status(
            self._make_thinking_label_renderable(),
            console=self._console,
            refresh_per_second=_THINKING_REFRESH_PER_SECOND,
        )
        self._thinking_status = status
        status.start()

    def _ensure_thinking_ticker(self) -> None:
        """Start a ≥1/s daemon ticker for dumb-terminal / CR fallback frames."""
        if not self._auto_refresh_thinking:
            return
        if self._thinking_ticker_thread is not None:
            return
        stop_event = threading.Event()
        self._thinking_ticker_stop = stop_event

        def _tick_until_stopped() -> None:
            while not stop_event.wait(_THINKING_REFRESH_PER_SECOND):
                self.refresh_thinking_label()

        thread = threading.Thread(
            target=_tick_until_stopped,
            name="cursor-agent-thinking-ticker",
            daemon=True,
        )
        self._thinking_ticker_thread = thread
        thread.start()

    def _stop_thinking_ticker(self) -> None:
        """Stop the fallback ticker thread if running; safe when inactive."""
        stop_event = self._thinking_ticker_stop
        thread = self._thinking_ticker_thread
        self._thinking_ticker_stop = None
        self._thinking_ticker_thread = None
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _write_tool_badge(self, tool_name: str, state: str) -> None:
        """Render a Rich badge and forward the captured line to the status sink."""
        badge_key = (tool_name, state)
        if self._last_tool_badge == badge_key:
            return
        self._last_tool_badge = badge_key
        with self._console.capture() as capture:
            self._console.print(_format_tool_badge(tool_name, state), end="")
        self._status_writer(capture.get())
