"""Unit tests for CLI thinking indicator lifecycle (PRD-018 / Q8).

Covers ``ThinkingDisplay`` / ``RichDisplay`` start/stop/suppress/elapsed
refresh and callback-clear (FR-1–FR-3).
"""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO

import pytest
from rich.console import Console

import cursor_agent.cli.rich_display as rich_display_module
from cursor_agent.cli.rich_display import RichDisplay, ThinkingDisplay

# LOCKED (PRD-018 Q2): unicode ellipsis U+2026, not ASCII "...".
_THINKING_ELLIPSIS = "\u2026"
_THINKING_LABEL_PREFIX = f"Thinking{_THINKING_ELLIPSIS} · "


def _thinking_label(elapsed_seconds: int) -> str:
    """Return the LOCKED thinking status copy for ``elapsed_seconds``."""
    return f"{_THINKING_LABEL_PREFIX}{elapsed_seconds}s"


def _make_thinking_display(
    *,
    is_tty: bool = True,
    is_ci: bool = False,
    elapsed_seconds: Callable[[], int] | None = None,
    stream_writer: Callable[[str], None] | None = None,
    status_writer: Callable[[str], None] | None = None,
    console_file: StringIO | None = None,
    force_terminal: bool = True,
) -> tuple[RichDisplay, StringIO, list[str], list[str]]:
    """Build a ``RichDisplay`` with injectable TTY/CI/clock and StringIO console.

    Disables the production auto-ticker so elapsed refresh is driven only via
    ``refresh_thinking_label`` (no real sleeps / races in unit tests).
    """
    stream_sink: list[str] = []
    status_sink: list[str] = []
    captured = console_file if console_file is not None else StringIO()
    fake_console = Console(
        file=captured,
        force_terminal=force_terminal,
        color_system=None,
    )
    clock = elapsed_seconds if elapsed_seconds is not None else (lambda: 0)
    display = RichDisplay(
        stream_writer=stream_writer
        if stream_writer is not None
        else stream_sink.append,
        status_writer=status_writer
        if status_writer is not None
        else status_sink.append,
        console=fake_console,
        is_tty=is_tty,
        is_ci=is_ci,
        elapsed_seconds=clock,
        auto_refresh_thinking=False,
    )
    return display, captured, stream_sink, status_sink


def test_rich_display_satisfies_thinking_display_protocol() -> None:
    """``RichDisplay`` is a ``ThinkingDisplay`` (start/stop surface)."""
    assert ThinkingDisplay is rich_display_module.ThinkingDisplay
    display, _console_file, _stream, _status = _make_thinking_display()
    assert isinstance(display, ThinkingDisplay)
    assert callable(display.start_thinking)
    assert callable(display.stop_thinking)


def test_start_thinking_on_tty_shows_live_status() -> None:
    """TTY + not CI: ``start_thinking`` emits a live status frame with the label."""
    display, console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
        elapsed_seconds=lambda: 0,
        # CI regression: force_terminal + StringIO must still show the label
        # via CR fallback (Rich Status alone only emits cursor-hide ANSI).
        force_terminal=True,
    )

    display.start_thinking()

    output = console_file.getvalue()
    assert _thinking_label(0) in output
    assert "\r" in output or "Thinking" in output


@pytest.mark.parametrize(
    ("is_tty", "is_ci"),
    [
        (False, False),
        (True, True),
        (False, True),
    ],
)
def test_start_thinking_suppressed_when_non_tty_or_ci(
    is_tty: bool,
    is_ci: bool,
) -> None:
    """Non-TTY or CI: ``start_thinking`` is a no-op (no Status/Live, no ``\\r``)."""
    display, console_file, _stream, _status = _make_thinking_display(
        is_tty=is_tty,
        is_ci=is_ci,
        elapsed_seconds=lambda: 3,
        force_terminal=True,
    )

    display.start_thinking()

    output = console_file.getvalue()
    assert "Thinking" not in output
    assert "\r" not in output
    assert _THINKING_ELLIPSIS not in output


def test_thinking_label_uses_unicode_ellipsis_and_injectable_elapsed() -> None:
    """Copy LOCKED: ``Thinking… · {n}s`` (U+2026) via injectable elapsed provider."""
    display, console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
        elapsed_seconds=lambda: 7,
    )

    display.start_thinking()

    assert _thinking_label(7) in console_file.getvalue()
    assert "Thinking..." not in console_file.getvalue()
    assert _THINKING_ELLIPSIS in console_file.getvalue()


def test_thinking_elapsed_updates_after_single_start_without_restart() -> None:
    """FR-1 regression: elapsed refreshes without a second ``start_thinking``."""
    elapsed = {"seconds": 0}

    def elapsed_seconds() -> int:
        return elapsed["seconds"]

    display, console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
        elapsed_seconds=elapsed_seconds,
    )

    display.start_thinking()
    assert _thinking_label(0) in console_file.getvalue()

    elapsed["seconds"] = 15
    display.refresh_thinking_label()

    assert _thinking_label(15) in console_file.getvalue()
    assert _THINKING_ELLIPSIS in console_file.getvalue()
    assert "Thinking..." not in console_file.getvalue()


@pytest.mark.asyncio
async def test_on_assistant_text_stops_thinking_before_writing_delta() -> None:
    """First ``on_assistant_text`` calls ``stop_thinking`` before the stream write."""
    events: list[str] = []
    stream_sink: list[str] = []

    def stream_writer(delta: str) -> None:
        events.append(f"stream:{delta}")
        stream_sink.append(delta)

    display, console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
        stream_writer=stream_writer,
        elapsed_seconds=lambda: 2,
    )
    original_stop = display.stop_thinking

    def traced_stop() -> None:
        events.append("stop_thinking")
        original_stop()

    display.stop_thinking = traced_stop  # type: ignore[method-assign]

    display.start_thinking()
    assert _thinking_label(2) in console_file.getvalue()

    callbacks = display.build_stream_callbacks()
    assert callbacks.on_assistant_text is not None
    await callbacks.on_assistant_text("hel")

    assert events == ["stop_thinking", "stream:hel"]
    assert stream_sink == ["hel"]
    assert "Thinking" not in console_file.getvalue() or "\r" in console_file.getvalue()


@pytest.mark.asyncio
async def test_on_tool_start_stops_thinking_before_badge() -> None:
    """First ``on_tool_start`` calls ``stop_thinking`` before the tool badge write."""
    events: list[str] = []
    status_sink: list[str] = []

    def status_writer(line: str) -> None:
        events.append("badge")
        status_sink.append(line)

    display, _console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
        status_writer=status_writer,
        elapsed_seconds=lambda: 1,
    )
    original_stop = display.stop_thinking

    def traced_stop() -> None:
        events.append("stop_thinking")
        original_stop()

    display.stop_thinking = traced_stop  # type: ignore[method-assign]

    display.start_thinking()
    callbacks = display.build_stream_callbacks()
    assert callbacks.on_tool_start is not None
    await callbacks.on_tool_start("grep", {"pattern": "x"})

    assert events == ["stop_thinking", "badge"]
    assert len(status_sink) == 1
    assert "grep" in status_sink[0]
    assert "running" in status_sink[0].lower()


def test_stop_thinking_is_idempotent() -> None:
    """``stop_thinking`` is safe to call twice (and with no prior start)."""
    display, _console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
    )

    display.stop_thinking()
    display.start_thinking()
    display.stop_thinking()
    display.stop_thinking()


def test_stop_thinking_clears_live_status() -> None:
    """Explicit ``stop_thinking`` clears the live thinking line after start."""
    display, console_file, _stream, _status = _make_thinking_display(
        is_tty=True,
        is_ci=False,
        elapsed_seconds=lambda: 4,
    )

    display.start_thinking()
    assert _thinking_label(4) in console_file.getvalue()

    display.stop_thinking()
    # Cleared status must not leave an active Thinking label as the live line.
    # Rich Status stop typically rewrites with spaces/CR; label must not linger alone.
    final = console_file.getvalue()
    assert not final.rstrip().endswith(_thinking_label(4))
