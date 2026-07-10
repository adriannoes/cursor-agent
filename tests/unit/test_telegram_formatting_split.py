"""Unit tests for Telegram HTML split/prepare chunking (PRD-007 task 7)."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from cursor_agent.platforms.telegram_chunking import TELEGRAM_MESSAGE_LIMIT
from cursor_agent.platforms.telegram_formatting import (
    prepare_telegram_assistant_reply_chunks,
    render_cursor_markdown_for_telegram,
    split_telegram_html_fragments,
)
from tests.unit.telegram_formatting_test_fakes import (
    assert_balanced_supported_tags,
    assert_telegram_html_chunk_valid,
    build_long_two_column_markdown_table,
    build_memory_heavy_assistant_reply,
)


def test_split_long_table_with_links_chunks_valid_telegram_html() -> None:
    """Regression: long table HTML must not orphan closing tags near flush threshold."""
    source = build_long_two_column_markdown_table(row_count=80)
    rendered = render_cursor_markdown_for_telegram(source)
    assert len(rendered) > 3800, "fixture must exceed flush threshold to force chunking"
    fragments = split_telegram_html_fragments(rendered)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert_telegram_html_chunk_valid(fragment)
    combined = "".join(fragments)
    assert "• <b>Critério 0 (install → run)</b>" in combined
    assert '<a href="https://example.com/path/0">link</a>' in combined


def test_prepare_long_table_reply_chunks_valid_telegram_html() -> None:
    """End-to-end prepare path must emit Telegram-safe HTML chunks for long tables."""
    source = build_long_two_column_markdown_table(row_count=80)
    chunks = prepare_telegram_assistant_reply_chunks(source)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert_telegram_html_chunk_valid(chunk)


def test_memory_heavy_assistant_reply_chunks_valid_telegram_html() -> None:
    """Memory-heavy assistant replies chunk safely with balanced Telegram HTML."""
    source = build_memory_heavy_assistant_reply()
    rendered = render_cursor_markdown_for_telegram(source)
    assert len(rendered) > 3800, "fixture must exceed flush threshold to force chunking"
    chunks = prepare_telegram_assistant_reply_chunks(source)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert_telegram_html_chunk_valid(chunk)
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
        assert_telegram_html_chunk_valid(fragment)
    assert "<b>Item 1</b>" in rendered


def test_split_telegram_html_fragments_respects_message_limit() -> None:
    """Every emitted HTML fragment is within Telegram message limit."""
    html = "<b>" + ("word " * 900) + "</b>"
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT
        assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_tag_balance_near_bold() -> None:
    """Chunk boundaries near <b> tags keep supported tags balanced."""
    html = "<b>" + ("x" * 2000) + "</b>\n\n" + ("y" * 2000)
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_fenced_inline_code_blocks() -> None:
    """Long bold-label inline code blocks split without leaving unbalanced tags."""
    code_body = "line\n" * 900
    html = f"<b>Shell:</b> <code>{code_body}</code>"
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_anchor_tags() -> None:
    """Chunking near <a href> keeps anchors balanced."""
    prefix = '<a href="https://example.com">'
    html = prefix + ("z" * 3900) + "</a>"
    fragments = split_telegram_html_fragments(html)
    for fragment in fragments:
        assert_balanced_supported_tags(fragment)


def test_split_telegram_html_fragments_preserves_long_href_url() -> None:
    """Very long href URLs stay balanced when followed by long link text."""
    long_url = "https://example.com/" + "segment/" * 400
    html = f'<a href="{long_url}">docs</a>' + (" trailing text." * 300)
    fragments = split_telegram_html_fragments(html)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert_telegram_html_chunk_valid(fragment)
    combined = "".join(fragments)
    assert long_url in combined
    assert "docs" in combined


def test_split_telegram_html_fragments_empty_returns_no_chunks() -> None:
    """Empty rendered HTML produces no fragments."""
    assert split_telegram_html_fragments("") == []


def test_prepare_telegram_assistant_reply_chunks_renders_markdown() -> None:
    """High-level chunk helper renders Markdown before tag-safe splitting."""
    chunks = prepare_telegram_assistant_reply_chunks("**ok**")
    assert chunks == ["<b>ok</b>"]


def test_split_long_rendered_table_preserves_tag_balance() -> None:
    """Long rendered tables chunk into valid Telegram HTML fragments."""
    header = "Name | Score |\n| --- | --- |\n"
    rows = "\n".join(f"| Item {index} | {index} |" for index in range(200))
    rendered = render_cursor_markdown_for_telegram(header + rows)
    fragments = split_telegram_html_fragments(rendered)
    assert len(fragments) >= 2
    for fragment in fragments:
        assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT
        assert_balanced_supported_tags(fragment)


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
