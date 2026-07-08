"""Unit tests for centralized user-facing product copy."""

from __future__ import annotations

import re

from cursor_agent.platforms.base import GATEWAY_BUSY_MESSAGE
from cursor_agent.product_copy import (
    CURSOR_API_KEY_SETUP_HINT,
    FIRST_COMMANDS_HINT,
    FIRST_RUN_GETTING_STARTED,
    GATEWAY_BUSY_MESSAGE as COPY_GATEWAY_BUSY_MESSAGE,
    TELEGRAM_NO_SESSION_HINT,
    WELCOME_LOGO,
    WELCOME_READY_LINE,
    WELCOME_TAGLINE,
)

PRD_MAX_LINE_WIDTH = 60

_SECRET_LIKE_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9]{20,}|key_[A-Za-z0-9]{20,}|[A-Fa-f0-9]{32,})"
)

_FORBIDDEN_CLI_HINT_SUBSTRINGS: tuple[str, ...] = (
    "gateway",
    "cron",
    "/start",
    "telegram",
    "create app",
    "connect github",
)


def _max_rendered_line_width(text: str) -> int:
    """Return the widest line in a multi-line copy block."""
    lines = text.splitlines()
    if not lines:
        return 0
    return max(len(line) for line in lines)


def _assert_no_secret_like_values(text: str) -> None:
    """Product copy must not embed real API keys or token-shaped secrets."""
    assert _SECRET_LIKE_PATTERN.search(text) is None, (
        f"copy must not contain secret-like values: {text!r}"
    )


def _assert_cli_hint_exclusions(text: str) -> None:
    """CLI onboarding hints must not mention gateway/cron/Telegram /start."""
    lowered = text.lower()
    for forbidden in _FORBIDDEN_CLI_HINT_SUBSTRINGS:
        assert forbidden not in lowered, (
            f"CLI hint must not mention {forbidden!r}: {text!r}"
        )


def test_gateway_busy_message_is_english_and_reexported_from_platforms() -> None:
    """Gateway busy copy is defined once and re-exported by platforms.base."""
    expected = "I'm still processing your previous message. Please wait or send /stop."
    assert COPY_GATEWAY_BUSY_MESSAGE == expected
    assert GATEWAY_BUSY_MESSAGE == expected


def test_telegram_no_session_hint_is_non_empty_english() -> None:
    """Telegram first-contact hint is non-empty English copy."""
    assert TELEGRAM_NO_SESSION_HINT == "Send /new to start a conversation."


def test_welcome_tagline_is_compact_english_copy() -> None:
    """Recurring banner tagline matches PRD-011 compact mockup."""
    assert WELCOME_TAGLINE == "Build faster. Ship sooner. Repeat less."


def test_welcome_ready_line_is_compact_english_copy() -> None:
    """Recurring ready line matches PRD-011 compact mockup."""
    assert WELCOME_READY_LINE == "✓ Ready — type your request or /help."


def test_welcome_logo_is_ascii_wordmark_within_prd_width() -> None:
    """ASCII logo uses the >_ wordmark and stays within PRD width limits."""
    assert ">_  CURSOR AGENT" in WELCOME_LOGO
    assert "░" not in WELCOME_LOGO
    assert "▒" not in WELCOME_LOGO
    assert _max_rendered_line_width(WELCOME_LOGO) <= PRD_MAX_LINE_WIDTH


def test_first_commands_hint_includes_onboarding_discoverability_items() -> None:
    """Shared first-command hint lists the six PRD onboarding bullets."""
    assert "plain language" in FIRST_COMMANDS_HINT
    assert "/help" in FIRST_COMMANDS_HINT
    assert "/new" in FIRST_COMMANDS_HINT
    assert "/skills" in FIRST_COMMANDS_HINT
    assert "sessions list" in FIRST_COMMANDS_HINT
    assert "docs/setup.md" in FIRST_COMMANDS_HINT


def test_first_commands_hint_is_english_without_forbidden_cli_topics() -> None:
    """CLI first-command hint excludes gateway/cron/Telegram /start content."""
    _assert_cli_hint_exclusions(FIRST_COMMANDS_HINT)
    _assert_no_secret_like_values(FIRST_COMMANDS_HINT)
    assert _max_rendered_line_width(FIRST_COMMANDS_HINT) <= PRD_MAX_LINE_WIDTH


def test_first_run_getting_started_includes_composer_and_setup_pointer() -> None:
    """First-run block includes Composer branding and getting-started bullets."""
    assert "powered by Composer" in FIRST_RUN_GETTING_STARTED
    assert "Installation complete" in FIRST_RUN_GETTING_STARTED
    assert FIRST_COMMANDS_HINT.strip() in FIRST_RUN_GETTING_STARTED
    assert _max_rendered_line_width(FIRST_RUN_GETTING_STARTED) <= PRD_MAX_LINE_WIDTH


def test_cursor_api_key_setup_hint_points_to_setup_docs_without_secrets() -> None:
    """API-key setup hint links to setup docs and onboarding placeholders only."""
    assert "docs/setup.md" in CURSOR_API_KEY_SETUP_HINT
    assert "docs/cursor-api-key-onboarding.md" in CURSOR_API_KEY_SETUP_HINT
    assert "CURSOR_API_KEY" in CURSOR_API_KEY_SETUP_HINT
    _assert_no_secret_like_values(CURSOR_API_KEY_SETUP_HINT)
    _assert_cli_hint_exclusions(CURSOR_API_KEY_SETUP_HINT)
    assert _max_rendered_line_width(CURSOR_API_KEY_SETUP_HINT) <= PRD_MAX_LINE_WIDTH


def test_setup_hint_mentions_command_before_docs() -> None:
    """AuthError hint recommends ``cursor-agent setup`` before doc links (FR-21)."""
    hint = CURSOR_API_KEY_SETUP_HINT
    setup_command = "cursor-agent setup"
    assert setup_command in hint, f"hint must mention {setup_command!r}: {hint!r}"
    command_index = hint.index(setup_command)
    docs_markers = ("docs/setup.md", "docs/cursor-api-key-onboarding.md")
    for marker in docs_markers:
        assert marker in hint, f"hint must still mention {marker!r}: {hint!r}"
        assert command_index < hint.index(marker), (
            f"{setup_command!r} must appear before {marker!r} in hint: {hint!r}"
        )
    _assert_no_secret_like_values(hint)
    assert _max_rendered_line_width(hint) <= PRD_MAX_LINE_WIDTH


def test_first_commands_hint_has_no_setup_command_bullet() -> None:
    """Q7 Accept B: MVP does not add a ``cursor-agent setup`` banner bullet."""
    assert "cursor-agent setup" not in FIRST_COMMANDS_HINT
    assert "cursor-agent setup" not in FIRST_RUN_GETTING_STARTED


# --- Task 5.1 / 5.2: SETUP_* wizard + apply success copy (FR-11) -------------

_SETUP_COPY_NAMES: tuple[str, ...] = (
    "SETUP_INTRO",
    "SETUP_PROMPT_API_KEY",
    "SETUP_PROMPT_WORKSPACE",
    "SETUP_PROMPT_MEMORY_ROOT",
    "SETUP_PROMPT_SESSIONS_DB",
    "SETUP_PROMPT_MODEL",
    "SETUP_PROMPT_TOOL_PROFILE",
    "SETUP_SUMMARY_HEADER",
    "SETUP_CONFIRM",
    "SETUP_SUCCESS",
    "SETUP_ALREADY_CONFIGURED",
)


def test_setup_copy_constants_exist_english_first_without_secrets() -> None:
    """SETUP_* wizard/apply constants are non-empty English Final[str] without secrets."""
    import cursor_agent.product_copy as product_copy

    for name in _SETUP_COPY_NAMES:
        assert hasattr(product_copy, name), f"missing product_copy.{name}"
        value = getattr(product_copy, name)
        assert isinstance(value, str), f"{name} must be str, got {type(value)!r}"
        assert value.strip(), f"{name} must be non-empty"
        assert name in product_copy.__all__, f"{name} must be exported in __all__"
        _assert_no_secret_like_values(value)


def test_setup_intro_points_to_docs_setup() -> None:
    """Wizard intro mentions docs/setup.md for cold-start discoverability."""
    from cursor_agent.product_copy import SETUP_INTRO

    assert "docs/setup.md" in SETUP_INTRO
    assert _max_rendered_line_width(SETUP_INTRO) <= PRD_MAX_LINE_WIDTH


def test_setup_success_suggests_setup_check() -> None:
    """Apply/wizard success copy points operators to ``cursor-agent setup check``."""
    from cursor_agent.product_copy import SETUP_SUCCESS

    assert "cursor-agent setup check" in SETUP_SUCCESS
    _assert_no_secret_like_values(SETUP_SUCCESS)


def test_setup_already_configured_is_idempotent_message() -> None:
    """Idempotent apply uses a clear already-configured success string."""
    from cursor_agent.product_copy import SETUP_ALREADY_CONFIGURED

    lowered = SETUP_ALREADY_CONFIGURED.lower()
    assert "already" in lowered and "configur" in lowered


def test_setup_banner_adjacent_prompts_respect_prd_width() -> None:
    """Short wizard prompts stay within PRD ≤60 column budget where applicable."""
    import cursor_agent.product_copy as product_copy

    for name in (
        "SETUP_PROMPT_API_KEY",
        "SETUP_PROMPT_WORKSPACE",
        "SETUP_CONFIRM",
        "SETUP_SUMMARY_HEADER",
        "SETUP_SUCCESS",
        "SETUP_ALREADY_CONFIGURED",
    ):
        value = getattr(product_copy, name)
        assert _max_rendered_line_width(value) <= PRD_MAX_LINE_WIDTH, name
