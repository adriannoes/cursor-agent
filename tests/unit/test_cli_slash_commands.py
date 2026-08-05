"""Unit tests for slash-command help text assembly (CLI UX /help clarity)."""

from __future__ import annotations

from cursor_agent.cli.slash_commands import handle_help

_FORBIDDEN_HELP_SUBSTRINGS: tuple[str, ...] = (
    "gateway",
    "cron",
    "/start",
    "telegram",
    "create app",
    "connect github",
    "p0",
    "p1",
    "p2",
    "get started:",
)

_REQUIRED_SLASH_MARKERS: tuple[str, ...] = (
    "/new",
    "/help",
    "/skills",
    "/resume",
    "/usage",
    "/compress",
    "/memory show",
)

_REQUIRED_GROUP_HEADERS: tuple[str, ...] = (
    "Session:",
    "Ops:",
    "Advanced:",
)


def _capture_help_text() -> str:
    """Collect the full /help output from handle_help."""
    lines: list[str] = []
    handle_help(writer=lines.append)
    return "\n".join(lines)


def test_handle_help_uses_operator_group_headers() -> None:
    """/help groups commands as Session / Ops / Advanced (not P0/P1/P2)."""
    help_text = _capture_help_text()
    for header in _REQUIRED_GROUP_HEADERS:
        assert header in help_text, f"/help must include group {header!r}"


def test_handle_help_lists_core_slash_commands() -> None:
    """/help documents the built-in slash surface."""
    help_text = _capture_help_text()
    for marker in _REQUIRED_SLASH_MARKERS:
        assert marker in help_text, f"/help must include {marker!r}"


def test_handle_help_does_not_embed_first_run_banner_block() -> None:
    """/help must not paste the first-run Get started / Typer blob into the REPL."""
    help_text = _capture_help_text()
    assert "Get started:" not in help_text
    assert "plain language" not in help_text
    # Typer commands belong in a single footer line, not mixed as slash peers.
    assert "\n  - doctor" not in help_text
    assert "\n  - sessions list" not in help_text


def test_handle_help_footer_points_to_typer_commands() -> None:
    """Footer discovers out-of-prompt Typer commands without jargon like REPL."""
    help_text = _capture_help_text()
    assert "Also useful:" in help_text
    assert "doctor" in help_text
    assert "sessions list" in help_text
    assert "skills" in help_text
    assert "docs/setup.md" in help_text
    assert "repl" not in help_text.lower()


def test_handle_help_excludes_gateway_cron_and_telegram_start() -> None:
    """/help must not mention gateway/cron/Telegram onboarding topics."""
    help_text = _capture_help_text().lower()
    for forbidden in _FORBIDDEN_HELP_SUBSTRINGS:
        assert forbidden not in help_text, f"/help must not mention {forbidden!r}"
