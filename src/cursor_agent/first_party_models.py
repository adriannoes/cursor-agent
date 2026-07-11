"""First-party Cursor agent model catalog and wizard model resolve (v1.1.0).

Soft catalog only: recommended ids for UX/docs. Do not call these from
``load_config`` to reject unknown model strings (D8). Bare string ids only —
no ``ModelSelection`` / fast params (D12). Wizard chrome wiring is G3.
Tool-profile wizard resolve lives in ``tool_profiles`` (Wave C 8.2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from cursor_agent.errors import ConfigError

DEFAULT_AGENT_MODEL: Final[str] = "grok-4.5"

_SIGNED_OR_DIGIT_INDEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True, slots=True)
class FirstPartyAgentModel:
    """One curated first-party agent model row for UX and docs.

    Example:
        >>> FirstPartyAgentModel(id="grok-4.5", label="Grok 4.5", is_default=True).id
        'grok-4.5'
    """

    id: str
    label: str
    is_default: bool


FIRST_PARTY_AGENT_MODELS: Final[tuple[FirstPartyAgentModel, ...]] = (
    FirstPartyAgentModel(id="grok-4.5", label="Grok 4.5", is_default=True),
    FirstPartyAgentModel(id="composer-2.5", label="Composer 2.5", is_default=False),
)

# Soft-catalog non-default pin for override fixtures / D5 (not load_config).
COMPOSER_AGENT_MODEL: Final[str] = next(
    row.id for row in FIRST_PARTY_AGENT_MODELS if not row.is_default
)

# Derived from catalog so display (enumerate) and resolve stay in sync.
_WIZARD_MODEL_INDEX_TO_ID: Final[dict[str, str]] = {
    str(index): row.id for index, row in enumerate(FIRST_PARTY_AGENT_MODELS, start=1)
}
_MODEL_CHOICE_EXPECTED_SHAPE: Final[str] = (
    "empty (default), "
    + ", ".join(
        f"'{index}' ({row.label})"
        for index, row in enumerate(FIRST_PARTY_AGENT_MODELS, start=1)
    )
    + ", or a Cursor SDK model id"
)


def recommended_agent_model_ids() -> tuple[str, ...]:
    """Return recommended first-party model ids in catalog order.

    Example:
        >>> recommended_agent_model_ids()
        ('grok-4.5', 'composer-2.5')
    """
    return tuple(row.id for row in FIRST_PARTY_AGENT_MODELS)


def format_first_party_model_help() -> str:
    """Return flat ``/model`` help listing first-party options (no wizard glyphs).

    Example:
        >>> "grok-4.5" in format_first_party_model_help()
        True
    """
    lines: list[str] = [
        "Usage: /model <id>",
        "First-party options:",
    ]
    for row in FIRST_PARTY_AGENT_MODELS:
        suffix = " (default)" if row.is_default else ""
        lines.append(f"  {row.id:<14} {row.label}{suffix}")
    lines.append("Other Cursor SDK model ids are accepted.")
    return "\n".join(lines)


# Glyph-free Other row; setup_wizard_chrome owns ○ / spacing (D10–D11).
WIZARD_MODEL_OTHER_ESCAPE_LABEL: Final[str] = "Other — type a Cursor SDK model id"
# Keep recommended-id padding aligned with the locked Proposal B mock.
_WIZARD_MODEL_RECOMMENDED_DETAIL_SUFFIX: Final[str] = "         (recommended)"


def wizard_model_radio_options() -> tuple[tuple[int, str, str, bool], ...]:
    """Return glyph-free numbered model rows for chrome radio rendering.

    Each row is ``(index, label, option_detail, selected)``. Callers must render
    glyphs via ``setup_wizard_chrome`` — this catalog stays soft and glyph-free.

    Example:
        >>> wizard_model_radio_options()[0][2].startswith("grok-4.5")
        True
    """
    rows: list[tuple[int, str, str, bool]] = []
    for index, row in enumerate(FIRST_PARTY_AGENT_MODELS, start=1):
        detail = (
            f"{row.id}{_WIZARD_MODEL_RECOMMENDED_DETAIL_SUFFIX}"
            if row.is_default
            else row.id
        )
        rows.append((index, row.label, detail, row.is_default))
    return tuple(rows)


def _looks_like_wizard_numeric_index(stripped: str) -> bool:
    """True when ``stripped`` is a pure integer token (digits, sign, leading zeros)."""
    return _SIGNED_OR_DIGIT_INDEX_PATTERN.fullmatch(stripped) is not None


def resolve_wizard_model_choice(raw: str) -> str | None:
    """Map wizard model input to a model id, ``None`` (omit), or raise.

    Empty/whitespace → ``None``. ``1``/``2`` → catalog ids. Other non-index
    strings pass through (soft catalog). Integer-looking indexes outside
    ``{1,2}`` (including negatives and leading-zero forms) raise ``ConfigError``.

    Example:
        >>> resolve_wizard_model_choice("1")
        'grok-4.5'
    """
    stripped = raw.strip()
    if not stripped:
        return None
    mapped = _WIZARD_MODEL_INDEX_TO_ID.get(stripped)
    if mapped is not None:
        return mapped
    if _looks_like_wizard_numeric_index(stripped):
        raise ConfigError(
            f"invalid model choice: received {stripped!r}, "
            f"expected {_MODEL_CHOICE_EXPECTED_SHAPE}",
        )
    return stripped
