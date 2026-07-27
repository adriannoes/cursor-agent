"""User-facing product copy (English) for CLI, gateway, and platform adapters.

PRD-007 targets English-first gateway/Telegram UX; Portuguese copy is out of scope
for this module until locale support is added.
"""

from __future__ import annotations

from typing import Final

from cursor_agent.tool_profiles import WIZARD_TOOL_PROFILE_ENTRIES

GATEWAY_BUSY_MESSAGE: Final[str] = (
    "I'm still processing your previous message. Please wait or send /stop."
)

TELEGRAM_NO_SESSION_HINT: Final[str] = "Send /new to start a conversation."

EMAIL_NO_SESSION_HINT: Final[str] = (
    "Send an email with /new in the body (or subject) to start a conversation."
)

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
  - /skills          list skills (also: skills list)
  - skills seed      optional starters; skills path
  - sessions list    see past sessions

  Setup & docs: docs/setup.md"""

FIRST_RUN_GETTING_STARTED: Final[str] = (
    f"{_WELCOME_BORDER}\n"
    "                     >_  CURSOR AGENT\n"
    "                   powered by Cursor\n"
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

# --- PRD-013 / v1.1.0 Wave G3 setup wizard chrome copy (FR-11) ---
# Titles/hints/prompts are glyph-free; setup_wizard_chrome owns ◆/│/└/◇/✓.

SETUP_TITLE_INTRO: Final[str] = "cursor-agent setup"
SETUP_INTRO: Final[str] = (
    "Configure local settings for this machine.\n"
    "You will set an API key, workspace, and optional defaults.\n"
    "Details: docs/setup.md"
)

SETUP_TITLE_API_KEY: Final[str] = "API key"
SETUP_HINT_API_KEY: Final[str] = (
    "Required for the Cursor SDK. Input is hidden.\n"
    "Create a key: docs/cursor-api-key-onboarding.md"
)
SETUP_PROMPT_API_KEY: Final[str] = "CURSOR_API_KEY:"

SETUP_TITLE_WORKSPACE: Final[str] = "Workspace"
SETUP_HINT_WORKSPACE: Final[str] = (
    "Local project directory for the agent.\nEnter keeps the current directory."
)
SETUP_PROMPT_WORKSPACE: Final[str] = "Workspace [{default}]:"

SETUP_TITLE_MEMORY_ROOT: Final[str] = "Memory root"
SETUP_HINT_MEMORY_ROOT: Final[str] = (
    "Optional directory for USER.md / MEMORY.md.\n"
    "Enter skips (default: ~/.cursor-agent)."
)
SETUP_PROMPT_MEMORY_ROOT: Final[str] = "Memory root:"

SETUP_TITLE_SESSIONS_DB: Final[str] = "Sessions database"
SETUP_HINT_SESSIONS_DB: Final[str] = (
    "Optional SQLite path for session records.\n"
    "Enter skips (default: ~/.cursor-agent/sessions.db)."
)
SETUP_PROMPT_SESSIONS_DB: Final[str] = "Sessions DB:"

SETUP_TITLE_MODEL: Final[str] = "Agent model"
SETUP_HINT_MODEL: Final[str] = (
    "Choose a Cursor first-party model. Enter keeps the default."
)
SETUP_PROMPT_MODEL: Final[str] = "Model [1 / 2 / id]:"

SETUP_TITLE_TOOL_PROFILE: Final[str] = "Tool profile"
SETUP_HINT_TOOL_PROFILE: Final[str] = (
    "Controls tool posture for this config.\nEnter keeps the default (coding)."
)
SETUP_PROMPT_TOOL_PROFILE: Final[str] = "Tool profile [1 / 2 / 3 / name]:"

# Base labels only — "(default)" suffix is appended from is_default on entries.
_SETUP_TOOL_PROFILE_LABELS: Final[dict[str, str]] = {
    "coding": "Local development",
    "messaging": "Gateways / bots — read-only posture",
    "full": "Coding + curated MCP servers",
}
SETUP_TOOL_PROFILE_OPTIONS: Final[tuple[tuple[int, str, str, bool], ...]] = tuple(
    (
        index,
        profile_name,
        (
            f"{_SETUP_TOOL_PROFILE_LABELS[profile_name]} (default)"
            if is_default
            else _SETUP_TOOL_PROFILE_LABELS[profile_name]
        ),
        is_default,
    )
    for index, (profile_name, is_default) in enumerate(
        WIZARD_TOOL_PROFILE_ENTRIES,
        start=1,
    )
)

SETUP_SUMMARY_HEADER: Final[str] = "Summary"
SETUP_CONFIRM: Final[str] = "Write configuration? [y / N]:"

# Shared by interactive chrome (via format_success) and terse non-interactive apply.
SETUP_SUCCESS: Final[str] = "Configuration written.\nNext: cursor-agent setup check"

SETUP_ALREADY_CONFIGURED: Final[str] = "Already configured (no changes needed)."

__all__ = [
    "CURSOR_API_KEY_SETUP_HINT",
    "FIRST_COMMANDS_HINT",
    "FIRST_RUN_GETTING_STARTED",
    "GATEWAY_BUSY_MESSAGE",
    "SETUP_ALREADY_CONFIGURED",
    "SETUP_CONFIRM",
    "SETUP_HINT_API_KEY",
    "SETUP_HINT_MEMORY_ROOT",
    "SETUP_HINT_MODEL",
    "SETUP_HINT_SESSIONS_DB",
    "SETUP_HINT_TOOL_PROFILE",
    "SETUP_HINT_WORKSPACE",
    "SETUP_INTRO",
    "SETUP_PROMPT_API_KEY",
    "SETUP_PROMPT_MEMORY_ROOT",
    "SETUP_PROMPT_MODEL",
    "SETUP_PROMPT_SESSIONS_DB",
    "SETUP_PROMPT_TOOL_PROFILE",
    "SETUP_PROMPT_WORKSPACE",
    "SETUP_SUCCESS",
    "SETUP_SUMMARY_HEADER",
    "SETUP_TITLE_API_KEY",
    "SETUP_TITLE_INTRO",
    "SETUP_TITLE_MEMORY_ROOT",
    "SETUP_TITLE_MODEL",
    "SETUP_TITLE_SESSIONS_DB",
    "SETUP_TITLE_TOOL_PROFILE",
    "SETUP_TITLE_WORKSPACE",
    "SETUP_TOOL_PROFILE_OPTIONS",
    "TELEGRAM_NO_SESSION_HINT",
    "EMAIL_NO_SESSION_HINT",
    "WELCOME_LOGO",
    "WELCOME_READY_LINE",
    "WELCOME_TAGLINE",
]
