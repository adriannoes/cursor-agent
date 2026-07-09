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
    format_success,
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
    assert lines[0] == f"{GLYPH_STEP}  Workspace"
    assert lines[1] == f"{GLYPH_TRUNK}  Path under home."
    assert lines[2] == ""
    assert lines[3] == f"{GLYPH_PROMPT}  Enter path:"


def test_format_step_allows_empty_prompt_for_intro_blocks() -> None:
    """Empty prompt yields title + body only (intro / guidance without input)."""
    rendered = format_step(
        "Welcome",
        ["This guided setup writes ~/.cursor-agent/config.yaml."],
        "",
    )
    lines = rendered.splitlines()
    assert lines[0] == f"{GLYPH_STEP}  Welcome"
    assert lines[1] == (
        f"{GLYPH_TRUNK}  This guided setup writes ~/.cursor-agent/config.yaml."
    )
    assert GLYPH_PROMPT not in rendered


def test_format_step_with_empty_body_still_emits_title_and_prompt() -> None:
    """Empty body_lines still renders ◆ title and └ prompt without trunk rows."""
    rendered = format_step("API key", [], "Paste key:")
    lines = rendered.splitlines()
    assert lines[0] == f"{GLYPH_STEP}  API key"
    assert not any(line.startswith(f"{GLYPH_TRUNK}  ") for line in lines)
    assert lines[-1] == f"{GLYPH_PROMPT}  Paste key:"


def test_format_step_whitespace_only_prompt_omits_leaf() -> None:
    """Whitespace-only prompt is treated as empty (no └ line)."""
    rendered = format_step("Intro", ["Guidance."], "   ")
    lines = rendered.splitlines()
    assert lines[0] == f"{GLYPH_STEP}  Intro"
    assert lines[1] == f"{GLYPH_TRUNK}  Guidance."
    assert GLYPH_PROMPT not in rendered


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


def test_format_summary_accepts_explicit_title() -> None:
    """Callers can override the short summary title (avoids product_copy drift)."""
    rendered = format_summary([("workspace", "/tmp/demo")], title="Review")
    lines = rendered.splitlines()
    assert lines[0] == f"{GLYPH_SUMMARY}  Review"
    assert lines[1] == f"{GLYPH_TRUNK}  workspace: /tmp/demo"


def test_format_summary_with_empty_rows_emits_header_only() -> None:
    """Empty rows yield the ◇ header line alone."""
    rendered = format_summary([])
    assert rendered == f"{GLYPH_SUMMARY}  Summary"
    assert GLYPH_TRUNK not in rendered


def test_format_success_emits_checkmark_and_optional_next_hint() -> None:
    """format_success uses ✓ and optional │ next-hint (Step 8 mock)."""
    with_hint = format_success(
        "Configuration written.",
        "Next: cursor-agent setup check",
    )
    assert with_hint.splitlines() == [
        f"{GLYPH_SUCCESS}  Configuration written.",
        f"{GLYPH_TRUNK}  Next: cursor-agent setup check",
    ]
    header_only = format_success("Configuration written.")
    assert header_only == f"{GLYPH_SUCCESS}  Configuration written."


def test_formatters_return_exact_layout_strings_without_tty_dependency() -> None:
    """Formatters are pure: exact layout strings, no interactive I/O side effects."""
    step = format_step("Title", ["Body"], "Prompt?")
    radio = format_radio_option(1, "Label", "id", selected=True)
    summary = format_summary([("Key", "Value")])
    success = format_success("Done.", "Next: check")
    assert step == (
        f"{GLYPH_STEP}  Title\n{GLYPH_TRUNK}  Body\n\n{GLYPH_PROMPT}  Prompt?"
    )
    assert radio == f"{GLYPH_RADIO_ON}  1  Label  id"
    assert summary == f"{GLYPH_SUMMARY}  Summary\n{GLYPH_TRUNK}  Key: Value"
    assert success == f"{GLYPH_SUCCESS}  Done.\n{GLYPH_TRUNK}  Next: check"
