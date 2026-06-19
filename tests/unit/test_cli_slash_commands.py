"""Unit tests for slash-command help text assembly (PRD-011 DRY hints)."""

from __future__ import annotations

from cursor_agent.cli.slash_commands import handle_help
from cursor_agent.product_copy import FIRST_COMMANDS_HINT

_FORBIDDEN_HELP_SUBSTRINGS: tuple[str, ...] = (
    "gateway",
    "cron",
    "/start",
    "telegram",
    "create app",
    "connect github",
)

_REQUIRED_DISCOVERABILITY_MARKERS: tuple[str, ...] = (
    "/new",
    "/help",
    "/skills",
    "sessions list",
)


def _capture_help_text() -> str:
    """Collect the full /help output from handle_help."""
    lines: list[str] = []
    handle_help(writer=lines.append)
    return "\n".join(lines)


def test_handle_help_includes_shared_first_commands_hint() -> None:
    """/help surfaces the shared first-command discoverability block."""
    help_text = _capture_help_text()
    assert FIRST_COMMANDS_HINT.strip() in help_text


def test_handle_help_includes_onboarding_discoverability_items() -> None:
    """/help includes the onboarding subset shared with the welcome banner."""
    help_text = _capture_help_text()
    for marker in _REQUIRED_DISCOVERABILITY_MARKERS:
        assert marker in help_text, f"/help must include {marker!r}"


def test_handle_help_excludes_gateway_cron_and_telegram_start() -> None:
    """/help discoverability must not mention advanced operator topics."""
    help_text = _capture_help_text().lower()
    for forbidden in _FORBIDDEN_HELP_SUBSTRINGS:
        assert forbidden not in help_text, f"/help must not mention {forbidden!r}"


def test_handle_help_preserves_advanced_command_groups() -> None:
    """Full /help keeps advanced groups for power-user slash commands."""
    help_text = _capture_help_text()
    for marker in ("/resume", "/usage", "/compress", "/memory show"):
        assert marker in help_text, f"/help must still document {marker!r}"
