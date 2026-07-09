"""Unit tests for curated MCP registry (PRD-012 / ADR-029)."""

from __future__ import annotations

import pytest

from cursor_agent.mcp_registry import (
    MCP_SERVER_ID_BRAVE_SEARCH,
    MCP_SERVER_ID_GITHUB,
    MCP_SERVER_ID_PLAYWRIGHT,
    build_mcp_servers_for_full,
)

_FAKE_GITHUB_TOKEN = "ghp_fake_secret_token_DO_NOT_LEAK_abc123"
_FAKE_BRAVE_KEY = "BSA_fake_secret_key_DO_NOT_LEAK_xyz789"


def test_allowlist_filters_to_requested_curated_ids_only() -> None:
    """Only allowlisted curated server ids appear in the emitted map."""
    environ = {
        "GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN,
        "BRAVE_API_KEY": _FAKE_BRAVE_KEY,
    }
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_PLAYWRIGHT],
        environ=environ,
    )

    assert set(servers) == {MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_PLAYWRIGHT}
    assert MCP_SERVER_ID_BRAVE_SEARCH not in servers
    assert warnings == []


def test_default_allowlist_includes_all_curated_when_none() -> None:
    """None/unset allowlist defaults to every curated server id."""
    environ = {
        "GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN,
        "BRAVE_API_KEY": _FAKE_BRAVE_KEY,
    }
    servers, warnings = build_mcp_servers_for_full(allowlist=None, environ=environ)

    assert set(servers) == {
        MCP_SERVER_ID_GITHUB,
        MCP_SERVER_ID_BRAVE_SEARCH,
        MCP_SERVER_ID_PLAYWRIGHT,
    }
    assert warnings == []


def test_missing_required_env_omits_server_and_warns() -> None:
    """Missing required env omits that server and yields a warning (Q2)."""
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_PLAYWRIGHT],
        environ={},
    )

    assert set(servers) == {MCP_SERVER_ID_PLAYWRIGHT}
    assert MCP_SERVER_ID_GITHUB not in servers
    assert len(warnings) == 1
    assert MCP_SERVER_ID_GITHUB in warnings[0]
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in warnings[0]


def test_playwright_always_includable_without_required_env() -> None:
    """Playwright has no required env and is always includable when allowlisted."""
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_PLAYWRIGHT],
        environ={},
    )

    assert set(servers) == {MCP_SERVER_ID_PLAYWRIGHT}
    assert servers[MCP_SERVER_ID_PLAYWRIGHT]["command"] == "npx"
    assert servers[MCP_SERVER_ID_PLAYWRIGHT]["args"] == ["-y", "@playwright/mcp@latest"]
    assert warnings == []


def test_empty_allowlist_returns_empty_map() -> None:
    """An explicit empty allowlist yields an empty MCP map and no warnings."""
    environ = {
        "GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN,
        "BRAVE_API_KEY": _FAKE_BRAVE_KEY,
    }
    servers, warnings = build_mcp_servers_for_full(allowlist=[], environ=environ)

    assert servers == {}
    assert warnings == []


def test_unknown_server_id_raises_with_received_value_and_allowed_set() -> None:
    """Unknown ids fail fast with the received value and the allowed curated set."""
    with pytest.raises(ValueError) as exc_info:
        build_mcp_servers_for_full(allowlist=["not-a-real-server"], environ={})

    message = str(exc_info.value)
    assert "not-a-real-server" in message
    assert MCP_SERVER_ID_GITHUB in message
    assert MCP_SERVER_ID_BRAVE_SEARCH in message
    assert MCP_SERVER_ID_PLAYWRIGHT in message


def test_warnings_never_contain_secret_token_values() -> None:
    """Omit+warn path must never echo secret token values into warning text."""
    # github present so only brave is omitted; fake tokens must not appear in warnings
    environ = {"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN}
    _servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_BRAVE_SEARCH],
        environ=environ,
    )

    assert len(warnings) == 1
    joined = "\n".join(warnings)
    assert _FAKE_GITHUB_TOKEN not in joined
    assert _FAKE_BRAVE_KEY not in joined
    assert "BRAVE_API_KEY" in joined


def test_github_and_brave_env_values_appear_in_emitted_env_dict() -> None:
    """Required env values are interpolated into the emitted server env dict."""
    environ = {
        "GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN,
        "BRAVE_API_KEY": _FAKE_BRAVE_KEY,
    }
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_BRAVE_SEARCH],
        environ=environ,
    )

    assert warnings == []
    assert servers[MCP_SERVER_ID_GITHUB] == {
        "command": "docker",
        "args": [
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "ghcr.io/github/github-mcp-server",
        ],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN},
    }
    assert servers[MCP_SERVER_ID_BRAVE_SEARCH] == {
        "command": "npx",
        "args": ["-y", "@brave/brave-search-mcp-server"],
        "env": {"BRAVE_API_KEY": _FAKE_BRAVE_KEY},
    }
