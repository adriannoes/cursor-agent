"""Pure string formatters for interactive setup wizard chrome (v1.1.0 Wave G2).

Glyph vocabulary matches the locked Proposal B mock (D10–D11). No TTY, input,
or print — callers compose these strings and own I/O.

Chrome owns short step titles (e.g. summary default ``\"Summary\"`` via
``format_summary(..., title=...)``). ``product_copy.SETUP_*`` supplies English
copy; G3 should pass titles into these helpers rather than duplicating glyphs
in copy strings. Non-interactive ``setup apply`` stays terse (no chrome).
"""

from __future__ import annotations

from collections.abc import Sequence

GLYPH_STEP: str = "◆"
GLYPH_TRUNK: str = "│"
GLYPH_PROMPT: str = "└"
GLYPH_SUMMARY: str = "◇"
GLYPH_RADIO_ON: str = "●"
GLYPH_RADIO_OFF: str = "○"
GLYPH_SUCCESS: str = "✓"

# Two spaces after glyphs match the approved onboard mock (readable TTY scan).
_GLYPH_GAP: str = "  "
_DEFAULT_SUMMARY_TITLE: str = "Summary"


def _format_trunk_line(body_line: str) -> str:
    """Render an empty body row as a bare trunk without trailing spaces."""
    if not body_line.strip():
        return GLYPH_TRUNK
    return f"{GLYPH_TRUNK}{_GLYPH_GAP}{body_line}"


def format_prompt_leaf(prompt: str) -> str:
    """Render a └ prompt leaf with the shared glyph spacing.

    Example:
        >>> format_prompt_leaf("Continue?")
        '└  Continue?'
    """
    return f"{GLYPH_PROMPT}{_GLYPH_GAP}{prompt.strip()}"


def format_step(title: str, body_lines: Sequence[str], prompt: str) -> str:
    """Render a wizard step: ◆ title, │ body/breathing room, then └ prompt.

    Empty or whitespace-only ``prompt`` omits the leaf line (intro / guidance).
    A visible bare trunk before the prompt is inserted when ``body_lines`` is
    non-empty. Empty body rows also become bare trunks without trailing spaces.

    Example:
        >>> "Choose" in format_step("Choose", ["Hint."], "Enter:")
        True
    """
    lines: list[str] = [f"{GLYPH_STEP}{_GLYPH_GAP}{title}"]
    for body_line in body_lines:
        lines.append(_format_trunk_line(body_line))
    prompt_text = prompt.strip()
    if prompt_text:
        if body_lines:
            lines.append(GLYPH_TRUNK)
        lines.append(format_prompt_leaf(prompt_text))
    return "\n".join(lines)


def format_radio_option(
    index: int,
    label: str,
    option_detail: str,
    *,
    selected: bool,
    label_width: int | None = None,
) -> str:
    """Render one radio choice with single-space glyph/index and optional alignment.

    Example:
        >>> "grok-4.5" in format_radio_option(1, "Grok", "grok-4.5", selected=True)
        True
    """
    glyph = GLYPH_RADIO_ON if selected else GLYPH_RADIO_OFF
    label_column = (
        f"{label:<{label_width}}" if label_width is not None else f"{label}{_GLYPH_GAP}"
    )
    return f"{glyph} {index}{_GLYPH_GAP}{label_column}{option_detail}"


def format_summary(
    rows: Sequence[tuple[str, str]],
    *,
    title: str = _DEFAULT_SUMMARY_TITLE,
) -> str:
    """Render a ◇ summary header with │ ``key: value`` trunk rows.

    ``title`` defaults to the short chrome header (``Summary``). Callers that
    still hold longer ``SETUP_SUMMARY_HEADER`` copy should pass an explicit
    short title rather than baking glyphs into product_copy.

    Empty ``rows`` yields the header line only.

    Example:
        >>> "Model" in format_summary([("Model", "grok-4.5")])
        True
    """
    lines: list[str] = [f"{GLYPH_SUMMARY}{_GLYPH_GAP}{title}"]
    for key, value in rows:
        lines.append(f"{GLYPH_TRUNK}{_GLYPH_GAP}{key}: {value}")
    return "\n".join(lines)


def format_success(
    message: str,
    next_hint: str = "",
    *,
    detail_lines: Sequence[str] = (),
) -> str:
    """Render Step 8 success with optional detail and next-hint trunks.

    Interactive wizard only — do not use on non-interactive ``setup apply``.

    Example:
        >>> GLYPH_SUCCESS in format_success("Configuration written.")
        True
    """
    lines: list[str] = [f"{GLYPH_SUCCESS}{_GLYPH_GAP}{message}"]
    for detail_line in detail_lines:
        if detail_line.strip():
            lines.append(_format_trunk_line(detail_line))
    hint_text = next_hint.strip()
    if hint_text:
        lines.append(_format_trunk_line(hint_text))
    return "\n".join(lines)
