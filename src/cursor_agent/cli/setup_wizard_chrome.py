"""Pure string formatters for interactive setup wizard chrome (v1.1.0 Wave G2).

Glyph vocabulary matches the locked Proposal B mock (D10–D11). No TTY, input,
or print — callers compose these strings and own I/O.
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


def format_step(title: str, body_lines: Sequence[str], prompt: str) -> str:
    """Render a wizard step: ◆ title, │ body, optional blank line, └ prompt.

    Empty ``prompt`` omits the leaf line (intro / guidance blocks). A blank
    line before the prompt is inserted only when ``body_lines`` is non-empty.

    Example:
        >>> "Choose" in format_step("Choose", ["Hint."], "Enter:")
        True
    """
    lines: list[str] = [f"{GLYPH_STEP}{_GLYPH_GAP}{title}"]
    for body_line in body_lines:
        lines.append(f"{GLYPH_TRUNK}{_GLYPH_GAP}{body_line}")
    if prompt:
        if body_lines:
            lines.append("")
        lines.append(f"{GLYPH_PROMPT}{_GLYPH_GAP}{prompt}")
    return "\n".join(lines)


def format_radio_option(
    index: int,
    label: str,
    option_id: str,
    *,
    selected: bool,
) -> str:
    """Render one radio choice line with ●/○, index, label, and option id.

    Example:
        >>> "grok-4.5" in format_radio_option(1, "Grok", "grok-4.5", selected=True)
        True
    """
    glyph = GLYPH_RADIO_ON if selected else GLYPH_RADIO_OFF
    return f"{glyph}{_GLYPH_GAP}{index}{_GLYPH_GAP}{label}{_GLYPH_GAP}{option_id}"


def format_summary(rows: Sequence[tuple[str, str]]) -> str:
    """Render a ◇ summary header with │ ``key: value`` trunk rows.

    Example:
        >>> "Model" in format_summary([("Model", "grok-4.5")])
        True
    """
    lines: list[str] = [f"{GLYPH_SUMMARY}{_GLYPH_GAP}Summary"]
    for key, value in rows:
        lines.append(f"{GLYPH_TRUNK}{_GLYPH_GAP}{key}: {value}")
    return "\n".join(lines)
