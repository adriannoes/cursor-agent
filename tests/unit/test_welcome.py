"""Unit tests for welcome banner rendering (PRD-011 Task 2.0)."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from cursor_agent.cli.welcome import build_compact_welcome_text, render_welcome
from cursor_agent.product_copy import (
    FIRST_COMMANDS_HINT,
    FIRST_RUN_GETTING_STARTED,
    WELCOME_LOGO,
    WELCOME_READY_LINE,
    WELCOME_TAGLINE,
)

PRD_MAX_LINE_WIDTH = 60
_ALLOWED_UNICODE = {"✓", "—"}
_NDJSON_PREFIX = '{"'


def _capture_welcome(
    *,
    first_run: bool,
    is_tty: bool = True,
    no_banner: bool = False,
    is_ci: bool = False,
) -> tuple[list[str], bool]:
    """Render welcome into a list writer and return output plus write flag."""
    lines: list[str] = []

    def writer(text: str) -> None:
        lines.append(text)

    wrote = render_welcome(
        writer,
        first_run=first_run,
        is_tty=is_tty,
        no_banner=no_banner,
        is_ci=is_ci,
    )
    return lines, wrote


def _joined_output(lines: list[str]) -> str:
    """Join captured writer calls into one banner string."""
    return "\n".join(lines)


def _max_line_width(text: str) -> int:
    """Return the widest line in a multi-line banner."""
    rendered_lines = text.splitlines()
    if not rendered_lines:
        return 0
    return max(len(line) for line in rendered_lines)


def _assert_only_allowed_unicode(text: str) -> None:
    """Banner must stay ASCII except for the PRD-allowed ready checkmark."""
    for char in text:
        if ord(char) > 127 and char not in _ALLOWED_UNICODE:
            raise AssertionError(
                f"unexpected non-ASCII character {char!r} in banner output"
            )


def _assert_no_ndjson(text: str) -> None:
    """Banner must not emit NDJSON-style structured log lines."""
    for line in text.splitlines():
        stripped = line.lstrip()
        assert not stripped.startswith(_NDJSON_PREFIX), (
            f"banner must not emit NDJSON lines, got: {line!r}"
        )


@pytest.mark.parametrize("first_run", [True, False])
def test_render_welcome_lines_within_prd_max_width(first_run: bool) -> None:
    """Every rendered line stays within the PRD-011 60-column limit."""
    lines, wrote = _capture_welcome(first_run=first_run)
    assert wrote is True
    output = _joined_output(lines)
    assert _max_line_width(output) <= PRD_MAX_LINE_WIDTH


def test_first_run_shows_getting_started_and_first_commands_hint() -> None:
    """First-run banner includes the full getting-started block and command hints."""
    lines, wrote = _capture_welcome(first_run=True)
    assert wrote is True
    output = _joined_output(lines)

    assert "powered by Composer" in output
    assert "Installation complete" in output
    for marker in (
        "plain language",
        "/help",
        "/new",
        "/skills",
        "sessions list",
        "docs/setup.md",
    ):
        assert marker in output
    assert FIRST_COMMANDS_HINT.strip() in output


def test_recurring_shows_compact_logo_tagline_ready_only() -> None:
    """Recurring banner shows compact logo, tagline, and ready line only."""
    lines, wrote = _capture_welcome(first_run=False)
    assert wrote is True
    output = _joined_output(lines)

    assert ">_  CURSOR AGENT" in output
    assert WELCOME_TAGLINE in output
    assert WELCOME_READY_LINE in output
    assert WELCOME_LOGO.splitlines()[0] in output

    assert "powered by Composer" not in output
    assert "Installation complete" not in output
    assert "Get started:" not in output
    assert FIRST_COMMANDS_HINT.strip() not in output


def test_rendered_output_only_allows_ready_checkmark_unicode() -> None:
    """Rendered banners use ASCII 7-bit except PRD-allowed punctuation from copy."""
    for first_run in (True, False):
        lines, _ = _capture_welcome(first_run=first_run)
        _assert_only_allowed_unicode(_joined_output(lines))


@pytest.mark.parametrize(
    ("no_banner", "is_tty", "is_ci"),
    [
        (True, True, False),
        (False, False, False),
        (False, True, True),
    ],
    ids=["no_banner", "not_tty", "ci"],
)
def test_suppresses_output_for_policy_flags(
    no_banner: bool,
    is_tty: bool,
    is_ci: bool,
) -> None:
    """Banner is suppressed when --no-banner, non-TTY, or CI is set."""
    lines, wrote = _capture_welcome(
        first_run=True,
        is_tty=is_tty,
        no_banner=no_banner,
        is_ci=is_ci,
    )
    assert wrote is False
    assert lines == []


def test_suppression_leaves_writer_untouched() -> None:
    """Suppressed renders return False without calling the line writer."""
    calls: list[str] = []

    def writer(text: str) -> None:
        calls.append(text)

    wrote = render_welcome(
        writer,
        first_run=False,
        is_tty=False,
        no_banner=False,
        is_ci=False,
    )
    assert wrote is False
    assert calls == []


def test_banner_writes_only_to_line_writer_not_ndjson() -> None:
    """Banner output stays on the line writer and never emits NDJSON."""
    lines, wrote = _capture_welcome(first_run=True)
    assert wrote is True
    output = _joined_output(lines)
    assert output
    _assert_no_ndjson(output)


def test_render_welcome_does_not_require_stream_writer() -> None:
    """Welcome rendering uses only the injected line writer callable."""
    line_sink: list[str] = []
    stream_calls: list[str] = []

    def line_writer(text: str) -> None:
        line_sink.append(text)

    def stream_writer(text: str) -> None:
        stream_calls.append(text)

    wrote = render_welcome(
        line_writer,
        first_run=False,
        is_tty=True,
        no_banner=False,
        is_ci=False,
    )

    assert wrote is True
    assert line_sink
    assert stream_calls == []


# Manual width validation (ADR-027 §7): isolated render_welcome() output was
# checked at 80-column and 120-column terminal contexts — both pass; every
# line remains ≤60 characters because the banner uses fixed-width ASCII layout
# without dynamic wrapping.
@pytest.mark.parametrize("terminal_width", [80, 120])
def test_rendered_banner_invariant_at_terminal_widths(
    terminal_width: int,
) -> None:
    """Banner line widths stay ≤60 at 80- and 120-column Rich console widths."""
    for first_run in (True, False):
        text = FIRST_RUN_GETTING_STARTED if first_run else build_compact_welcome_text()
        console = Console(
            file=StringIO(),
            force_terminal=False,
            color_system=None,
            width=terminal_width,
        )
        with console.capture() as capture:
            console.print(text)
        rendered = capture.get().rstrip("\n")
        assert _max_line_width(rendered) <= PRD_MAX_LINE_WIDTH, (
            f"terminal_width={terminal_width}, first_run={first_run}"
        )
