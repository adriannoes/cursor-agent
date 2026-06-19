"""Welcome banner rendering for default interactive CLI launches (PRD-011)."""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO

from rich.console import Console

from cursor_agent.product_copy import (
    FIRST_RUN_GETTING_STARTED,
    WELCOME_LOGO,
    WELCOME_READY_LINE,
    WELCOME_TAGLINE,
)

_BANNER_INNER_WIDTH = 58


def build_compact_welcome_text() -> str:
    """Assemble the recurring compact welcome banner from product copy.

    Example:
        >>> "CURSOR AGENT" in build_compact_welcome_text()
        True
    """
    border, logo_line, _bottom_border = WELCOME_LOGO.splitlines()
    return "\n".join(
        [
            border,
            logo_line,
            "",
            WELCOME_TAGLINE.center(_BANNER_INNER_WIDTH),
            "",
            WELCOME_READY_LINE.center(_BANNER_INNER_WIDTH),
            border,
        ]
    )


def _should_suppress_welcome(*, is_tty: bool, no_banner: bool, is_ci: bool) -> bool:
    """Return True when ADR-027 suppression policy blocks banner output."""
    return no_banner or not is_tty or is_ci


def _capture_rich_text(text: str) -> str:
    """Render plain banner text through Rich and return captured stdout."""
    console = Console(
        file=StringIO(),
        force_terminal=False,
        color_system=None,
    )
    with console.capture() as capture:
        console.print(text)
    return capture.get().rstrip("\n")


def render_welcome(
    writer: Callable[[str], None],
    *,
    first_run: bool,
    is_tty: bool,
    no_banner: bool,
    is_ci: bool,
) -> bool:
    """Render the welcome banner to the line writer when policy allows.

    Returns whether banner text was written. Suppressed when ``no_banner`` is
    set, stdout is not a TTY, or ``CI`` is a truthy env value (ADR-027 §6).

    Example:
        >>> lines: list[str] = []
        >>> render_welcome(lines.append, first_run=False, is_tty=True,
        ...                no_banner=False, is_ci=False)
        True
    """
    if _should_suppress_welcome(is_tty=is_tty, no_banner=no_banner, is_ci=is_ci):
        return False

    banner_text = (
        FIRST_RUN_GETTING_STARTED if first_run else build_compact_welcome_text()
    )
    writer(_capture_rich_text(banner_text))
    return True
