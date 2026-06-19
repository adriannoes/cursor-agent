"""User-facing product copy (English) for CLI, gateway, and platform adapters.

PRD-007 targets English-first gateway/Telegram UX; Portuguese copy is out of scope
for this module until locale support is added.
"""

from __future__ import annotations

from typing import Final

GATEWAY_BUSY_MESSAGE: Final[str] = (
    "I'm still processing your previous message. Please wait or send /stop."
)

TELEGRAM_NO_SESSION_HINT: Final[str] = "Send /new to start a conversation."

_WELCOME_BORDER: Final[str] = "=" * 58

WELCOME_LOGO: Final[str] = (
    f"{_WELCOME_BORDER}\n                     >_  CURSOR AGENT\n{_WELCOME_BORDER}"
)

WELCOME_TAGLINE: Final[str] = "Build faster. Ship sooner. Repeat less."

WELCOME_READY_LINE: Final[str] = "✓ Ready — type your request or /help."

FIRST_COMMANDS_HINT: Final[str] = """\
Get started:
  - describe what you want, in plain language
  - /help            list commands
  - /new             start a fresh session
  - /skills          list available workspace skills
  - sessions list    see past sessions

  Setup & docs: docs/setup.md"""

FIRST_RUN_GETTING_STARTED: Final[str] = (
    f"{_WELCOME_BORDER}\n"
    "                     >_  CURSOR AGENT\n"
    "                   powered by Composer\n"
    "\n"
    "   You bring the ideas. We handle the repetitive parts.\n"
    "\n"
    "     ✓ Installation complete — you're ready to build.\n"
    "\n"
    f"{FIRST_COMMANDS_HINT}\n"
    f"{_WELCOME_BORDER}"
)

CURSOR_API_KEY_SETUP_HINT: Final[str] = (
    "Set CURSOR_API_KEY before starting.\n"
    "See docs/setup.md and docs/cursor-api-key-onboarding.md."
)

__all__ = [
    "CURSOR_API_KEY_SETUP_HINT",
    "FIRST_COMMANDS_HINT",
    "FIRST_RUN_GETTING_STARTED",
    "GATEWAY_BUSY_MESSAGE",
    "TELEGRAM_NO_SESSION_HINT",
    "WELCOME_LOGO",
    "WELCOME_READY_LINE",
    "WELCOME_TAGLINE",
]
