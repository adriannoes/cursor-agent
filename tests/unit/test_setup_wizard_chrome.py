"""Unit tests for setup wizard chrome formatters (v1.1.0 Wave G2 / Tasks 1.8 + 3.0a).

Covers glyph constants and pure string formatters in
``cursor_agent.cli.setup_wizard_chrome`` — no TTY or real I/O.
"""

from __future__ import annotations

from cursor_agent.cli.setup_wizard_chrome import (
    GLYPH_PROMPT,
    GLYPH_RADIO_OFF,
    GLYPH_RADIO_ON,
    GLYPH_STEP,
    GLYPH_SUCCESS,
    GLYPH_SUMMARY,
    GLYPH_TRUNK,
    format_radio_option,
    format_step,
    format_summary,
)


def test_glyph_constants_match_canonical_ux_contract() -> None:
    """Glyph constants match the D10–D11 wizard chrome vocabulary."""
    assert GLYPH_STEP == "◆"
    assert GLYPH_TRUNK == "│"
    assert GLYPH_PROMPT == "└"
    assert GLYPH_SUMMARY == "◇"
    assert GLYPH_RADIO_ON == "●"
    assert GLYPH_RADIO_OFF == "○"
    assert GLYPH_SUCCESS == "✓"


def test_format_step_emits_diamond_trunk_and_prompt_glyphs() -> None:
    """format_step lays out title (◆), body (│), blank line, then prompt (└)."""
    rendered = format_step(
        "Choose a model",
        ["Grok is recommended.", "Composer is available."],
        "[1 / 2 / id]",
    )
    lines = rendered.splitlines()
    # Exact two-space gap after glyphs (approved mock); single-space would still
    # pass startswith(f"{GLYPH} "), so lock the full prefix.
    assert lines[0] == f"{GLYPH_STEP}  Choose a model"
    assert lines[1] == f"{GLYPH_TRUNK}  Grok is recommended."
    assert lines[2] == f"{GLYPH_TRUNK}  Composer is available."
    assert lines[3] == ""
    assert lines[4] == f"{GLYPH_PROMPT}  [1 / 2 / id]"


def test_format_step_inserts_blank_line_before_prompt_when_body_present() -> None:
    """Breathing room: blank line between │ body and └ prompt when body exists."""
    rendered = format_step("Workspace", ["Path under home."], "Enter path:")
    lines = rendered.splitlines()
    assert lines[0].startswith(f"{GLYPH_STEP} ")
    assert lines[1].startswith(f"{GLYPH_TRUNK} ")
    assert lines[2] == ""
    assert lines[3].startswith(f"{GLYPH_PROMPT} ")


def test_format_step_allows_empty_prompt_for_intro_blocks() -> None:
    """Empty prompt yields title + body only (intro / guidance without input)."""
    rendered = format_step(
        "Welcome",
        ["This guided setup writes ~/.cursor-agent/config.yaml."],
        "",
    )
    lines = rendered.splitlines()
    assert lines[0].startswith(f"{GLYPH_STEP} ")
    assert "Welcome" in lines[0]
    assert lines[1].startswith(f"{GLYPH_TRUNK} ")
    assert GLYPH_PROMPT not in rendered


def test_format_step_with_empty_body_still_emits_title_and_prompt() -> None:
    """Empty body_lines still renders ◆ title and └ prompt without trunk rows."""
    rendered = format_step("API key", [], "Paste key:")
    lines = rendered.splitlines()
    assert lines[0].startswith(f"{GLYPH_STEP} ")
    assert "API key" in lines[0]
    assert not any(line.startswith(f"{GLYPH_TRUNK} ") for line in lines)
    assert lines[-1].startswith(f"{GLYPH_PROMPT} ")
    assert "Paste key:" in lines[-1]


def test_format_radio_option_selected_uses_filled_bullet() -> None:
    """Selected radio option uses ● and two-space separators for index/label/id."""
    line = format_radio_option(1, "Grok 4.5 (recommended)", "grok-4.5", selected=True)
    assert line == f"{GLYPH_RADIO_ON}  1  Grok 4.5 (recommended)  grok-4.5"
    assert GLYPH_RADIO_OFF not in line


def test_format_radio_option_unselected_uses_hollow_bullet() -> None:
    """Unselected radio option uses ○ and two-space separators for index/label/id."""
    line = format_radio_option(2, "Composer 2.5", "composer-2.5", selected=False)
    assert line == f"{GLYPH_RADIO_OFF}  2  Composer 2.5  composer-2.5"
    assert GLYPH_RADIO_ON not in line


def test_format_summary_uses_open_diamond_and_trunk_rows() -> None:
    """format_summary header uses ◇; each row sits under │ with two-space gap."""
    rendered = format_summary(
        [
            ("Model", "grok-4.5"),
            ("Tool profile", "(default: coding)"),
        ]
    )
    lines = rendered.splitlines()
    assert lines[0] == f"{GLYPH_SUMMARY}  Summary"
    assert lines[1] == f"{GLYPH_TRUNK}  Model: grok-4.5"
    assert lines[2] == f"{GLYPH_TRUNK}  Tool profile: (default: coding)"


def test_formatters_return_plain_strings_without_tty_dependency() -> None:
    """Formatters are pure: str in, str out — no interactive I/O side effects."""
    step = format_step("Title", ["Body"], "Prompt?")
    radio = format_radio_option(1, "Label", "id", selected=True)
    summary = format_summary([("Key", "Value")])
    assert isinstance(step, str)
    assert isinstance(radio, str)
    assert isinstance(summary, str)
    assert step.strip() != ""
    assert radio.strip() != ""
    assert summary.strip() != ""
