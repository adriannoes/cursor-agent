"""Unit tests for curated MCP registry (PRD-012 / ADR-029)."""

from __future__ import annotations

import pytest

from cursor_agent.mcp_registry import (
    ALLOWED_GITHUB_TRANSPORTS,
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


def test_whitespace_only_required_env_omits_server_and_warns() -> None:
    """Whitespace-only secrets are treated as missing (not usable tokens)."""
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_BRAVE_SEARCH],
        environ={
            "GITHUB_PERSONAL_ACCESS_TOKEN": "   ",
            "BRAVE_API_KEY": "\t",
        },
    )

    assert servers == {}
    assert len(warnings) == 2
    assert any(MCP_SERVER_ID_GITHUB in warning for warning in warnings)
    assert any(MCP_SERVER_ID_BRAVE_SEARCH in warning for warning in warnings)


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


def test_github_and_brave_env_values_appear_in_emitted_configs() -> None:
    """Required secrets are interpolated into emitted github HTTP and brave stdio."""
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
        "url": "https://api.githubcopilot.com/mcp/",
        "headers": {"Authorization": f"Bearer {_FAKE_GITHUB_TOKEN}"},
    }
    assert "command" not in servers[MCP_SERVER_ID_GITHUB]
    assert servers[MCP_SERVER_ID_BRAVE_SEARCH] == {
        "command": "npx",
        "args": ["-y", "@brave/brave-search-mcp-server"],
        "env": {"BRAVE_API_KEY": _FAKE_BRAVE_KEY},
    }


def test_github_default_transport_emits_http_remote_shape() -> None:
    """Unset github_transport defaults to official remote HTTP (no Docker)."""
    environ = {"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN}
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB],
        environ=environ,
    )

    assert warnings == []
    github = servers[MCP_SERVER_ID_GITHUB]
    assert github["url"] == "https://api.githubcopilot.com/mcp/"
    assert github["headers"] == {"Authorization": f"Bearer {_FAKE_GITHUB_TOKEN}"}
    assert "command" not in github
    assert "args" not in github
    assert "env" not in github


def test_github_explicit_http_transport_emits_http_remote_shape() -> None:
    """Explicit github_transport='http' emits the same remote HTTP shape."""
    environ = {"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN}
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB],
        environ=environ,
        github_transport="http",
    )

    assert warnings == []
    github = servers[MCP_SERVER_ID_GITHUB]
    assert "url" in github
    assert github["url"] == "https://api.githubcopilot.com/mcp/"
    assert github["headers"]["Authorization"] == f"Bearer {_FAKE_GITHUB_TOKEN}"
    assert "command" not in github


def test_github_explicit_stdio_transport_emits_docker_shape() -> None:
    """Explicit github_transport='stdio' emits Docker stdio (operator choice)."""
    environ = {"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN}
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB],
        environ=environ,
        github_transport="stdio",
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
    assert "url" not in servers[MCP_SERVER_ID_GITHUB]


def test_github_missing_pat_omits_and_warns_on_http_path() -> None:
    """Missing PAT omits github on the default HTTP path and warns without secrets."""
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB],
        environ={},
        github_transport="http",
    )

    assert servers == {}
    assert len(warnings) == 1
    assert MCP_SERVER_ID_GITHUB in warnings[0]
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in warnings[0]
    assert _FAKE_GITHUB_TOKEN not in warnings[0]


def test_github_missing_pat_omits_and_warns_on_stdio_path() -> None:
    """Missing PAT omits github on the stdio Docker path and warns without secrets."""
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB],
        environ={},
        github_transport="stdio",
    )

    assert servers == {}
    assert len(warnings) == 1
    assert MCP_SERVER_ID_GITHUB in warnings[0]
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in warnings[0]
    assert _FAKE_GITHUB_TOKEN not in warnings[0]


def test_github_whitespace_pat_omits_on_both_transports() -> None:
    """Whitespace-only PAT is treated as missing for http and stdio."""
    for transport in ("http", "stdio"):
        servers, warnings = build_mcp_servers_for_full(
            allowlist=[MCP_SERVER_ID_GITHUB],
            environ={"GITHUB_PERSONAL_ACCESS_TOKEN": "  \t  "},
            github_transport=transport,  # type: ignore[arg-type]
        )
        assert servers == {}, f"expected omit for transport={transport!r}"
        assert len(warnings) == 1
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in warnings[0]
        assert _FAKE_GITHUB_TOKEN not in warnings[0]


def test_github_invalid_transport_raises_with_received_and_allowed_set() -> None:
    """Invalid github_transport fails fast with received value and {http, stdio}."""
    with pytest.raises(ValueError) as exc_info:
        build_mcp_servers_for_full(
            allowlist=[MCP_SERVER_ID_GITHUB],
            environ={"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN},
            github_transport="sse",  # type: ignore[arg-type]
        )

    message = str(exc_info.value)
    assert "sse" in message
    assert "http" in message
    assert "stdio" in message


def test_github_http_and_stdio_warnings_never_contain_token_substrings() -> None:
    """Omit warnings on either github transport must never echo the PAT value."""
    for transport in (None, "http", "stdio"):
        _servers, warnings = build_mcp_servers_for_full(
            allowlist=[MCP_SERVER_ID_GITHUB],
            environ={"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
            github_transport=transport,  # type: ignore[arg-type]
        )
        joined = "\n".join(warnings)
        assert _FAKE_GITHUB_TOKEN not in joined
        assert "ghp_fake" not in joined


def test_github_http_bearer_strips_trailing_newline_from_pat() -> None:
    """HTTP emit strips trailing newline from PAT so Bearer header stays clean."""
    servers, warnings = build_mcp_servers_for_full(
        allowlist=[MCP_SERVER_ID_GITHUB],
        environ={"GITHUB_PERSONAL_ACCESS_TOKEN": f"{_FAKE_GITHUB_TOKEN}\n"},
        github_transport="http",
    )

    assert warnings == []
    auth = servers[MCP_SERVER_ID_GITHUB]["headers"]["Authorization"]
    assert auth == f"Bearer {_FAKE_GITHUB_TOKEN}"
    assert "\n" not in auth


def test_allowed_github_transports_is_http_and_stdio() -> None:
    """Public ALLOWED_GITHUB_TRANSPORTS is the single source for {http, stdio}."""
    assert ALLOWED_GITHUB_TRANSPORTS == frozenset({"http", "stdio"})
