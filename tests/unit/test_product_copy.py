"""Unit tests for centralized user-facing product copy."""

from __future__ import annotations

from cursor_agent.platforms.base import GATEWAY_BUSY_MESSAGE
from cursor_agent.product_copy import (
    GATEWAY_BUSY_MESSAGE as COPY_GATEWAY_BUSY_MESSAGE,
    TELEGRAM_NO_SESSION_HINT,
)


def test_gateway_busy_message_is_english_and_reexported_from_platforms() -> None:
    """Gateway busy copy is defined once and re-exported by platforms.base."""
    expected = "I'm still processing your previous message. Please wait or send /stop."
    assert COPY_GATEWAY_BUSY_MESSAGE == expected
    assert GATEWAY_BUSY_MESSAGE == expected


def test_telegram_no_session_hint_is_non_empty_english() -> None:
    """Telegram first-contact hint is ready for PRD-007 adapter use."""
    assert TELEGRAM_NO_SESSION_HINT == "Send /new to start a conversation."
