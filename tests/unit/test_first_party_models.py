"""Unit tests for first-party model catalog (v1.1.0 Wave G1 / Task 1.6).

Imports ``cursor_agent.first_party_models`` — expected to fail collection until
Task 2.0 adds the module.
"""

from __future__ import annotations

import re

import pytest

from cursor_agent.errors import ConfigError
import cursor_agent.first_party_models as first_party_models_mod
from cursor_agent.first_party_models import (
    COMPOSER_AGENT_MODEL,
    DEFAULT_AGENT_MODEL,
    FIRST_PARTY_AGENT_MODELS,
    WIZARD_MODEL_OTHER_ESCAPE_LABEL,
    format_first_party_model_help,
    recommended_agent_model_ids,
    resolve_wizard_model_choice,
    wizard_model_radio_options,
)

# Same TTY width budget as FIRST_RUN / product_copy tests (PRD-011).
PRD_MAX_LINE_WIDTH = 60


def test_default_agent_model_constant_is_grok_4_5() -> None:
    """DEFAULT_AGENT_MODEL is the confirmed Grok id."""
    assert DEFAULT_AGENT_MODEL == "grok-4.5"


def test_composer_agent_model_constant_is_composer_2_5() -> None:
    """COMPOSER_AGENT_MODEL is the confirmed Composer override id."""
    assert COMPOSER_AGENT_MODEL == "composer-2.5"


def test_composer_agent_model_matches_sole_non_default_catalog_row() -> None:
    """COMPOSER_AGENT_MODEL equals the sole soft-catalog non-default row id."""
    non_defaults = [row for row in FIRST_PARTY_AGENT_MODELS if not row.is_default]
    assert len(non_defaults) == 1
    assert COMPOSER_AGENT_MODEL == non_defaults[0].id


def test_composer_agent_model_distinct_from_default() -> None:
    """Composer override pin must not equal the unset default model."""
    assert COMPOSER_AGENT_MODEL != DEFAULT_AGENT_MODEL


def test_default_agent_model_identity_wrapper_is_removed() -> None:
    """Public default surface is DEFAULT_AGENT_MODEL only (no identity wrapper)."""
    assert not hasattr(first_party_models_mod, "default_agent_model")


def test_first_party_catalog_has_exactly_two_rows() -> None:
    """Soft catalog is Grok (default) + Composer 2.5 only."""
    assert len(FIRST_PARTY_AGENT_MODELS) == 2
    grok, composer = FIRST_PARTY_AGENT_MODELS
    assert grok.id == "grok-4.5"
    assert grok.is_default is True
    assert composer.id == "composer-2.5"
    assert composer.is_default is False
    defaults = [row for row in FIRST_PARTY_AGENT_MODELS if row.is_default]
    assert len(defaults) == 1
    assert defaults[0].id == "grok-4.5"


def test_recommended_agent_model_ids_order_grok_then_composer() -> None:
    """recommended_agent_model_ids lists Grok first, then Composer."""
    assert recommended_agent_model_ids() == ("grok-4.5", "composer-2.5")


def test_wizard_model_indexes_match_catalog_order() -> None:
    """Resolve indexes 1..N match FIRST_PARTY_AGENT_MODELS order (no drift map)."""
    for index, row in enumerate(FIRST_PARTY_AGENT_MODELS, start=1):
        assert resolve_wizard_model_choice(str(index)) == row.id


def test_format_first_party_model_help_includes_ids_and_default() -> None:
    """Flat /model help lists both ids and marks the default."""
    help_text = format_first_party_model_help()
    assert "grok-4.5" in help_text
    assert "composer-2.5" in help_text
    assert "default" in help_text.lower()
    # Keep bare /model help within the same TTY width budget as welcome copy.
    assert max(len(line) for line in help_text.splitlines()) <= PRD_MAX_LINE_WIDTH


def test_wizard_model_radio_options_are_glyph_free_structured_rows() -> None:
    """Catalog exposes glyph-free model rows; chrome owns ●/○ layout."""
    options = wizard_model_radio_options()
    assert options == (
        (1, "Grok 4.5", "grok-4.5         (recommended)", True),
        (2, "Composer 2.5", "composer-2.5", False),
    )
    assert all(glyph not in str(options) for glyph in ("●", "○"))
    assert "Other" in WIZARD_MODEL_OTHER_ESCAPE_LABEL
    assert all(glyph not in WIZARD_MODEL_OTHER_ESCAPE_LABEL for glyph in ("●", "○"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", None),
        ("   ", None),
        ("\t", None),
        ("1", "grok-4.5"),
        ("2", "composer-2.5"),
        ("composer-2.5", "composer-2.5"),
        ("grok-4.5", "grok-4.5"),
        ("some-other-model", "some-other-model"),
    ],
)
def test_resolve_wizard_model_choice_maps_empty_index_and_raw_ids(
    raw: str,
    expected: str | None,
) -> None:
    """Empty → None; 1/2 → catalog ids; opaque ids pass through."""
    assert resolve_wizard_model_choice(raw) == expected


@pytest.mark.parametrize("raw", ["3", "9", "0", "99", "-1", "+1", "01"])
def test_resolve_wizard_model_choice_rejects_out_of_range_index(raw: str) -> None:
    """Out-of-range numeric choice raises ConfigError with received value."""
    with pytest.raises(ConfigError, match=re.escape(raw)) as exc_info:
        resolve_wizard_model_choice(raw)
    message = str(exc_info.value)
    assert raw in message
    assert "expected" in message.lower()


def test_first_party_models_does_not_export_tool_profile_resolve() -> None:
    """Model catalog module must not own wizard tool-profile resolve (Wave C 8.2)."""
    assert not hasattr(first_party_models_mod, "resolve_wizard_tool_profile_choice")
    assert not hasattr(first_party_models_mod, "_WIZARD_TOOL_PROFILE_INDEX_TO_NAME")
