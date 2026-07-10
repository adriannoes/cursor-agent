"""Shared helpers for AsyncSdkFacade unit tests (create/resume option inspection)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

# Fake secrets for full-profile MCP wiring tests — never real credentials.
FAKE_FULL_GITHUB_TOKEN = "ghp_fake_facade_token_DO_NOT_LEAK"
FAKE_FULL_BRAVE_KEY = "BSA_fake_facade_key_DO_NOT_LEAK"


def local_option(local_opts: object, key: str) -> object | None:
    """Read a LocalAgentOptions field from object or mapping test doubles.

    Example:
        >>> local_option({"settingSources": ["project"]}, "setting_sources")
        ['project']
    """
    if isinstance(local_opts, dict):
        wire_key = {
            "setting_sources": "settingSources",
            "sandbox_options": "sandboxOptions",
        }.get(key, key)
        if wire_key in local_opts:
            return local_opts.get(wire_key)
        return local_opts.get(key)
    return getattr(local_opts, key, None)


def resume_request_options(mock_client: MagicMock) -> dict[str, Any]:
    """Extract JSON-serializable resume options passed to the SDK.

    Example:
        >>> options = resume_request_options(mock_client)
        >>> "mcpServers" in options
        False
    """
    resume_args = mock_client.agents.resume.await_args
    options = (
        resume_args.args[1]
        if len(resume_args.args) > 1
        else resume_args.kwargs.get("options")
    )
    assert isinstance(options, dict)
    json.dumps(options)
    return options


def sandbox_enabled(local_opts: object) -> bool | None:
    """Return sandbox_options.enabled from LocalAgentOptions or a mapping.

    Example:
        >>> sandbox_enabled({"sandboxOptions": {"enabled": True}})
        True
    """
    sandbox = local_option(local_opts, "sandbox_options")
    if sandbox is None:
        return None
    if isinstance(sandbox, dict):
        enabled = sandbox.get("enabled")
        return enabled if isinstance(enabled, bool) else None
    return getattr(sandbox, "enabled", None)


def create_mcp_servers(mock_client: MagicMock) -> dict[str, Any] | None:
    """Extract mcp_servers from client.agents.create positional options or kwargs.

    Example:
        >>> create_mcp_servers(mock_client)
        {}
    """
    call = mock_client.agents.create.await_args
    options = call.args[0] if call.args else None
    if isinstance(options, dict) and "mcp_servers" in options:
        mcp_servers = options["mcp_servers"]
        return mcp_servers if isinstance(mcp_servers, dict) else None
    kwarg_value = call.kwargs.get("mcp_servers")
    return kwarg_value if isinstance(kwarg_value, dict) else None
