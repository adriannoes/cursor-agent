"""Unit tests for setup wizard chrome formatters (v1.1.0 Wave G2 / Tasks 1.8 + 3.0a).

Covers glyph constants and pure string formatters in
``cursor_agent.cli.setup_wizard_chrome`` — no TTY or real I/O.
"""

from __future__ import annotations

import pytest

from cursor_agent.cli.setup_wizard_chrome import (
    GLYPH_PROMPT,
    GLYPH_RADIO_OFF,
    GLYPH_RADIO_ON,
    GLYPH_STEP,
    GLYPH_SUCCESS,
    GLYPH_SUMMARY,
    GLYPH_TRUNK,
    format_prompt_leaf,
    format_radio_escape_hatch,
    format_radio_option,
    format_step,
    format_success,
    format_summary,
    radio_option_label_width,
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
    """format_step lays out title (◆), body (│), bare trunk, then prompt (└)."""
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
    assert lines[3] == GLYPH_TRUNK
    assert lines[4] == f"{GLYPH_PROMPT}  [1 / 2 / id]"


def test_format_step_inserts_bare_trunk_before_prompt_when_body_present() -> None:
    """Breathing room uses a visible bare │ between body and prompt."""
    rendered = format_step("Workspace", ["Path under home."], "Enter path:")
    lines = rendered.splitlines()
    assert lines[0] == f"{GLYPH_STEP}  Workspace"
    assert lines[1] == f"{GLYPH_TRUNK}  Path under home."
    assert lines[2] == GLYPH_TRUNK
    assert lines[3] == f"{GLYPH_PROMPT}  Enter path:"


def test_format_step_renders_empty_body_separator_without_trailing_spaces() -> None:
    """Empty body rows render as a bare │ without trailing whitespace."""
    rendered = format_step("Model", ["Hint.", "", "● 1  Model"], "Model:")
    lines = rendered.splitlines()
    assert lines[2] == GLYPH_TRUNK
    assert not lines[2].endswith(" ")


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


def test_format_prompt_leaf_owns_prompt_glyph_spacing() -> None:
    """Prompt leaf formatter applies the approved two-space glyph gap."""
    assert format_prompt_leaf("Write configuration? [y / N]:") == (
        f"{GLYPH_PROMPT}  Write configuration? [y / N]:"
    )


def test_format_radio_option_selected_uses_filled_bullet() -> None:
    """Selected radio uses the approved single-space glyph/index style."""
    line = format_radio_option(1, "Grok 4.5 (recommended)", "grok-4.5", selected=True)
    assert line == f"{GLYPH_RADIO_ON} 1  Grok 4.5 (recommended)  grok-4.5"
    assert GLYPH_RADIO_OFF not in line


def test_format_radio_option_unselected_uses_hollow_bullet() -> None:
    """Unselected radio uses ○ and neutral option-detail copy."""
    line = format_radio_option(2, "Composer 2.5", "composer-2.5", selected=False)
    assert line == f"{GLYPH_RADIO_OFF} 2  Composer 2.5  composer-2.5"
    assert GLYPH_RADIO_ON not in line


def test_radio_option_label_width_derives_from_longest_label_plus_gap() -> None:
    """Label column width is longest label length plus trailing detail gap."""
    assert (
        radio_option_label_width(("coding", "messaging", "full"))
        == len("messaging") + 2
    )
    assert (
        radio_option_label_width(("Grok 4.5", "Composer 2.5"))
        == len("Composer 2.5") + 2
    )


def test_radio_option_label_width_rejects_empty_labels() -> None:
    """Empty label sequences raise with received value and expected shape."""
    with pytest.raises(ValueError, match="empty") as exc_info:
        radio_option_label_width(())
    message = str(exc_info.value)
    assert "()" in message or "empty" in message.lower()
    assert "expected" in message.lower()


def test_format_radio_option_aligns_profile_detail_column() -> None:
    """Profile labels align from derived width while keeping approved radio glyphs."""
    labels = ("coding", "messaging", "full")
    width = radio_option_label_width(labels)
    lines = [
        format_radio_option(
            1,
            "coding",
            "Local development (default)",
            selected=True,
            label_width=width,
        ),
        format_radio_option(
            2,
            "messaging",
            "Gateways / bots — read-only posture",
            selected=False,
            label_width=width,
        ),
        format_radio_option(
            3,
            "full",
            "Coding + curated MCP servers",
            selected=False,
            label_width=width,
        ),
    ]
    assert lines == [
        "● 1  coding     Local development (default)",
        "○ 2  messaging  Gateways / bots — read-only posture",
        "○ 3  full       Coding + curated MCP servers",
    ]


def test_format_radio_option_renders_proposal_b_model_rows() -> None:
    """Chrome owns model radio glyphs/layout from glyph-free catalog fields."""
    labels = ("Grok 4.5", "Composer 2.5")
    width = radio_option_label_width(labels)
    lines = [
        format_radio_option(
            1,
            "Grok 4.5",
            "grok-4.5         (recommended)",
            selected=True,
            label_width=width,
        ),
        format_radio_option(
            2,
            "Composer 2.5",
            "composer-2.5",
            selected=False,
            label_width=width,
        ),
        format_radio_escape_hatch("Other — type a Cursor SDK model id"),
    ]
    assert lines == [
        "● 1  Grok 4.5      grok-4.5         (recommended)",
        "○ 2  Composer 2.5  composer-2.5",
        "○    Other — type a Cursor SDK model id",
    ]


def test_format_radio_escape_hatch_is_unnumbered_hollow_row() -> None:
    """Other escape hatch keeps hollow glyph and omits a numeric index."""
    line = format_radio_escape_hatch("Other — type a Cursor SDK model id")
    assert line == f"{GLYPH_RADIO_OFF}    Other — type a Cursor SDK model id"
    assert "1" not in line and "2" not in line
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


def test_format_success_emits_detail_lines_before_next_hint() -> None:
    """Interactive success includes generated artifact details before Next."""
    rendered = format_success(
        "Configuration written.",
        "Next: cursor-agent setup check",
        detail_lines=["backup: /tmp/project/.env.bak.20260709-120000"],
    )
    assert rendered.splitlines() == [
        "✓  Configuration written.",
        "│  backup: /tmp/project/.env.bak.20260709-120000",
        "│  Next: cursor-agent setup check",
    ]


def test_formatters_return_exact_layout_strings_without_tty_dependency() -> None:
    """Formatters are pure: exact layout strings, no interactive I/O side effects."""
    step = format_step("Title", ["Body"], "Prompt?")
    radio = format_radio_option(1, "Label", "id", selected=True)
    summary = format_summary([("Key", "Value")])
    success = format_success("Done.", "Next: check")
    assert step == (
        f"{GLYPH_STEP}  Title\n{GLYPH_TRUNK}  Body\n"
        f"{GLYPH_TRUNK}\n{GLYPH_PROMPT}  Prompt?"
    )
    assert radio == f"{GLYPH_RADIO_ON} 1  Label  id"
    assert summary == f"{GLYPH_SUMMARY}  Summary\n{GLYPH_TRUNK}  Key: Value"
    assert success == f"{GLYPH_SUCCESS}  Done.\n{GLYPH_TRUNK}  Next: check"
