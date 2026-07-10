"""Unit tests for the canonical allowed tool-profile set (Wave C 8.1–8.3)."""

from __future__ import annotations

import re

import pytest

import cursor_agent.config.writer as writer_mod
import cursor_agent.tool_profile_policy as policy_mod
from cursor_agent.config.writer import validate_tool_profile
from cursor_agent.errors import ConfigError
from cursor_agent.product_copy import SETUP_TOOL_PROFILE_OPTIONS
from cursor_agent.tool_profile_policy import mcp_servers_override_for_profile
from cursor_agent.tool_profiles import (
    ALLOWED_TOOL_PROFILES,
    WIZARD_TOOL_PROFILE_INDEX_TO_NAME,
    resolve_wizard_tool_profile_choice,
)


def test_allowed_tool_profiles_is_coding_messaging_full() -> None:
    """Public ALLOWED_TOOL_PROFILES is the single source for {coding, messaging, full}."""
    assert ALLOWED_TOOL_PROFILES == frozenset({"coding", "messaging", "full"})


def test_writer_and_policy_share_allowed_tool_profiles_identity() -> None:
    """Writer and policy membership checks bind the same frozenset object."""
    assert writer_mod.ALLOWED_TOOL_PROFILES is ALLOWED_TOOL_PROFILES
    assert policy_mod.ALLOWED_TOOL_PROFILES is ALLOWED_TOOL_PROFILES


def test_validate_tool_profile_accepts_allowed_members_only() -> None:
    """Writer validation accepts only ALLOWED_TOOL_PROFILES members."""
    for profile in sorted(ALLOWED_TOOL_PROFILES):
        assert validate_tool_profile(profile) == profile
    with pytest.raises(ConfigError, match="invalid tool_profile"):
        validate_tool_profile("research")


def test_mcp_override_rejects_unknown_with_allowed_set() -> None:
    """Policy MCP override error lists the canonical allowed profiles."""
    with pytest.raises(ValueError, match="unsupported tool_profile") as caught:
        mcp_servers_override_for_profile("research")
    for profile in ALLOWED_TOOL_PROFILES:
        assert profile in str(caught.value)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("   ", None),
        ("1", "coding"),
        ("coding", "coding"),
        ("2", "messaging"),
        ("messaging", "messaging"),
        ("3", "full"),
        ("full", "full"),
    ],
)
def test_resolve_wizard_tool_profile_choice_maps_empty_index_and_names(
    raw: str,
    expected: str | None,
) -> None:
    """Empty → None; 1/2/3 and profile names map to ToolProfile values."""
    assert resolve_wizard_tool_profile_choice(raw) == expected


@pytest.mark.parametrize("raw", ["4", "0", "bogus", "admin", "-1", "+1", "01"])
def test_resolve_wizard_tool_profile_choice_rejects_garbage(raw: str) -> None:
    """Garbage profile choice raises ConfigError citing value and 1/2/3 choices."""
    with pytest.raises(ConfigError, match=re.escape(raw)) as exc_info:
        resolve_wizard_tool_profile_choice(raw)
    message = str(exc_info.value)
    assert raw in message
    assert "1" in message and "2" in message and "3" in message
    assert (
        "coding" in message
        or "messaging" in message
        or "full" in message
        or "tool_profile" in message.lower()
    )


def test_setup_tool_profile_options_indexes_match_wizard_resolve_map() -> None:
    """SETUP_TOOL_PROFILE_OPTIONS indexes must not drift from the wizard resolve map."""
    options_index_to_name = {
        str(index): profile_name
        for index, profile_name, _label, _is_default in SETUP_TOOL_PROFILE_OPTIONS
    }
    assert options_index_to_name == WIZARD_TOOL_PROFILE_INDEX_TO_NAME
    for index, profile_name, _label, _is_default in SETUP_TOOL_PROFILE_OPTIONS:
        assert resolve_wizard_tool_profile_choice(str(index)) == profile_name


def test_tool_profile_choice_expected_shape_derives_from_entries() -> None:
    """ConfigError expected-shape text lists every wizard index and profile name."""
    with pytest.raises(ConfigError) as caught:
        resolve_wizard_tool_profile_choice("bogus")
    message = str(caught.value)
    for index, name in WIZARD_TOOL_PROFILE_INDEX_TO_NAME.items():
        assert f"'{index}' ({name})" in message
        assert f"'{name}'" in message
