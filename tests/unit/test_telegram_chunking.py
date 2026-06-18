"""Unit tests for Telegram session-key and reply chunking helpers (PRD-007 Wave 2B)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cursor_agent.platforms.telegram_chunking import (
    TELEGRAM_FLUSH_THRESHOLD,
    TELEGRAM_MESSAGE_LIMIT,
    escape_telegram_html,
    split_telegram_html_reply,
    telegram_session_key,
    telegram_workspace_hash,
)


def _expected_workspace_hash(workspace: Path | str) -> str:
    """Compute workspace_hash per ADR-004."""
    absolute = str(Path(workspace).resolve())
    return hashlib.sha256(absolute.encode()).hexdigest()[:8]


# --- Session key helpers (sub-task 2.1) ---


def test_telegram_workspace_hash_is_stable_for_absolute_path(tmp_path: Path) -> None:
    """Workspace hash uses resolved absolute path and returns 8 hex chars."""
    expected = _expected_workspace_hash(tmp_path)
    assert telegram_workspace_hash(tmp_path) == expected
    assert len(telegram_workspace_hash(tmp_path)) == 8


def test_telegram_workspace_hash_same_workspace_same_hash(tmp_path: Path) -> None:
    """Same resolved workspace always yields the same hash."""
    nested = tmp_path / "nested"
    nested.mkdir()
    assert telegram_workspace_hash(tmp_path) == telegram_workspace_hash(nested / "..")


def test_telegram_workspace_hash_different_workspace_different_hash(
    tmp_path: Path,
) -> None:
    """Different workspaces produce different hashes."""
    other = tmp_path / "other"
    other.mkdir()
    assert telegram_workspace_hash(tmp_path) != telegram_workspace_hash(other)


def test_telegram_workspace_hash_accepts_str_path(tmp_path: Path) -> None:
    """Workspace hash accepts workspace as str."""
    assert telegram_workspace_hash(str(tmp_path)) == _expected_workspace_hash(
        str(tmp_path)
    )


def test_telegram_session_key_format_int_chat_id(tmp_path: Path) -> None:
    """Session key uses telegram:{chat_id}:{workspace_hash} with int chat_id."""
    workspace_hash = _expected_workspace_hash(tmp_path)
    assert telegram_session_key(123456789, tmp_path) == (
        f"telegram:123456789:{workspace_hash}"
    )


def test_telegram_session_key_format_str_chat_id(tmp_path: Path) -> None:
    """Session key accepts chat_id as str."""
    workspace_hash = _expected_workspace_hash(tmp_path)
    assert telegram_session_key("987654321", tmp_path) == (
        f"telegram:987654321:{workspace_hash}"
    )


# --- HTML escape (sub-task 2.3) ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain text", "plain text"),
        ("a < b > c", "a &lt; b &gt; c"),
        ("foo & bar", "foo &amp; bar"),
        ('say "hi"', 'say "hi"'),
        ("<script>alert('x')</script>", "&lt;script&gt;alert('x')&lt;/script&gt;"),
    ],
)
def test_escape_telegram_html_escapes_markup(raw: str, expected: str) -> None:
    """Model content is escaped for Telegram parse_mode=HTML without quoting quotes."""
    assert escape_telegram_html(raw) == expected


# --- Chunking (sub-task 2.3) ---


def test_split_telegram_html_reply_empty_text_returns_no_chunks() -> None:
    """Empty input produces no outbound chunks."""
    assert split_telegram_html_reply("") == []


def test_split_telegram_html_reply_short_text_single_chunk() -> None:
    """Text within flush threshold becomes one escaped chunk."""
    text = "Hello <world> & friends"
    chunks = split_telegram_html_reply(text)
    assert chunks == ["Hello &lt;world&gt; &amp; friends"]


def test_split_telegram_html_reply_respects_flush_threshold() -> None:
    """Buffered text exceeding 3800 chars triggers a split."""
    paragraph = "x" * 2000
    text = f"{paragraph}\n\n{paragraph}"
    assert len(text) > TELEGRAM_FLUSH_THRESHOLD
    chunks = split_telegram_html_reply(text)
    assert len(chunks) >= 2
    assert all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks)
    assert "".join(chunks) == text


def test_split_telegram_html_reply_prefers_double_newline_break() -> None:
    """Splitter prefers paragraph breaks (\\n\\n) near the flush threshold."""
    head = "a" * (TELEGRAM_FLUSH_THRESHOLD - 10)
    tail = "b" * 500
    text = f"{head}\n\n{tail}"
    chunks = split_telegram_html_reply(text)
    assert chunks[0].endswith("\n\n")
    assert chunks[1] == tail
    assert all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks)


def test_split_telegram_html_reply_prefers_single_newline_when_no_paragraph_break() -> (
    None
):
    """Splitter falls back to single newline breaks when \\n\\n is unavailable."""
    head = "a" * (TELEGRAM_FLUSH_THRESHOLD - 5)
    tail = "b" * 500
    text = f"{head}\n{tail}"
    chunks = split_telegram_html_reply(text)
    assert chunks[0].endswith("\n")
    assert chunks[1] == tail


def test_split_telegram_html_reply_hard_splits_unbroken_text() -> None:
    """Very long text without newlines is hard-split at the Telegram hard limit."""
    text = "z" * (TELEGRAM_MESSAGE_LIMIT + 500)
    chunks = split_telegram_html_reply(text)
    assert len(chunks) == 2
    assert len(chunks[0]) == TELEGRAM_MESSAGE_LIMIT
    assert len(chunks[1]) == 500
    assert "".join(chunks) == text


def test_split_telegram_html_reply_hard_splits_when_over_threshold_without_breaks() -> (
    None
):
    """Unbroken text just above flush threshold splits at the threshold."""
    text = "y" * (TELEGRAM_FLUSH_THRESHOLD + 100)
    chunks = split_telegram_html_reply(text)
    assert len(chunks) == 2
    assert len(chunks[0]) == TELEGRAM_FLUSH_THRESHOLD
    assert len(chunks[1]) == 100


def test_split_telegram_html_reply_no_empty_chunks() -> None:
    """Every emitted chunk is non-empty."""
    text = ("line\n\n" * 500) + ("word " * 2000)
    chunks = split_telegram_html_reply(text)
    assert chunks
    assert all(chunk for chunk in chunks)


def test_split_telegram_html_reply_escapes_before_splitting() -> None:
    """HTML escaping happens before length-based splitting."""
    raw = "<" * (TELEGRAM_FLUSH_THRESHOLD + 10)
    chunks = split_telegram_html_reply(raw)
    assert chunks
    assert all("&lt;" in chunk or chunk == "&lt;" for chunk in chunks)
    assert "".join(chunks) == escape_telegram_html(raw)


def test_telegram_limits_are_documented_constants() -> None:
    """Named limits match Telegram Bot API and ADR-012."""
    assert TELEGRAM_MESSAGE_LIMIT == 4096
    assert TELEGRAM_FLUSH_THRESHOLD == 3800
