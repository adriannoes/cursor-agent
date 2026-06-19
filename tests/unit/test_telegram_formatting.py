"""Unit tests for Cursor-style Markdown to Telegram HTML rendering (PRD-007 task 7)."""

from __future__ import annotations

import logging
import re
from unittest.mock import patch

import pytest

from cursor_agent.platforms.telegram_chunking import TELEGRAM_MESSAGE_LIMIT
from cursor_agent.platforms.telegram_formatting import (
    prepare_telegram_assistant_reply_chunks,
    render_cursor_markdown_for_telegram,
    split_telegram_html_fragments,
)

_SUPPORTED_TAG_PATTERN = re.compile(
    r"</?(?:b|code|pre|a)(?:\s[^>]*)?>",
    re.IGNORECASE,
)
_SUPPORTED_OPEN_TAG_NAMES: frozenset[str] = frozenset({"b", "code", "pre", "a"})


def _assert_balanced_supported_tags(fragment: str) -> None:
    """Assert supported Telegram HTML tags are balanced in *fragment*."""
    stack: list[str] = []
    for match in _SUPPORTED_TAG_PATTERN.finditer(fragment):
        token = match.group(0)
        if token.startswith("</"):
            tag = token[2:-1].lower()
            assert stack, f"unexpected closing tag {token!r} in {fragment!r}"
            assert stack[-1] == tag, (
                f"mismatched closing tag {token!r}, expected </{stack[-1]}>"
            )
            stack.pop()
        else:
            tag = token[1:].split(maxsplit=1)[0].rstrip(">").lower()
            stack.append(tag)
    assert not stack, f"unclosed tags {stack!r} in {fragment!r}"


def _assert_telegram_html_chunk_valid(fragment: str) -> None:
    """Assert a chunk is structurally valid for Telegram parse_mode=HTML."""
    assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT, (
        f"chunk length {len(fragment)!r} exceeds Telegram limit {TELEGRAM_MESSAGE_LIMIT}"
    )
    _assert_balanced_supported_tags(fragment)
    open_anchor_count = len(re.findall(r"<a\s", fragment, flags=re.IGNORECASE))
    close_anchor_count = fragment.lower().count("</a>")
    assert open_anchor_count == close_anchor_count, (
        f"anchor tag count mismatch: open={open_anchor_count!r}, "
        f"close={close_anchor_count!r} in {fragment[-120:]!r}"
    )
    assert "</a>" not in fragment or "<a " in fragment.lower(), (
        f"orphan closing anchor in chunk tail: {fragment[-80:]!r}"
    )


def _build_long_two_column_markdown_table(row_count: int) -> str:
    """Build a realistic long two-column table used in manual Telegram validation."""
    rows = [
        (
            f"| Critério {index} (install → run) | "
            f"Alta com `a|b` e [link](https://example.com/path/{index}) |"
        )
        for index in range(row_count)
    ]
    return "Critério | Nota |\n| --- | --- |\n" + "\n".join(rows)


def test_split_long_table_with_links_chunks_valid_telegram_html() -> None:
    """Regression: long table HTML must not orphan closing tags near flush threshold."""
    source = _build_long_two_column_markdown_table(row_count=80)
    rendered = render_cursor_markdown_for_telegram(source)
    assert len(rendered) > 3800, "fixture must exceed flush threshold to force chunking"
    fragments = split_telegram_html_fragments(rendered)
    assert len(fragments) >= 2
    for fragment in fragments:
        _assert_telegram_html_chunk_valid(fragment)
    combined = "".join(fragments)
    assert "• <b>Critério 0 (install → run)</b>" in combined
    assert '<a href="https://example.com/path/0">link</a>' in combined


def test_prepare_long_table_reply_chunks_valid_telegram_html() -> None:
    """End-to-end prepare path must emit Telegram-safe HTML chunks for long tables."""
    source = _build_long_two_column_markdown_table(row_count=80)
    chunks = prepare_telegram_assistant_reply_chunks(source)
    assert len(chunks) >= 2
    for chunk in chunks:
        _assert_telegram_html_chunk_valid(chunk)


def _build_memory_heavy_assistant_reply() -> str:
    """Build a long Markdown-rich reply similar to memory-informed first turns."""
    preference_rows = [
        (
            f"| Preference {index} | "
            f"Value with `opt|{index}` and [guide](https://example.com/prefs/{index}) |"
        )
        for index in range(60)
    ]
    checklist_rows = [
        (
            f"| Task {index} | "
            f"Verify with `pytest -k item_{index}` and "
            f"[runbook](https://example.com/tasks/{index}) |"
        )
        for index in range(40)
    ]
    return (
        "**Session context**\n\n"
        "I loaded your workspace preferences and prior notes:\n\n"
        "- Prefer `uv run pytest` for local verification\n"
        "- Keep adapter code free of memory-specific progress copy\n"
        "- Deliver replies through shared Telegram chunking helpers\n\n"
        "1. Confirm loader quotas\n"
        "2. Validate injection on the first free-text turn\n"
        "3. Check gateway inheritance without adapter branching\n\n"
        "Preference | Detail |\n| --- | --- |\n" + "\n".join(preference_rows) + "\n\n"
        "Example tooling snippet:\n\n"
        "```toml\n"
        "[tool.pytest.ini_options]\n"
        'markers = ["integration: needs CURSOR_API_KEY"]\n'
        "```\n\n"
        "Checklist | Next step |\n| --- | --- |\n"
        + "\n".join(checklist_rows)
        + "\n\n"
        + ("Boundary note: memory stays presentation-agnostic for Telegram. " * 80)
    )


def test_memory_heavy_assistant_reply_chunks_valid_telegram_html() -> None:
    """Memory-heavy assistant replies chunk safely with balanced Telegram HTML."""
    source = _build_memory_heavy_assistant_reply()
    rendered = render_cursor_markdown_for_telegram(source)
    assert len(rendered) > 3800, "fixture must exceed flush threshold to force chunking"
    chunks = prepare_telegram_assistant_reply_chunks(source)
    assert len(chunks) >= 2
    for chunk in chunks:
        _assert_telegram_html_chunk_valid(chunk)
    combined = "".join(chunks)
    assert "<b>Session context</b>" in combined
    assert "<b>Toml:</b> <code>" in combined
    assert '<a href="https://example.com/prefs/0">guide</a>' in combined
    assert "• <b>Preference 0</b>" in combined
    assert "- Prefer <code>uv run pytest</code>" in combined


def test_split_long_three_column_table_chunks_valid_telegram_html() -> None:
    """Multi-column table blocks must also chunk without orphan closing tags."""
    rows = [
        (
            f"| Critério {index} | Nota {index} | "
            f"Risco com [docs](https://example.com/r/{index}) |"
        )
        for index in range(60)
    ]
    source = "Critério | Nota | Risco |\n| --- | --- | --- |\n" + "\n".join(rows)
    rendered = render_cursor_markdown_for_telegram(source)
    fragments = split_telegram_html_fragments(rendered)
    assert len(fragments) >= 2
    for fragment in fragments:
        _assert_telegram_html_chunk_valid(fragment)
    assert "<b>Item 1</b>" in rendered


def test_render_bold_markdown() -> None:
    """**bold** renders as Telegram <b> tag with escaped inner text."""
    assert render_cursor_markdown_for_telegram("**bold**") == "<b>bold</b>"


def test_render_inline_code() -> None:
    """Inline backticks render as <code> with escaped content."""
    assert render_cursor_markdown_for_telegram("use `foo()` here") == (
        "use <code>foo()</code> here"
    )


def test_render_fenced_code_block() -> None:
    """Fenced code blocks with a language tag render as bold label + inline code."""
    source = "```python\nprint('hi')\n```"
    assert render_cursor_markdown_for_telegram(source) == (
        "<b>Python:</b> <code>print('hi')</code>"
    )


def test_render_fenced_shell_block_uses_bold_label_and_inline_code() -> None:
    """Shell fences render as bold label + inline code (no <pre> pill UI)."""
    source = "```shell\necho ok\n```"
    rendered = render_cursor_markdown_for_telegram(source)
    assert rendered == "<b>Shell:</b> <code>echo ok</code>"
    assert "<pre>" not in rendered


def test_render_fenced_code_block_without_language_uses_inline_code_only() -> None:
    """Bare fences without a language tag render as inline <code> only."""
    source = "```\necho ok\n```"
    assert render_cursor_markdown_for_telegram(source) == "<code>echo ok</code>"


def test_render_adjacent_fenced_blocks_without_extra_blank_lines() -> None:
    """Blank lines around fences must not stack into large Telegram gaps."""
    source = (
        "**Shell snippets**\n\n"
        "```shell\n"
        "echo ok\n"
        "```\n\n"
        "```bash\n"
        "ls -la\n"
        "```\n\n"
        "**Python snippet**"
    )
    rendered = render_cursor_markdown_for_telegram(source)
    assert "\n\n\n" not in rendered
    assert "<b>Shell:</b> <code>echo ok</code>" in rendered
    assert "<b>Bash:</b> <code>ls -la</code>" in rendered
    assert rendered.index("<b>Shell snippets</b>") < rendered.index("<b>Shell:</b>")
    assert rendered.index("<b>Bash:</b>") < rendered.index("<b>Python snippet</b>")


def test_render_empty_text_returns_empty_string() -> None:
    """Empty assistant text renders to an empty string."""
    assert render_cursor_markdown_for_telegram("") == ""


def test_render_prose_before_and_after_fenced_code() -> None:
    """Prose around a fenced code block renders alongside bold label + inline code."""
    source = "Run **this**:\n\n```sh\nls -la\n```\n\nThen check `output`."
    rendered = render_cursor_markdown_for_telegram(source)

    assert "<b>this</b>" in rendered
    assert "<b>Sh:</b> <code>ls -la</code>" in rendered
    assert "<code>output</code>" in rendered
    assert rendered.index("<b>this</b>") < rendered.index("<b>Sh:</b>")
    assert rendered.index("<b>Sh:</b>") < rendered.index("<code>output</code>")


def test_render_heading_as_bold() -> None:
    """Markdown headings render as bold plain headings."""
    assert render_cursor_markdown_for_telegram("## Section title") == (
        "<b>Section title</b>"
    )


def test_render_https_link() -> None:
    """Markdown links with https render as Telegram anchor tags."""
    assert render_cursor_markdown_for_telegram("[docs](https://example.com/docs)") == (
        '<a href="https://example.com/docs">docs</a>'
    )


def test_render_http_link() -> None:
    """http:// links are allowed."""
    assert render_cursor_markdown_for_telegram("[site](http://example.com)") == (
        '<a href="http://example.com">site</a>'
    )


def test_render_unsupported_link_scheme_as_plain_text() -> None:
    """Non-http(s) links stay escaped plain text."""
    rendered = render_cursor_markdown_for_telegram("[x](javascript:alert(1))")
    assert "<a " not in rendered
    assert "javascript" in rendered


def test_render_unordered_list_as_plain_lines() -> None:
    """List markers remain readable plain-text lines."""
    source = "- first\n- second"
    rendered = render_cursor_markdown_for_telegram(source)
    assert rendered == "- first\n- second"


def test_render_ordered_list_as_plain_lines() -> None:
    """Ordered list lines remain readable plain text."""
    source = "1. alpha\n2. beta"
    rendered = render_cursor_markdown_for_telegram(source)
    assert rendered == "1. alpha\n2. beta"


def test_render_mixed_markdown_snippet() -> None:
    """Representative Cursor reply mixes bold, code, and links."""
    source = "**Summary**\n\nSee `README.md` and [repo](https://github.com/org/proj)."
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<b>Summary</b>" in rendered
    assert "<code>README.md</code>" in rendered
    assert '<a href="https://github.com/org/proj">repo</a>' in rendered


def test_render_literal_angle_brackets_are_escaped() -> None:
    """Literal < and > in model text are HTML-escaped."""
    rendered = render_cursor_markdown_for_telegram("if x < 1 && y > 0")
    assert rendered == "if x &lt; 1 &amp;&amp; y &gt; 0"


def test_render_ampersand_is_escaped() -> None:
    """Ampersands in plain text are escaped."""
    assert render_cursor_markdown_for_telegram("Tom & Jerry") == "Tom &amp; Jerry"


def test_render_malformed_markdown_falls_back_to_escaped_text() -> None:
    """Unclosed emphasis markers do not crash rendering."""
    rendered = render_cursor_markdown_for_telegram("**unclosed bold")
    assert "**" in rendered or "<b>" in rendered
    assert "<" not in rendered.replace("&lt;", "")


def test_split_telegram_html_fragments_respects_message_limit() -> None:
    """Every emitted HTML fragment is within Telegram message limit."""
    html = "<b>" + ("word " * 900) + "</b>"
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT
        _assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_tag_balance_near_bold() -> None:
    """Chunk boundaries near <b> tags keep supported tags balanced."""
    html = "<b>" + ("x" * 2000) + "</b>\n\n" + ("y" * 2000)
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        _assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_fenced_inline_code_blocks() -> None:
    """Long bold-label inline code blocks split without leaving unbalanced tags."""
    code_body = "line\n" * 900
    html = f"<b>Shell:</b> <code>{code_body}</code>"
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        _assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_anchor_tags() -> None:
    """Chunking near <a href> keeps anchors balanced."""
    prefix = '<a href="https://example.com">'
    html = prefix + ("z" * 3900) + "</a>"
    fragments = split_telegram_html_fragments(html)
    for fragment in fragments:
        _assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_empty_returns_no_chunks() -> None:
    """Empty rendered HTML produces no fragments."""
    assert split_telegram_html_fragments("") == []


@pytest.mark.parametrize(
    ("markdown", "expected_substrings"),
    [
        ("```\n<script>alert(1)</script>\n```", ["&lt;script&gt;"]),
        ("`a & b`", ["<code>a &amp; b</code>"]),
    ],
)
def test_render_escapes_unsafe_content_inside_markup(
    markdown: str,
    expected_substrings: list[str],
) -> None:
    """Rendered HTML escapes user/model content inside supported tags."""
    rendered = render_cursor_markdown_for_telegram(markdown)
    for substring in expected_substrings:
        assert substring in rendered


def test_prepare_telegram_assistant_reply_chunks_renders_markdown() -> None:
    """High-level chunk helper renders Markdown before tag-safe splitting."""
    chunks = prepare_telegram_assistant_reply_chunks("**ok**")
    assert chunks == ["<b>ok</b>"]


def test_render_two_column_table_without_leading_pipes() -> None:
    """Two-column GFM tables render as Telegram bullet lines."""
    source = (
        "Critério | Nota |\n"
        "|----------|------|\n"
        "| Clareza e precisão | Alta |\n"
        "| Segurança e links | Alta |\n"
        "| Onboarding humano (install → run) | Baixa |"
    )
    rendered = render_cursor_markdown_for_telegram(source)
    assert "• <b>Clareza e precisão</b>: Alta" in rendered
    assert "• <b>Segurança e links</b>: Alta" in rendered
    assert "• <b>Onboarding humano (install → run)</b>: Baixa" in rendered
    assert "|----------|" not in rendered
    assert "Critério | Nota" not in rendered


def test_render_two_column_table_with_leading_pipes() -> None:
    """Tables with leading pipes normalize optional outer cells."""
    source = "| Name | Score |\n| --- | --- |\n| Alpha | 10 |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert rendered == "• <b>Alpha</b>: 10"


def test_render_table_with_alignment_separator_row() -> None:
    """Alignment markers in separator rows are treated as structural metadata."""
    source = "| left | center | right |\n|:---|:---:|---:|\n| a | b | c |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<b>Item 1</b>" in rendered
    assert "left: a" in rendered
    assert "center: b" in rendered
    assert "right: c" in rendered
    assert ":---" not in rendered


def test_render_table_with_blank_lines_around_block() -> None:
    """Blank lines before and after a table do not break detection."""
    source = "Intro line\n\nKey | Value |\n| --- | --- |\n| foo | bar |\n\nOutro line"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "Intro line" in rendered
    assert "• <b>foo</b>: bar" in rendered
    assert "Outro line" in rendered


def test_render_malformed_table_falls_back_to_escaped_plain_text() -> None:
    """Inconsistent column counts stay escaped plain text instead of raising."""
    source = "| only header |\n| --- |\n| a | b | extra |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<table" not in rendered.lower()
    assert "|" in rendered
    assert "&lt;" not in rendered or "|" in rendered


def test_render_three_column_table_as_row_blocks() -> None:
    """Three-column tables render compact Item blocks with header labels."""
    source = (
        "Critério | Nota | Risco |\n"
        "| --- | --- | --- |\n"
        "| Clareza e precisão | Alta | Baixo |\n"
        "| Segurança e links | Alta | Médio |"
    )
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<b>Item 1</b>" in rendered
    assert "Critério: Clareza e precisão" in rendered
    assert "Nota: Alta" in rendered
    assert "Risco: Baixo" in rendered
    assert "<b>Item 2</b>" in rendered
    assert "Risco: Médio" in rendered


def test_render_four_column_table_as_row_blocks() -> None:
    """Four-column tables use the same row-block layout."""
    source = "A | B | C | D |\n| - | - | - | - |\n| 1 | 2 | 3 | 4 |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<b>Item 1</b>" in rendered
    assert "A: 1" in rendered
    assert "D: 4" in rendered


def test_render_table_cell_inline_code_with_pipe() -> None:
    """Pipes inside inline code do not split table cells."""
    source = "Cmd | Example |\n| --- | --- |\n| run | `a | b` |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "• <b>run</b>: <code>a | b</code>" in rendered


def test_render_table_cell_bold_and_link() -> None:
    """Inline bold and safe links render inside table cells."""
    source = (
        "Label | Detail |\n| --- | --- |\n| **bold** | [docs](https://example.com) |"
    )
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<b>bold</b>" in rendered
    assert '<a href="https://example.com">docs</a>' in rendered


def test_render_table_cell_unsupported_link_scheme() -> None:
    """Unsupported link schemes in table cells stay escaped plain text."""
    source = "Label | Link |\n| --- | --- |\n| x | [bad](javascript:alert(1)) |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "<a " not in rendered
    assert "javascript" in rendered


def test_render_table_cell_special_characters_are_escaped() -> None:
    """Angle brackets and ampersands in cells are HTML-escaped."""
    source = "Key | Value |\n| --- | --- |\n| Tom & Jerry | if x < 1 |"
    rendered = render_cursor_markdown_for_telegram(source)
    assert "Tom &amp; Jerry" in rendered
    assert "if x &lt; 1" in rendered


def test_split_long_rendered_table_preserves_tag_balance() -> None:
    """Long rendered tables chunk into valid Telegram HTML fragments."""
    header = "Name | Score |\n| --- | --- |\n"
    rows = "\n".join(f"| Item {index} | {index} |" for index in range(200))
    rendered = render_cursor_markdown_for_telegram(header + rows)
    fragments = split_telegram_html_fragments(rendered)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT
        _assert_balanced_supported_tags(fragment)


def test_prepare_telegram_assistant_reply_chunks_falls_back_on_render_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Renderer failures fall back to escaped plain chunks with safe logs only."""
    caplog.set_level(logging.WARNING)
    secret = "secret prompt <b>text</b>"
    with patch(
        "cursor_agent.platforms.telegram_formatting.render_cursor_markdown_for_telegram",
        side_effect=RuntimeError("boom"),
    ):
        chunks = prepare_telegram_assistant_reply_chunks(
            secret,
            logger=logging.getLogger("test.telegram.formatting"),
        )
    assert chunks == ["secret prompt &lt;b&gt;text&lt;/b&gt;"]
    assert "telegram_formatting_fallback" in caplog.text
    assert "secret prompt" not in caplog.text
