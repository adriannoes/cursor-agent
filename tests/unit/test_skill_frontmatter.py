"""Unit tests for AgentSkills YAML frontmatter helpers.

Hermetic: all paths use ``tmp_path`` only — never real ``~/.cursor/skills/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.skills.skill_frontmatter import (
    frontmatter_prefix_byte_length,
    is_safe_skill_file,
    parse_yaml_frontmatter,
    read_frontmatter_text,
    skill_name_from_frontmatter,
)


def test_is_safe_skill_file_returns_false_when_resolve_raises(
    tmp_path: Path,
) -> None:
    """Missing paths make ``resolve(strict=True)`` raise OSError → False."""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    missing_skill = skills_root / "gone" / "SKILL.md"

    assert is_safe_skill_file(missing_skill, skills_root) is False


def test_is_safe_skill_file_returns_false_when_skills_root_missing(
    tmp_path: Path,
) -> None:
    """Non-existent skills root fails resolve and is treated as unsafe."""
    missing_root = tmp_path / "missing-skills"
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("---\nname: x\n---\n\nBody.\n", encoding="utf-8")

    assert is_safe_skill_file(skill_path, missing_root) is False


def test_is_safe_skill_file_accepts_regular_file_under_root(
    tmp_path: Path,
) -> None:
    """Regular SKILL.md contained by the skills root is safe."""
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "plan"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: plan\n---\n\nBody.\n", encoding="utf-8")

    assert is_safe_skill_file(skill_path, skills_root) is True


def test_is_safe_skill_file_rejects_symlink(tmp_path: Path) -> None:
    """Symlinked SKILL.md paths are never considered safe."""
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    real_file = tmp_path / "outside.md"
    real_file.write_text("outside", encoding="utf-8")
    link_path = skills_root / "SKILL.md"
    link_path.symlink_to(real_file)

    assert is_safe_skill_file(link_path, skills_root) is False


def test_parse_yaml_frontmatter_returns_empty_when_opening_marker_has_suffix() -> None:
    """Text starting with ``---`` but not a bare marker line yields ``{}``.

    WHY: ``startswith("---")`` is true for ``----`` / ``---foo``, yet the first
    line after strip is not exactly ``---``, so parsing must bail early.
    """
    assert parse_yaml_frontmatter("---foo\nname: plan\n---\n") == {}
    assert parse_yaml_frontmatter("----\nname: plan\n---\n") == {}


def test_parse_yaml_frontmatter_returns_empty_without_closing_marker() -> None:
    """Frontmatter without a closing ``---`` line yields ``{}``."""
    assert parse_yaml_frontmatter("---\nname: plan\n") == {}


def test_parse_yaml_frontmatter_returns_empty_when_yaml_is_null() -> None:
    """Empty YAML between markers loads as None and becomes ``{}``."""
    assert parse_yaml_frontmatter("---\n---\n") == {}
    assert parse_yaml_frontmatter("---\n\n---\n") == {}


def test_parse_yaml_frontmatter_rejects_non_mapping_yaml() -> None:
    """Non-mapping YAML documents raise ValueError with the offending value."""
    with pytest.raises(ValueError, match=r"expected mapping"):
        parse_yaml_frontmatter("---\n- item\n---\n")

    with pytest.raises(ValueError, match=r"received 42"):
        parse_yaml_frontmatter("---\n42\n---\n")


def test_parse_yaml_frontmatter_rejects_non_string_name_field() -> None:
    """Non-string ``name`` values raise ValueError naming the field."""
    with pytest.raises(ValueError, match=r"invalid frontmatter field 'name'"):
        parse_yaml_frontmatter("---\nname: 42\n---\n")


def test_parse_yaml_frontmatter_rejects_non_string_description_field() -> None:
    """Non-string ``description`` values raise ValueError naming the field."""
    with pytest.raises(ValueError, match=r"invalid frontmatter field 'description'"):
        parse_yaml_frontmatter("---\nname: plan\ndescription: [a, b]\n---\n")


def test_parse_yaml_frontmatter_parses_string_fields() -> None:
    """Supported string fields are returned as a flat mapping."""
    assert parse_yaml_frontmatter("---\nname: plan\ndescription: Plan work\n---\n") == {
        "name": "plan",
        "description": "Plan work",
    }


def test_parse_yaml_frontmatter_returns_empty_without_opening_marker() -> None:
    """Text that does not start with ``---`` yields ``{}``."""
    assert parse_yaml_frontmatter("name: plan\n") == {}


def test_frontmatter_prefix_byte_length_returns_zero_without_closing_marker(
    tmp_path: Path,
) -> None:
    """Bytes starting with ``---`` but lacking ``\\n---\\n`` report length 0."""
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_bytes(b"---\nname: plan\nbody without closing marker\n")

    assert frontmatter_prefix_byte_length(skill_path) == 0


def test_frontmatter_prefix_byte_length_returns_zero_without_opening_marker(
    tmp_path: Path,
) -> None:
    """Files that do not start with ``---`` report prefix length 0."""
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_bytes(b"no frontmatter here\n")

    assert frontmatter_prefix_byte_length(skill_path) == 0


def test_frontmatter_prefix_byte_length_includes_trailing_blank_lines(
    tmp_path: Path,
) -> None:
    """Prefix length includes the closing marker and following blank lines."""
    skill_path = tmp_path / "SKILL.md"
    content = b"---\nname: plan\n---\n\n\nBody.\n"
    skill_path.write_bytes(content)

    prefix_length = frontmatter_prefix_byte_length(skill_path)
    assert prefix_length > 0
    assert content[:prefix_length].endswith(b"\n\n\n")
    assert content[prefix_length:] == b"Body.\n"


def test_frontmatter_prefix_byte_length_accepts_crlf_closer(tmp_path: Path) -> None:
    """Windows-authored CRLF frontmatter must still yield a positive prefix.

    WHY (PR #69 review): scanner that only looks for ``\\n---\\n`` returns 0 for
    ``---\\r\\n...\\r\\n---\\r\\n``, hiding name/description.
    """
    skill_path = tmp_path / "SKILL.md"
    content = b"---\r\nname: plan\r\ndescription: Plan work\r\n---\r\n\r\nBody.\r\n"
    skill_path.write_bytes(content)

    prefix_length = frontmatter_prefix_byte_length(skill_path)
    assert prefix_length > 0
    assert content[:prefix_length].startswith(b"---")
    assert b"Body." not in content[:prefix_length]

    frontmatter = parse_yaml_frontmatter(read_frontmatter_text(skill_path))
    assert frontmatter == {"name": "plan", "description": "Plan work"}


def test_read_frontmatter_text_returns_empty_without_frontmatter(
    tmp_path: Path,
) -> None:
    """``read_frontmatter_text`` returns empty string when no prefix exists."""
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("Just a body.\n", encoding="utf-8")

    assert read_frontmatter_text(skill_path) == ""


def test_read_frontmatter_text_returns_decoded_prefix(tmp_path: Path) -> None:
    """``read_frontmatter_text`` returns the UTF-8 decoded frontmatter block."""
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("---\nname: plan\n---\n\nBody.\n", encoding="utf-8")

    text = read_frontmatter_text(skill_path)
    assert text.startswith("---\nname: plan\n---")
    assert "Body." not in text


def test_skill_name_from_frontmatter_uses_name_when_present() -> None:
    """Present non-empty ``name`` wins over ``directory_name``."""
    assert (
        skill_name_from_frontmatter(
            {"name": "plan", "description": "x"},
            directory_name="dir-only-slug",
        )
        == "plan"
    )


def test_skill_name_from_frontmatter_strips_whitespace_name() -> None:
    """Whitespace-only ``name`` falls back to ``directory_name``."""
    assert (
        skill_name_from_frontmatter(
            {"name": "   ", "description": "x"},
            directory_name="dir-only-slug",
        )
        == "dir-only-slug"
    )


def test_skill_name_from_frontmatter_falls_back_when_name_absent() -> None:
    """Missing ``name`` key falls back to ``directory_name``."""
    assert (
        skill_name_from_frontmatter(
            {"description": "no name field"},
            directory_name="dir-only-slug",
        )
        == "dir-only-slug"
    )
