"""Canonical tool profile policy for coding and messaging profiles."""

from __future__ import annotations

from typing import Any


def effective_tool_profile(
    config_profile: str,
    session_profile: str,
) -> str:
    """Return the stricter tool profile; messaging wins over coding (ADR-014).

    Example:
        >>> effective_tool_profile("coding", "messaging")
        'messaging'
    """
    if config_profile == "messaging" or session_profile == "messaging":
        return "messaging"
    return session_profile


def requires_messaging_hooks(config_profile: str, session_profile: str) -> bool:
    """Return True when messaging hooks must be installed for the effective profile.

    Example:
        >>> requires_messaging_hooks("coding", "messaging")
        True
    """
    return effective_tool_profile(config_profile, session_profile) == "messaging"


def resolve_mcp_servers(tool_profile: str) -> dict[str, Any]:
    """Return MCP server config for a tool profile; messaging uses an empty map.

    Example:
        >>> resolve_mcp_servers("messaging")
        {}
    """
    if tool_profile in {"coding", "messaging"}:
        return {}
    return {}


def sandbox_enabled(tool_profile: str) -> bool:
    """Return True when SDK sandbox must be enabled for the profile.

    Example:
        >>> sandbox_enabled("messaging")
        True
    """
    return tool_profile == "messaging"
