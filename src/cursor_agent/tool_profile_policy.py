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


def mcp_servers_override_for_profile(tool_profile: str) -> dict[str, Any] | None:
    """Return MCP override for agent create; None preserves SDK/project settings.

    Messaging returns an explicit empty map to force no MCP servers. Coding
    returns None so the SDK and workspace MCP configuration remain in effect.

    Example:
        >>> mcp_servers_override_for_profile("messaging")
        {}
        >>> mcp_servers_override_for_profile("coding") is None
        True
    """
    if tool_profile == "messaging":
        return {}
    if tool_profile == "coding":
        return None
    raise ValueError(
        f"unsupported tool_profile for MCP override: received {tool_profile!r}, "
        "expected 'coding' or 'messaging'"
    )


def passes_mcp_servers_on_resume(tool_profile: str) -> bool:
    """Return True when resume must inject explicit ``mcp_servers``.

    Coding omits the field so persisted SDK/project MCP settings apply.
    Messaging passes an empty map for defense in depth on resume.

    Example:
        >>> passes_mcp_servers_on_resume("messaging")
        True
        >>> passes_mcp_servers_on_resume("coding")
        False
    """
    return tool_profile == "messaging"


def resolve_mcp_servers(tool_profile: str) -> dict[str, Any]:
    """Return MCP server config for a tool profile (legacy empty-map API).

    Prefer :func:`mcp_servers_override_for_profile` when ``None`` must mean
    "do not override SDK/project settings".

    Example:
        >>> resolve_mcp_servers("messaging")
        {}
    """
    override = mcp_servers_override_for_profile(tool_profile)
    return override if override is not None else {}


def sandbox_enabled(tool_profile: str) -> bool:
    """Return True when SDK sandbox must be enabled for the profile.

    Example:
        >>> sandbox_enabled("messaging")
        True
    """
    return tool_profile == "messaging"
