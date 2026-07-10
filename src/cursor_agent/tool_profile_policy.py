"""Canonical tool profile policy for coding, messaging, and full profiles.

``full`` injects curated MCP servers from :mod:`cursor_agent.mcp_registry`
(ADR-029). Messaging still forces an empty MCP map; coding leaves SDK/project
MCP settings untouched (``None`` override).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from cursor_agent.mcp_registry import GithubTransport, build_mcp_servers_for_full
from cursor_agent.tool_profiles import ALLOWED_TOOL_PROFILES

_LOGGER = logging.getLogger(__name__)

# Q2 / ADR-029: omit+warn once per process for the same omit reason (create/resume).
_emitted_mcp_omit_warnings: set[str] = set()


def clear_mcp_omit_warning_cache_for_tests() -> None:
    """Reset omit-warning dedupe state between unit tests."""
    _emitted_mcp_omit_warnings.clear()


def effective_tool_profile(
    config_profile: str,
    session_profile: str,
) -> str:
    """Return the effective tool profile; messaging wins, else session wins.

    Messaging dominates when either side requests it (ADR-014). Among
    ``coding`` / ``full``, the session profile wins (PRD-012 FR-3).

    Example:
        >>> effective_tool_profile("coding", "messaging")
        'messaging'
        >>> effective_tool_profile("full", "coding")
        'coding'
        >>> effective_tool_profile("coding", "full")
        'full'
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


def mcp_servers_override_for_profile(
    tool_profile: str,
    *,
    allowlist: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    github_transport: GithubTransport | None = None,
) -> dict[str, Any] | None:
    """Return MCP override for agent create; None preserves SDK/project settings.

    Messaging returns an explicit empty map (allowlist ignored). Coding returns
    None so the SDK and workspace MCP configuration remain in effect. Full
    returns the curated registry map (may be empty when all servers are omitted).

    Example:
        >>> mcp_servers_override_for_profile("messaging")
        {}
        >>> mcp_servers_override_for_profile("coding") is None
        True
        >>> mcp_servers_override_for_profile("full", environ={})  # doctest: +ELLIPSIS
        {...}
    """
    if tool_profile == "messaging":
        return {}
    if tool_profile == "coding":
        return None
    if tool_profile == "full":
        return _mcp_servers_for_full(
            allowlist=allowlist,
            environ=environ,
            github_transport=github_transport,
        )
    allowed = ", ".join(sorted(ALLOWED_TOOL_PROFILES))
    raise ValueError(
        f"unsupported tool_profile for MCP override: received {tool_profile!r}, "
        f"expected one of {{{allowed}}}"
    )


def _mcp_servers_for_full(
    *,
    allowlist: Sequence[str] | None,
    environ: Mapping[str, str] | None,
    github_transport: GithubTransport | None,
) -> dict[str, Any]:
    """Build curated MCP servers for ``full``; warn once per omit reason (Q2)."""
    env_map: Mapping[str, str] = os.environ if environ is None else environ
    servers, warnings = build_mcp_servers_for_full(
        allowlist=allowlist,
        environ=env_map,
        github_transport=github_transport,
    )
    for warning in warnings:
        if warning in _emitted_mcp_omit_warnings:
            continue
        _emitted_mcp_omit_warnings.add(warning)
        _LOGGER.warning("%s", warning)
    return servers


def passes_mcp_servers_on_resume(tool_profile: str) -> bool:
    """Return True when resume must inject explicit ``mcp_servers``.

    Coding omits the field so persisted SDK/project MCP settings apply.
    Messaging and full pass an explicit map for defense in depth on resume.

    Example:
        >>> passes_mcp_servers_on_resume("messaging")
        True
        >>> passes_mcp_servers_on_resume("full")
        True
        >>> passes_mcp_servers_on_resume("coding")
        False
    """
    return tool_profile in {"messaging", "full"}


def sandbox_enabled(tool_profile: str) -> bool:
    """Return True when SDK sandbox must be enabled for the profile.

    Only messaging enables sandbox; coding and full are trusted local profiles.

    Example:
        >>> sandbox_enabled("messaging")
        True
        >>> sandbox_enabled("full")
        False
    """
    return tool_profile == "messaging"
