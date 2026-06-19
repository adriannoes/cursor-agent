"""Cursor-style Markdown to Telegram HTML rendering and tag-safe chunking (ADR-012)."""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Final

from cursor_agent.platforms.telegram_chunking import split_telegram_html_reply
from cursor_agent.platforms.telegram_html_splitter import (
    split_telegram_html_fragments,
)

_ALLOWED_LINK_SCHEMES: Final[tuple[str, ...]] = ("http://", "https://")
_FENCE_PATTERN: Final[re.Pattern[str]] = re.compile(r"```([^\n]*)\n(.*?)```", re.DOTALL)
_HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s+(.+)$")
_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_PATTERN: Final[re.Pattern[str]] = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"`([^`]+)`")
_PLACEHOLDER_PREFIX: Final[str] = "\x00TGHTML"
_SEPARATOR_CELL_PATTERN: Final[re.Pattern[str]] = re.compile(r":?-+:?")


@dataclass(frozen=True)
class _MarkdownTableBlock:
    """Parsed GitHub-flavored Markdown table block."""

    header_cells: list[str]
    data_rows: list[list[str]]
    raw_lines: list[str]


class TelegramFormattingError(ValueError):
    """Raised when Markdown cannot be rendered safely for Telegram HTML."""


def prepare_telegram_assistant_reply_chunks(
    text: str,
    *,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Render assistant Markdown to Telegram HTML chunks with plain-text fallback."""
    try:
        rendered = render_cursor_markdown_for_telegram(text)
        return split_telegram_html_fragments(rendered)
    except Exception as exc:
        if logger is not None:
            logger.warning(
                "telegram_formatting_fallback platform=telegram exception_class=%s",
                exc.__class__.__name__,
            )
        return split_telegram_html_reply(text)


def render_cursor_markdown_for_telegram(text: str) -> str:
    """Render a conservative Cursor-style Markdown subset to Telegram HTML.

    Supported: bold, inline code, language-tagged fenced code as ``<b>Lang:</b> <code>``,
    headings, http(s) links, plain list lines, and GitHub-flavored Markdown tables.
    All model text is HTML-escaped before entering tags.

    Example:
        >>> render_cursor_markdown_for_telegram("**hi**")
        '<b>hi</b>'
    """
    if not text:
        return ""

    try:
        blocks: list[str] = []
        last_end = 0
        for match in _FENCE_PATTERN.finditer(text):
            if match.start() > last_end:
                prose = _render_prose_block(text[last_end : match.start()])
                if prose.strip():
                    blocks.append(prose)
            language_info = match.group(1)
            code_body = match.group(2)
            blocks.append(_render_fenced_code_block(language_info, code_body))
            last_end = match.end()
        if last_end < len(text):
            prose = _render_prose_block(text[last_end:])
            if prose.strip():
                blocks.append(prose)
        return _join_rendered_blocks(blocks)
    except Exception as exc:
        msg = (
            "failed to render cursor markdown for telegram: "
            f"input_length={len(text)!r}, exception_class={exc.__class__.__name__}"
        )
        raise TelegramFormattingError(msg) from exc


def _fence_language_label(language_info: str) -> str | None:
    """Return a Telegram-safe label for a fenced-code language tag, if any."""
    tag = language_info.strip()
    if not tag:
        return None
    return tag.split()[0].title()


def _render_fenced_code_block(language_info: str, code_body: str) -> str:
    """Render fenced code as bold label + inline code.

    ``<pre>`` blocks collapse into the same Shell pill UI on mobile Telegram
    clients, so language-tagged fences use ``<b>Lang:</b> <code>...`` instead.
    """
    normalized_body = code_body.rstrip("\n")
    escaped_body = html.escape(normalized_body, quote=False)
    label = _fence_language_label(language_info)
    if label is None:
        return f"<code>{escaped_body}</code>"
    return f"<b>{label}:</b> <code>{escaped_body}</code>"


def _collapse_vertical_whitespace(text: str, *, max_blank_run: int = 1) -> str:
    """Collapse consecutive blank lines and trim outer whitespace."""
    collapsed: list[str] = []
    blank_run = 0
    for line in text.split("\n"):
        if not line.strip():
            blank_run += 1
            if blank_run <= max_blank_run:
                collapsed.append("")
            continue
        blank_run = 0
        collapsed.append(line)
    while collapsed and not collapsed[0].strip():
        collapsed.pop(0)
    while collapsed and not collapsed[-1].strip():
        collapsed.pop()
    return "\n".join(collapsed)


def _join_rendered_blocks(blocks: list[str]) -> str:
    """Join rendered prose and code blocks with Telegram-friendly spacing."""
    non_empty_blocks = [block for block in blocks if block.strip()]
    if not non_empty_blocks:
        return ""
    return _collapse_vertical_whitespace("\n".join(non_empty_blocks))


def _render_prose_block(text: str) -> str:
    lines = text.split("\n")
    rendered_lines: list[str] = []
    index = 0
    while index < len(lines):
        table_end, table_block = _try_parse_markdown_table_block(lines, index)
        if table_block is not None:
            rendered_lines.append(_render_markdown_table_block(table_block))
            index = table_end
            continue

        line = lines[index]
        if not line:
            rendered_lines.append("")
            index += 1
            continue
        heading_match = _HEADING_PATTERN.match(line)
        if heading_match is not None:
            rendered_lines.append(
                f"<b>{_render_inline(heading_match.group(1), allow_bold=False)}</b>",
            )
            index += 1
            continue
        rendered_lines.append(_render_inline(line))
        index += 1
    return _collapse_vertical_whitespace("\n".join(rendered_lines))


def _try_parse_markdown_table_block(
    lines: list[str],
    start: int,
) -> tuple[int, _MarkdownTableBlock | None]:
    """Return the end index and parsed table when *start* begins a GFM table."""
    if start >= len(lines):
        return start, None

    header_line = lines[start]
    if "|" not in header_line:
        return start, None
    if start + 1 >= len(lines):
        return start, None
    if not _is_markdown_table_separator_row(lines[start + 1]):
        return start, None

    data_start = start + 2
    data_end = data_start
    while data_end < len(lines):
        row_line = lines[data_end]
        if not row_line or "|" not in row_line:
            break
        if _is_markdown_table_separator_row(row_line):
            break
        data_end += 1

    if data_end == data_start:
        return start, None

    raw_lines = lines[start:data_end]
    header_cells = _split_markdown_table_row_cells(header_line)
    data_rows = [
        _split_markdown_table_row_cells(lines[row_index])
        for row_index in range(data_start, data_end)
    ]
    return data_end, _MarkdownTableBlock(
        header_cells=header_cells,
        data_rows=data_rows,
        raw_lines=raw_lines,
    )


def _is_markdown_table_separator_row(line: str) -> bool:
    """Return True when *line* is a GFM alignment/separator row."""
    if "|" not in line:
        return False
    cells = _split_markdown_table_row_cells(line)
    if not cells:
        return False
    return all(_is_markdown_table_separator_cell(cell) for cell in cells)


def _is_markdown_table_separator_cell(cell: str) -> bool:
    """Return True when a table cell is only dash/colon alignment markup."""
    stripped = cell.strip()
    if not stripped:
        return False
    return _SEPARATOR_CELL_PATTERN.fullmatch(stripped) is not None


def _split_markdown_table_row_cells(row: str) -> list[str]:
    """Split a Markdown table row on pipes outside inline code spans."""
    cells: list[str] = []
    current: list[str] = []
    in_inline_code = False
    for character in row:
        if character == "`":
            in_inline_code = not in_inline_code
            current.append(character)
            continue
        if character == "|" and not in_inline_code:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    cells.append("".join(current).strip())
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _render_markdown_table_block(block: _MarkdownTableBlock) -> str:
    """Render a parsed Markdown table or fall back to escaped plain text."""
    column_count = len(block.header_cells)
    if column_count < 2:
        return _render_markdown_table_fallback(block.raw_lines)

    for row in block.data_rows:
        if len(row) != column_count:
            return _render_markdown_table_fallback(block.raw_lines)

    if column_count == 2:
        return _render_two_column_markdown_table(block.data_rows)
    return _render_multi_column_markdown_table(block.header_cells, block.data_rows)


def _render_markdown_table_fallback(raw_lines: list[str]) -> str:
    """Escape malformed table blocks as plain Telegram-safe text."""
    return "\n".join(html.escape(line, quote=False) for line in raw_lines)


def _render_two_column_markdown_table(rows: list[list[str]]) -> str:
    """Render a two-column table as compact Telegram bullet lines."""
    bullets: list[str] = []
    for row in rows:
        first_cell = _render_two_column_table_first_cell(row[0])
        second_cell = _render_inline(row[1])
        bullets.append(f"• {first_cell}: {second_cell}")
    return "\n".join(bullets)


def _render_two_column_table_first_cell(cell: str) -> str:
    """Render the first table column with structural bold when still plain."""
    rendered = _render_inline(cell)
    if "<b>" in rendered:
        return rendered
    return f"<b>{rendered}</b>"


def _render_multi_column_markdown_table(
    header_cells: list[str],
    rows: list[list[str]],
) -> str:
    """Render a multi-column table as labeled row blocks."""
    blocks: list[str] = []
    for item_index, row in enumerate(rows, start=1):
        block_lines = [f"<b>Item {item_index}</b>"]
        for header, cell in zip(header_cells, row, strict=True):
            header_label = _render_inline(header, allow_bold=False)
            cell_value = _render_inline(cell)
            block_lines.append(f"{header_label}: {cell_value}")
        blocks.append("\n".join(block_lines))
    return "\n\n".join(blocks)


def _render_inline(text: str, *, allow_bold: bool = True) -> str:
    placeholders: dict[str, str] = {}
    counter = 0

    def stash(fragment: str) -> str:
        nonlocal counter
        key = f"{_PLACEHOLDER_PREFIX}{counter}\x00"
        counter += 1
        placeholders[key] = fragment
        return key

    working = text

    def replace_links(value: str) -> str:
        def repl(match: re.Match[str]) -> str:
            label = match.group(1)
            url = match.group(2)
            if not url.lower().startswith(_ALLOWED_LINK_SCHEMES):
                return match.group(0)
            escaped_label = html.escape(label, quote=False)
            escaped_url = html.escape(url, quote=True)
            return stash(f'<a href="{escaped_url}">{escaped_label}</a>')

        return _LINK_PATTERN.sub(repl, value)

    def replace_bold(value: str) -> str:
        def repl(match: re.Match[str]) -> str:
            inner = _render_inline(match.group(1), allow_bold=False)
            return stash(f"<b>{inner}</b>")

        return _BOLD_PATTERN.sub(repl, value)

    def replace_inline_code(value: str) -> str:
        def repl(match: re.Match[str]) -> str:
            escaped = html.escape(match.group(1), quote=False)
            return stash(f"<code>{escaped}</code>")

        return _INLINE_CODE_PATTERN.sub(repl, value)

    working = replace_links(working)
    if allow_bold:
        working = replace_bold(working)
    working = replace_inline_code(working)
    escaped = html.escape(working, quote=False)
    for key, fragment in placeholders.items():
        escaped = escaped.replace(html.escape(key, quote=False), fragment)
    return escaped


__all__ = [
    "TelegramFormattingError",
    "prepare_telegram_assistant_reply_chunks",
    "render_cursor_markdown_for_telegram",
    "split_telegram_html_fragments",
]
