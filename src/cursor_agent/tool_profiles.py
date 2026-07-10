"""Canonical allowed tool-profile names and wizard profile resolve.

Cycle-free leaf: config writer, tool-profile policy, product_copy options,
and wizard resolve import this module so membership and indexes cannot drift.
"""

from __future__ import annotations

import re
from typing import Final

from cursor_agent.errors import ConfigError

# Ordered wizard radio entries: (profile_name, is_default). Indexes are 1-based.
WIZARD_TOOL_PROFILE_ENTRIES: Final[tuple[tuple[str, bool], ...]] = (
    ("coding", True),
    ("messaging", False),
    ("full", False),
)
"""Canonical wizard order and default flag for tool-profile radio options.

Example:
    >>> WIZARD_TOOL_PROFILE_ENTRIES[0]
    ('coding', True)
"""

WIZARD_TOOL_PROFILE_INDEX_TO_NAME: Final[dict[str, str]] = {
    str(index): name
    for index, (name, _is_default) in enumerate(WIZARD_TOOL_PROFILE_ENTRIES, start=1)
}
"""1-based string indexes → profile names; single source for wizard resolve.

Example:
    >>> WIZARD_TOOL_PROFILE_INDEX_TO_NAME["2"]
    'messaging'
"""

ALLOWED_TOOL_PROFILES: Final[frozenset[str]] = frozenset(
    name for name, _is_default in WIZARD_TOOL_PROFILE_ENTRIES
)
"""Membership set for runtime tool profiles (PRD-012 / ADR-029).

Example:
    >>> "messaging" in ALLOWED_TOOL_PROFILES
    True
    >>> "research" in ALLOWED_TOOL_PROFILES
    False
"""

# Derived from entries so resolve help text cannot drift from indexes/names.
_TOOL_PROFILE_CHOICE_EXPECTED_SHAPE: Final[str] = (
    "empty (default), "
    + ", ".join(
        f"'{index}' ({name})"
        for index, name in WIZARD_TOOL_PROFILE_INDEX_TO_NAME.items()
    )
    + ", or a profile name ("
    + ", ".join(f"'{name}'" for name, _is_default in WIZARD_TOOL_PROFILE_ENTRIES)
    + ")"
)
_SIGNED_OR_DIGIT_INDEX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[+-]?\d+$")


def _looks_like_wizard_numeric_index(stripped: str) -> bool:
    """True when ``stripped`` is a pure integer token (digits, sign, leading zeros)."""
    return _SIGNED_OR_DIGIT_INDEX_PATTERN.fullmatch(stripped) is not None


def resolve_wizard_tool_profile_choice(raw: str) -> str | None:
    """Map wizard tool-profile input to a profile name, ``None``, or raise.

    Empty/whitespace → ``None``. ``1``/``2``/``3`` map to coding/messaging/full.
    Profile names must be members of ``ALLOWED_TOOL_PROFILES``. Invalid choices
    raise ``ConfigError`` mentioning numeric indexes and profile names.

    Example:
        >>> resolve_wizard_tool_profile_choice("2")
        'messaging'
    """
    stripped = raw.strip()
    if not stripped:
        return None
    mapped = WIZARD_TOOL_PROFILE_INDEX_TO_NAME.get(stripped)
    if mapped is not None:
        return mapped
    if _looks_like_wizard_numeric_index(stripped):
        raise ConfigError(
            f"invalid tool_profile choice: received {stripped!r}, "
            f"expected {_TOOL_PROFILE_CHOICE_EXPECTED_SHAPE}",
        )
    if stripped not in ALLOWED_TOOL_PROFILES:
        raise ConfigError(
            f"invalid tool_profile choice: received {stripped!r}, "
            f"expected {_TOOL_PROFILE_CHOICE_EXPECTED_SHAPE}",
        )
    return stripped
