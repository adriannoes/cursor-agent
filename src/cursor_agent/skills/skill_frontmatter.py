"""Public helpers for AgentSkills YAML frontmatter and SKILL.md path safety.

WHY: seed and discovery share symlink/frontmatter policy through one stable API
so both paths refuse the same unsafe SKILL.md layouts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import yaml

SKILL_FILENAME: Final[str] = "SKILL.md"
_FRONTMATTER_MAX_BYTES: Final[int] = 8192


def is_safe_skill_file(skill_path: Path, skills_root: Path) -> bool:
    """Return True only for regular SKILL.md files contained by the skills root.

    Example:
        >>> from pathlib import Path
        >>> # is_safe_skill_file(Path("skills/plan/SKILL.md"), Path("skills"))
    """
    if skill_path.is_symlink():
        return False
    try:
        resolved_root = skills_root.resolve(strict=True)
        resolved_skill_path = skill_path.resolve(strict=True)
    except OSError:
        return False
    return resolved_skill_path.is_file() and resolved_skill_path.is_relative_to(
        resolved_root
    )


def read_frontmatter_text(path: Path) -> str:
    """Read and decode only the YAML frontmatter block, if present.

    Example:
        >>> from pathlib import Path
        >>> # read_frontmatter_text(Path("skills/plan/SKILL.md"))
    """
    prefix_byte_length = frontmatter_prefix_byte_length(path)
    if prefix_byte_length == 0:
        return ""
    with path.open("rb") as handle:
        raw = handle.read(prefix_byte_length)
    return raw.decode("utf-8")


def parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Parse supported string fields from YAML frontmatter.

    Example:
        >>> parse_yaml_frontmatter("---\\nname: plan\\n---\\n")
        {'name': 'plan'}
    """
    if not text.startswith("---"):
        return {}

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        return {}

    loaded = yaml.safe_load("\n".join(lines[1:closing_index]))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"invalid frontmatter: received {loaded!r}, expected mapping"
        raise ValueError(msg)
    return _string_frontmatter_fields(loaded)


def skill_name_from_frontmatter(
    frontmatter: dict[str, str],
    *,
    directory_name: str,
) -> str:
    """Return frontmatter ``name`` (stripped) or fall back to ``directory_name``.

    Example:
        >>> skill_name_from_frontmatter({"name": "plan"}, directory_name="plan-dir")
        'plan'
    """
    return frontmatter.get("name", "").strip() or directory_name


def frontmatter_prefix_byte_length(skill_path: Path) -> int:
    """Return the UTF-8 byte length of YAML frontmatter plus its body separator.

    Example:
        >>> from pathlib import Path
        >>> # frontmatter_prefix_byte_length(Path("skills/plan/SKILL.md"))
    """
    with skill_path.open("rb") as handle:
        head_bytes = handle.read(_FRONTMATTER_MAX_BYTES)

    if not head_bytes.startswith(b"---"):
        return 0

    # WHY: Windows-authored SKILL.md uses CRLF; LF-only closer left name/description
    # invisible (PR #69 Should Fix). Prefer the earliest valid closer.
    closing_markers = (b"\n---\n", b"\r\n---\r\n", b"\n---\r\n", b"\r\n---\n")
    closing_index = -1
    closing_marker = b""
    for marker in closing_markers:
        index = head_bytes.find(marker, 3)
        if index == -1:
            continue
        if closing_index == -1 or index < closing_index:
            closing_index = index
            closing_marker = marker
    if closing_index == -1:
        return 0

    prefix_end = closing_index + len(closing_marker)
    while prefix_end < len(head_bytes) and head_bytes[prefix_end : prefix_end + 1] in {
        b"\n",
        b"\r",
    }:
        prefix_end += 1
    return prefix_end


def _string_frontmatter_fields(frontmatter: dict[Any, Any]) -> dict[str, str]:
    """Return normalized string-only frontmatter fields used by skills."""
    fields: dict[str, str] = {}
    for key in ("name", "description"):
        value = frontmatter.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            msg = (
                f"invalid frontmatter field {key!r}: received {value!r}, "
                "expected string"
            )
            raise ValueError(msg)
        fields[key] = value
    return fields
