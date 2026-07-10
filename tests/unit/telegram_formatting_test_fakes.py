"""Shared fixtures and assertions for Telegram HTML formatting unit tests."""

from __future__ import annotations

import re

from cursor_agent.platforms.telegram_chunking import TELEGRAM_MESSAGE_LIMIT

_SUPPORTED_TAG_PATTERN = re.compile(
    r"</?(?:b|code|pre|a)(?:\s[^>]*)?>",
    re.IGNORECASE,
)


def assert_balanced_supported_tags(fragment: str) -> None:
    """Assert supported Telegram HTML tags are balanced in *fragment*.

    Example:
        >>> assert_balanced_supported_tags("<b>ok</b>")
    """
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


def assert_telegram_html_chunk_valid(fragment: str) -> None:
    """Assert a chunk is structurally valid for Telegram parse_mode=HTML.

    Example:
        >>> assert_telegram_html_chunk_valid('<a href="https://ex.com">x</a>')
    """
    assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT, (
        f"chunk length {len(fragment)!r} exceeds Telegram limit {TELEGRAM_MESSAGE_LIMIT}"
    )
    assert_balanced_supported_tags(fragment)
    open_anchor_count = len(re.findall(r"<a\s", fragment, flags=re.IGNORECASE))
    close_anchor_count = fragment.lower().count("</a>")
    assert open_anchor_count == close_anchor_count, (
        f"anchor tag count mismatch: open={open_anchor_count!r}, "
        f"close={close_anchor_count!r} in {fragment[-120:]!r}"
    )
    assert "</a>" not in fragment or "<a " in fragment.lower(), (
        f"orphan closing anchor in chunk tail: {fragment[-80:]!r}"
    )


def build_long_two_column_markdown_table(row_count: int) -> str:
    """Build a realistic long two-column table used in Telegram chunking tests.

    Example:
        >>> markdown = build_long_two_column_markdown_table(row_count=2)
        >>> "Critério 0" in markdown
        True
    """
    rows = [
        (
            f"| Critério {index} (install → run) | "
            f"Alta com `a|b` e [link](https://example.com/path/{index}) |"
        )
        for index in range(row_count)
    ]
    return "Critério | Nota |\n| --- | --- |\n" + "\n".join(rows)


def build_memory_heavy_assistant_reply() -> str:
    """Build a long Markdown-rich reply similar to memory-informed first turns.

    Example:
        >>> reply = build_memory_heavy_assistant_reply()
        >>> "**Session context**" in reply
        True
    """
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
