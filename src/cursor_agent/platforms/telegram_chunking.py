"""Pure Telegram session-key and reply chunking helpers (ADR-004, ADR-012)."""

from __future__ import annotations

import hashlib
import html
from pathlib import Path

TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_FLUSH_THRESHOLD = 3800


def telegram_workspace_hash(workspace: Path | str) -> str:
    """Return the first 8 hex chars of sha256(abs(workspace)).

    Example:
        >>> telegram_workspace_hash("/tmp/project")  # doctest: +SKIP
        'a1b2c3d4'
    """
    absolute = str(Path(workspace).resolve())
    return hashlib.sha256(absolute.encode()).hexdigest()[:8]


def telegram_session_key(chat_id: int | str, workspace: Path | str) -> str:
    """Build the Telegram session key for a chat and workspace.

    Format: ``telegram:{chat_id}:{workspace_hash}``.

    Example:
        >>> telegram_session_key(123, "/tmp/project")  # doctest: +SKIP
        'telegram:123:a1b2c3d4'
    """
    workspace_hash = telegram_workspace_hash(workspace)
    return f"telegram:{chat_id}:{workspace_hash}"


def escape_telegram_html(text: str) -> str:
    """Escape model text for Telegram ``parse_mode=HTML``."""
    return html.escape(text, quote=False)


def _preferred_break_index(text: str, limit: int) -> int | None:
    """Return a split index preferring ``\\n\\n``, then ``\\n``, within *limit*."""
    if limit <= 0 or not text:
        return None
    window = text[:limit]
    paragraph_break = window.rfind("\n\n")
    if paragraph_break != -1:
        return paragraph_break + 2
    line_break = window.rfind("\n")
    if line_break != -1:
        return line_break + 1
    return None


def _hard_split_index(remaining_length: int) -> int:
    """Choose a hard split index when no preferred break exists."""
    if remaining_length > TELEGRAM_MESSAGE_LIMIT:
        return TELEGRAM_MESSAGE_LIMIT
    if remaining_length > TELEGRAM_FLUSH_THRESHOLD:
        return TELEGRAM_FLUSH_THRESHOLD
    return remaining_length


def split_telegram_html_reply(text: str) -> list[str]:
    """Escape and split assistant text into Telegram-safe HTML chunks.

    Chunks are emitted when buffered text exceeds ``TELEGRAM_FLUSH_THRESHOLD`` or
    at completion. Each chunk is ``<= TELEGRAM_MESSAGE_LIMIT`` characters.
    """
    return _split_text_into_chunks(escape_telegram_html(text))


def split_plain_text_reply(text: str) -> list[str]:
    """Split raw assistant text into Telegram-safe chunks without HTML escaping.

    Used as a send-time fallback when Telegram rejects ``parse_mode=HTML``.

    Example:
        >>> split_plain_text_reply("hello")
        ['hello']
    """
    return _split_text_into_chunks(text)


def _split_text_into_chunks(text: str) -> list[str]:
    """Split already-final text into ``<= TELEGRAM_MESSAGE_LIMIT`` chunks."""
    if not text:
        return []

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= TELEGRAM_FLUSH_THRESHOLD:
            chunks.append(remaining)
            break

        split_at = _preferred_break_index(remaining, TELEGRAM_FLUSH_THRESHOLD)
        if split_at is None:
            split_at = _preferred_break_index(remaining, TELEGRAM_MESSAGE_LIMIT)
        if split_at is None:
            split_at = _hard_split_index(len(remaining))

        if split_at <= 0 or split_at > len(remaining):
            msg = (
                "invalid telegram chunk split: "
                f"split_at={split_at!r}, remaining_length={len(remaining)!r}, "
                f"expected 1..{len(remaining)}"
            )
            raise ValueError(msg)

        chunk = remaining[:split_at]
        if not chunk:
            msg = (
                "empty telegram chunk after split: "
                f"split_at={split_at!r}, remaining_length={len(remaining)!r}, "
                "expected non-empty chunk"
            )
            raise ValueError(msg)

        chunks.append(chunk)
        remaining = remaining[split_at:]

    return chunks
