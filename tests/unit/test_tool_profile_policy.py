"""Unit tests for canonical tool profile policy."""

from __future__ import annotations

import logging

import pytest
from _pytest.logging import LogCaptureFixture

from cursor_agent.mcp_registry import (
    MCP_SERVER_ID_BRAVE_SEARCH,
    MCP_SERVER_ID_GITHUB,
    MCP_SERVER_ID_PLAYWRIGHT,
)
from cursor_agent.tool_profile_policy import (
    clear_mcp_omit_warning_cache_for_tests,
    effective_tool_profile,
    mcp_servers_override_for_profile,
    passes_mcp_servers_on_resume,
    requires_messaging_hooks,
    resolve_mcp_servers,
    sandbox_enabled,
)

_FAKE_GITHUB_TOKEN = "ghp_fake_policy_token_DO_NOT_LEAK"
_FAKE_BRAVE_KEY = "BSA_fake_policy_key_DO_NOT_LEAK"


@pytest.fixture(autouse=True)
def _reset_mcp_omit_warning_cache() -> None:
    """Keep Q2 warn-once state isolated across policy unit tests."""
    clear_mcp_omit_warning_cache_for_tests()


def test_effective_tool_profile_messaging_wins_over_coding() -> None:
    """Messaging must win when either config or session is messaging."""
    assert effective_tool_profile("messaging", "coding") == "messaging"
    assert effective_tool_profile("coding", "messaging") == "messaging"


def test_effective_tool_profile_keeps_coding_when_both_coding() -> None:
    """Coding remains when neither side requests messaging."""
    assert effective_tool_profile("coding", "coding") == "coding"


def test_effective_tool_profile_session_wins_among_coding_and_full() -> None:
    """Among coding/full, session profile wins; messaging still dominates."""
    assert effective_tool_profile("full", "coding") == "coding"
    assert effective_tool_profile("coding", "full") == "full"
    assert effective_tool_profile("full", "full") == "full"
    assert effective_tool_profile("messaging", "full") == "messaging"
    assert effective_tool_profile("full", "messaging") == "messaging"


def test_requires_messaging_hooks_follows_effective_profile() -> None:
    """Hook deploy is required only for the effective messaging profile."""
    assert requires_messaging_hooks("messaging", "coding") is True
    assert requires_messaging_hooks("coding", "messaging") is True
    assert requires_messaging_hooks("coding", "coding") is False
    assert requires_messaging_hooks("full", "coding") is False
    assert requires_messaging_hooks("coding", "full") is False


def test_mcp_servers_override_for_profile_coding_preserves_sdk_settings() -> None:
    """Coding create must omit mcp_servers so project/user MCP settings apply."""
    assert mcp_servers_override_for_profile("coding") is None


def test_mcp_servers_override_for_profile_messaging_forces_empty_map() -> None:
    """Messaging create must pass an explicit empty MCP map."""
    assert mcp_servers_override_for_profile("messaging") == {}


def test_mcp_servers_override_for_profile_messaging_ignores_allowlist() -> None:
    """Messaging empty-map invariant must ignore any allowlist argument."""
    assert (
        mcp_servers_override_for_profile(
            "messaging",
            allowlist=[MCP_SERVER_ID_GITHUB],
            environ={"GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN},
        )
        == {}
    )


def test_mcp_servers_override_for_profile_full_returns_curated_map() -> None:
    """Full override returns curated registry servers when env tokens are present."""
    environ = {
        "GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN,
        "BRAVE_API_KEY": _FAKE_BRAVE_KEY,
    }
    override = mcp_servers_override_for_profile("full", environ=environ)

    assert override is not None
    assert set(override) == {
        MCP_SERVER_ID_GITHUB,
        MCP_SERVER_ID_BRAVE_SEARCH,
        MCP_SERVER_ID_PLAYWRIGHT,
    }
    assert override[MCP_SERVER_ID_PLAYWRIGHT]["command"] == "npx"


def test_mcp_servers_override_for_profile_full_empty_environ_keeps_playwright() -> None:
    """Full with empty environ still includes playwright (no required env)."""
    override = mcp_servers_override_for_profile("full", environ={})

    assert override is not None
    assert MCP_SERVER_ID_PLAYWRIGHT in override
    assert MCP_SERVER_ID_GITHUB not in override
    assert MCP_SERVER_ID_BRAVE_SEARCH not in override


def test_full_missing_env_warns_once_across_repeated_resolutions(
    caplog: LogCaptureFixture,
) -> None:
    """Q2: omit+warn once — create/resume must not spam the same omit warning."""
    with caplog.at_level(logging.WARNING, logger="cursor_agent.tool_profile_policy"):
        first = mcp_servers_override_for_profile("full", environ={})
        second = mcp_servers_override_for_profile("full", environ={})

    assert first is not None
    assert second is not None
    omit_records = [
        record
        for record in caplog.records
        if "omitting MCP server" in record.getMessage()
    ]
    github_warnings = [
        record for record in omit_records if MCP_SERVER_ID_GITHUB in record.getMessage()
    ]
    brave_warnings = [
        record
        for record in omit_records
        if MCP_SERVER_ID_BRAVE_SEARCH in record.getMessage()
    ]
    assert len(github_warnings) == 1
    assert len(brave_warnings) == 1
    joined = "\n".join(record.getMessage() for record in omit_records)
    assert _FAKE_GITHUB_TOKEN not in joined
    assert _FAKE_BRAVE_KEY not in joined


def test_mcp_servers_override_for_profile_rejects_unknown() -> None:
    """Unsupported profiles must fail fast with received value and allowed set."""
    with pytest.raises(ValueError) as exc_info:
        mcp_servers_override_for_profile("unknown")

    message = str(exc_info.value)
    assert "unsupported tool_profile" in message
    assert "unknown" in message
    assert "coding" in message
    assert "messaging" in message
    assert "full" in message


def test_resolve_mcp_servers_returns_empty_maps() -> None:
    """Legacy API collapses None (coding) and {} (messaging) to empty dict."""
    assert resolve_mcp_servers("coding") == {}
    assert resolve_mcp_servers("messaging") == {}


def test_resolve_mcp_servers_full_matches_override() -> None:
    """Legacy resolve_mcp_servers('full') returns the same dict as the override."""
    environ = {
        "GITHUB_PERSONAL_ACCESS_TOKEN": _FAKE_GITHUB_TOKEN,
        "BRAVE_API_KEY": _FAKE_BRAVE_KEY,
    }
    override = mcp_servers_override_for_profile("full", environ=environ)
    assert resolve_mcp_servers("full", environ=environ) == override


def test_resolve_mcp_servers_rejects_unknown_profile() -> None:
    """Legacy API propagates unsupported profile errors from override helper."""
    with pytest.raises(ValueError) as exc_info:
        resolve_mcp_servers("unknown")

    message = str(exc_info.value)
    assert "unsupported tool_profile" in message
    assert "full" in message


def test_sandbox_enabled_only_for_messaging() -> None:
    """Sandbox is enabled only for messaging profile."""
    assert sandbox_enabled("messaging") is True
    assert sandbox_enabled("coding") is False
    assert sandbox_enabled("full") is False


def test_passes_mcp_servers_on_resume_coding_omits_override() -> None:
    """Coding resume must omit mcp_servers so SDK/project MCP settings apply."""
    assert passes_mcp_servers_on_resume("coding") is False


def test_passes_mcp_servers_on_resume_messaging_injects_empty_map() -> None:
    """Messaging resume must pass explicit empty mcp_servers for defense in depth."""
    assert passes_mcp_servers_on_resume("messaging") is True


def test_passes_mcp_servers_on_resume_full_reinjects() -> None:
    """Full resume must re-inject curated mcp_servers (same posture as messaging)."""
    assert passes_mcp_servers_on_resume("full") is True
