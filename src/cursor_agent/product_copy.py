"""User-facing product copy (English) for CLI, gateway, and platform adapters."""

from __future__ import annotations

from typing import Final

GATEWAY_BUSY_MESSAGE: Final[str] = (
    "I'm still processing your previous message. Please wait or send /stop."
)

TELEGRAM_NO_SESSION_HINT: Final[str] = "Send /new to start a conversation."

__all__ = [
    "GATEWAY_BUSY_MESSAGE",
    "TELEGRAM_NO_SESSION_HINT",
]
