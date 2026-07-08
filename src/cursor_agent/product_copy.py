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
    "Run: cursor-agent setup\n"
    "Set CURSOR_API_KEY before starting.\n"
    "See docs/setup.md and docs/cursor-api-key-onboarding.md."
)

# --- PRD-013 setup wizard / apply success (FR-11) ---

SETUP_INTRO: Final[str] = (
    "Configure local cursor-agent settings.\n"
    "This will set your API key, workspace, and optional paths.\n"
    "Details: docs/setup.md"
)

SETUP_PROMPT_API_KEY: Final[str] = "CURSOR_API_KEY (input hidden): "

SETUP_PROMPT_WORKSPACE: Final[str] = "Workspace directory [{default}]: "

SETUP_PROMPT_MEMORY_ROOT: Final[str] = "Memory root (Enter to skip): "

SETUP_PROMPT_SESSIONS_DB: Final[str] = "Sessions DB path (Enter to skip): "

SETUP_PROMPT_MODEL: Final[str] = "Model id (Enter to skip): "

SETUP_PROMPT_TOOL_PROFILE: Final[str] = (
    "Tool profile coding|messaging (Enter to skip): "
)

SETUP_SUMMARY_HEADER: Final[str] = "Summary (review before write):"

SETUP_CONFIRM: Final[str] = "Write configuration? [y/N]: "

SETUP_SUCCESS: Final[str] = "Configuration written.\nNext: cursor-agent setup check"

SETUP_ALREADY_CONFIGURED: Final[str] = "Already configured (no changes needed)."

__all__ = [
    "CURSOR_API_KEY_SETUP_HINT",
    "FIRST_COMMANDS_HINT",
    "FIRST_RUN_GETTING_STARTED",
    "GATEWAY_BUSY_MESSAGE",
    "SETUP_ALREADY_CONFIGURED",
    "SETUP_CONFIRM",
    "SETUP_INTRO",
    "SETUP_PROMPT_API_KEY",
    "SETUP_PROMPT_MEMORY_ROOT",
    "SETUP_PROMPT_MODEL",
    "SETUP_PROMPT_SESSIONS_DB",
    "SETUP_PROMPT_TOOL_PROFILE",
    "SETUP_PROMPT_WORKSPACE",
    "SETUP_SUCCESS",
    "SETUP_SUMMARY_HEADER",
    "TELEGRAM_NO_SESSION_HINT",
    "WELCOME_LOGO",
    "WELCOME_READY_LINE",
    "WELCOME_TAGLINE",
]
