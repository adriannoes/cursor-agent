"""First-party Cursor agent model catalog and wizard resolve helpers (v1.1.0).

Soft catalog only: recommended ids for UX/docs. Do not call these from
``load_config`` to reject unknown model strings (D8). Bare string ids only —
no ``ModelSelection`` / fast params (D12). Wizard chrome wiring is G3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from cursor_agent.errors import ConfigError

DEFAULT_AGENT_MODEL: Final[str] = "grok-4.5"

_WIZARD_TOOL_PROFILE_INDEX_TO_NAME: Final[dict[str, str]] = {
    "1": "coding",
    "2": "messaging",
    "3": "full",
}
_TOOL_PROFILE_CHOICE_EXPECTED_SHAPE: Final[str] = (
    "empty (default), '1' (coding), '2' (messaging), '3' (full), "
    "or a profile name ('coding', 'messaging', 'full')"
)
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


def default_agent_model() -> str:
    """Return the unset-default agent model id.

    Example:
        >>> default_agent_model()
        'grok-4.5'
    """
    return DEFAULT_AGENT_MODEL


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


def format_wizard_model_options() -> list[str]:
    """Return Proposal B model-step body lines for wizard chrome to wrap.

    Example:
        >>> any("grok-4.5" in line for line in format_wizard_model_options())
        True
    """
    lines: list[str] = []
    for index, row in enumerate(FIRST_PARTY_AGENT_MODELS, start=1):
        marker = "●" if row.is_default else "○"
        recommended = "         (recommended)" if row.is_default else ""
        lines.append(
            f"{marker} {index}  {row.label:<14} {row.id}{recommended}".rstrip()
        )
    lines.append("○    Other — type a Cursor SDK model id")
    return lines


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


def resolve_wizard_tool_profile_choice(raw: str) -> str | None:
    """Map wizard tool-profile input to a profile name, ``None``, or raise.

    Empty/whitespace → ``None``. ``1``/``2``/``3`` map to coding/messaging/full.
    Profile names are validated via ``validate_tool_profile``. Invalid choices
    raise ``ConfigError`` mentioning numeric indexes and profile names.

    Example:
        >>> resolve_wizard_tool_profile_choice("2")
        'messaging'
    """
    stripped = raw.strip()
    if not stripped:
        return None
    mapped = _WIZARD_TOOL_PROFILE_INDEX_TO_NAME.get(stripped)
    if mapped is not None:
        return mapped
    if _looks_like_wizard_numeric_index(stripped):
        raise ConfigError(
            f"invalid tool_profile choice: received {stripped!r}, "
            f"expected {_TOOL_PROFILE_CHOICE_EXPECTED_SHAPE}",
        )
    # Deferred: writer → loader → first_party_models would cycle at import time.
    from cursor_agent.config.writer import validate_tool_profile

    try:
        return validate_tool_profile(stripped)
    except ConfigError as exc:
        raise ConfigError(
            f"invalid tool_profile choice: received {stripped!r}, "
            f"expected {_TOOL_PROFILE_CHOICE_EXPECTED_SHAPE}",
        ) from exc
