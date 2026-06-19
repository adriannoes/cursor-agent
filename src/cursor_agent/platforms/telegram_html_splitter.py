"""Tag-safe splitting of rendered Telegram HTML into message-sized fragments (ADR-012)."""

from __future__ import annotations

import re
from typing import Final

from cursor_agent.platforms.telegram_chunking import (
    TELEGRAM_FLUSH_THRESHOLD,
    TELEGRAM_MESSAGE_LIMIT,
    _hard_split_index,
    _preferred_break_index,
)

_TAG_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(</?(?:b|code|pre|a)(?:\s[^>]*)?>)",
    re.IGNORECASE,
)
_SUPPORTED_OPEN_TAG_NAMES: Final[frozenset[str]] = frozenset({"b", "code", "pre", "a"})


def split_telegram_html_fragments(rendered_html: str) -> list[str]:
    """Split rendered Telegram HTML without breaking supported tag balance."""
    if not rendered_html:
        return []

    tokens = _tokenize_html(rendered_html)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    open_tags: list[tuple[str, str]] = []

    def closing_suffix() -> str:
        return "".join(f"</{name}>" for name, _ in reversed(open_tags))

    def reopening_prefix() -> str:
        return "".join(open_token for _, open_token in open_tags)

    def flush_chunk() -> None:
        nonlocal current_parts, current_len
        if not current_parts:
            return
        chunk = "".join(current_parts)
        if open_tags:
            chunk += closing_suffix()
        chunks.append(chunk)
        current_parts = [reopening_prefix()] if open_tags else []
        current_len = len(current_parts[0]) if current_parts else 0

    def append_text_with_splits(text: str) -> None:
        nonlocal current_len
        remaining = text
        while remaining:
            overhead = len(closing_suffix()) if open_tags else 0
            max_chunk_room = TELEGRAM_MESSAGE_LIMIT - current_len - overhead
            flush_room = TELEGRAM_FLUSH_THRESHOLD - current_len - overhead
            limit = min(max_chunk_room, flush_room)
            if limit <= 0:
                flush_chunk()
                continue
            if len(remaining) <= limit:
                current_parts.append(remaining)
                current_len += len(remaining)
                return
            split_at = _preferred_break_index(remaining, limit)
            if split_at is None:
                split_at = _preferred_break_index(remaining, max_chunk_room)
            if split_at is None:
                split_at = _hard_split_index(len(remaining))
            split_at = min(split_at, limit, max_chunk_room)
            if split_at <= 0:
                msg = (
                    "invalid telegram html fragment split: "
                    f"split_at={split_at!r}, limit={limit!r}, "
                    f"remaining_length={len(remaining)!r}"
                )
                raise ValueError(msg)
            piece = remaining[:split_at]
            current_parts.append(piece)
            current_len += len(piece)
            flush_chunk()
            remaining = remaining[split_at:]

    for token in tokens:
        token_len = len(token)
        overhead = len(closing_suffix()) if open_tags else 0
        is_open_tag = token.startswith("<") and not token.startswith("</")
        is_close_tag = token.startswith("</")

        if is_open_tag:
            if (
                current_len + token_len + overhead > TELEGRAM_FLUSH_THRESHOLD
                and current_parts
            ):
                flush_chunk()
                overhead = len(closing_suffix()) if open_tags else 0
            current_parts.append(token)
            current_len += token_len
            name, open_token = _parse_open_tag(token)
            if name in _SUPPORTED_OPEN_TAG_NAMES:
                open_tags.append((name, open_token))
            continue

        if is_close_tag:
            if (
                current_len + token_len + overhead > TELEGRAM_FLUSH_THRESHOLD
                and current_parts
            ):
                flush_chunk()
            current_parts.append(token)
            current_len += token_len
            name = token[2:-1].lower()
            if open_tags and open_tags[-1][0] == name:
                open_tags.pop()
            continue

        if (
            current_len + token_len + overhead > TELEGRAM_FLUSH_THRESHOLD
            and current_parts
        ):
            flush_chunk()
        append_text_with_splits(token)

    if current_parts:
        chunk = "".join(current_parts)
        if open_tags:
            chunk += closing_suffix()
        chunks.append(chunk)

    return [chunk for chunk in chunks if chunk]


def _tokenize_html(rendered_html: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    for match in _TAG_TOKEN_PATTERN.finditer(rendered_html):
        if match.start() > position:
            tokens.append(rendered_html[position : match.start()])
        tokens.append(match.group(0))
        position = match.end()
    if position < len(rendered_html):
        tokens.append(rendered_html[position:])
    return tokens


def _parse_open_tag(token: str) -> tuple[str, str]:
    lowered = token.lower()
    if lowered.startswith("<a "):
        return "a", token
    tag_name = token[1:].split(maxsplit=1)[0].rstrip(">").lower()
    return tag_name, token


__all__ = [
    "split_telegram_html_fragments",
]
