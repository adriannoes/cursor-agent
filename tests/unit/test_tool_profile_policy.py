"""Unit tests for canonical tool profile policy."""

from __future__ import annotations

from cursor_agent.tool_profile_policy import (
    effective_tool_profile,
    requires_messaging_hooks,
    resolve_mcp_servers,
    sandbox_enabled,
)


def test_effective_tool_profile_messaging_wins_over_coding() -> None:
    """Messaging must win when either config or session is messaging."""
    assert effective_tool_profile("messaging", "coding") == "messaging"
    assert effective_tool_profile("coding", "messaging") == "messaging"


def test_effective_tool_profile_keeps_coding_when_both_coding() -> None:
    """Coding remains when neither side requests messaging."""
    assert effective_tool_profile("coding", "coding") == "coding"


def test_requires_messaging_hooks_follows_effective_profile() -> None:
    """Hook deploy is required only for the effective messaging profile."""
    assert requires_messaging_hooks("messaging", "coding") is True
    assert requires_messaging_hooks("coding", "messaging") is True
    assert requires_messaging_hooks("coding", "coding") is False


def test_resolve_mcp_servers_returns_empty_maps() -> None:
    """Known and unknown profiles must resolve to empty MCP maps."""
    assert resolve_mcp_servers("coding") == {}
    assert resolve_mcp_servers("messaging") == {}
    assert resolve_mcp_servers("unknown") == {}


def test_sandbox_enabled_only_for_messaging() -> None:
    """Sandbox is enabled only for messaging profile."""
    assert sandbox_enabled("messaging") is True
    assert sandbox_enabled("coding") is False
