"""Unit tests for bundled product skills pack layout and catalog (PRD-016, FR-2, FR-7).

WHY: lock the 14 starter skill paths, frontmatter contracts, size cap, uniqueness,
and ADR-013 denylist before authoring SKILL.md bodies (TDD RED for Wave 1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.cli.command_router import RESERVED_BUILTIN_COMMANDS
from cursor_agent.skills import discovery as discovery_mod
from cursor_agent.skills.discovery import SKILL_CONTENT_MAX_BYTES
from cursor_agent.skills.pack_paths import bundled_skills_pack_root

# Locked catalog from PRD-016 FR-1 / FR-2 (category → skill name).
EXPECTED_SKILLS_PACK_ENTRIES: tuple[tuple[str, str], ...] = (
    ("research", "deep-research"),
    ("research", "brief"),
    ("research", "compare-sources"),
    ("research", "summarize-url"),
    ("software-development", "plan"),
    ("software-development", "debug"),
    ("software-development", "tdd"),
    ("software-development", "spike"),
    ("software-development", "dogfood"),
    ("software-development", "simplify"),
    ("github", "pr-review"),
    ("github", "pr-workflow"),
    ("github", "issues"),
    ("meta", "build-skill"),
)


def _skill_md_path(category: str, skill_name: str) -> Path:
    """Return the expected SKILL.md path under the bundled pack root."""
    return bundled_skills_pack_root() / category / skill_name / "SKILL.md"


def _read_skill_frontmatter(skill_path: Path) -> dict[str, str]:
    """Parse YAML frontmatter via discovery helpers (same contract as listing)."""
    return discovery_mod._parse_yaml_frontmatter(
        discovery_mod._read_frontmatter_text(skill_path)
    )


def test_skills_pack_catalog_has_fourteen_unique_names() -> None:
    """Locked catalog must list exactly 14 skills with unique names."""
    names: list[str] = [skill_name for _, skill_name in EXPECTED_SKILLS_PACK_ENTRIES]
    assert len(EXPECTED_SKILLS_PACK_ENTRIES) == 14, (
        f"expected 14 catalog entries, received {len(EXPECTED_SKILLS_PACK_ENTRIES)}"
    )
    assert len(names) == len(set(names)), (
        f"skill names must be unique across the catalog, "
        f"received duplicates in {names!r}"
    )


def test_skills_pack_filesystem_has_exactly_locked_skill_md_files() -> None:
    """Pack tree must contain exactly the locked 14 SKILL.md paths (no extras)."""
    pack_root: Path = bundled_skills_pack_root()
    on_disk: set[Path] = {path.resolve() for path in pack_root.rglob("SKILL.md")}
    expected: set[Path] = {
        _skill_md_path(category, skill_name).resolve()
        for category, skill_name in EXPECTED_SKILLS_PACK_ENTRIES
    }
    assert on_disk == expected, (
        f"pack SKILL.md set mismatch: "
        f"extra={sorted(on_disk - expected)!r}, "
        f"missing={sorted(expected - on_disk)!r}"
    )


@pytest.mark.parametrize(
    ("category", "skill_name"),
    EXPECTED_SKILLS_PACK_ENTRIES,
    ids=[f"{category}/{name}" for category, name in EXPECTED_SKILLS_PACK_ENTRIES],
)
def test_skills_pack_entry_layout(category: str, skill_name: str) -> None:
    """Each catalog entry must ship a valid, sized SKILL.md with frontmatter.

    Example:
        research/deep-research/SKILL.md must exist with name: deep-research.
    """
    assert skill_name not in RESERVED_BUILTIN_COMMANDS, (
        f"skill name {skill_name!r} collides with ADR-013 reserved builtin "
        f"command; reserved={sorted(RESERVED_BUILTIN_COMMANDS)!r}"
    )

    skill_path: Path = _skill_md_path(category, skill_name)
    assert skill_path.is_file(), (
        f"SKILL.md missing for catalog entry ({category!r}, {skill_name!r}): "
        f"expected file at {skill_path}"
    )

    file_size: int = skill_path.stat().st_size
    assert file_size <= SKILL_CONTENT_MAX_BYTES, (
        f"SKILL.md too large for ({category!r}, {skill_name!r}): "
        f"received {file_size} bytes, expected <= {SKILL_CONTENT_MAX_BYTES}"
    )

    frontmatter: dict[str, str] = _read_skill_frontmatter(skill_path)
    assert frontmatter.get("name") == skill_name, (
        f"frontmatter name mismatch for ({category!r}, {skill_name!r}): "
        f"received {frontmatter.get('name')!r}, expected {skill_name!r}"
    )
    description: str = frontmatter.get("description", "")
    assert description.strip(), (
        f"frontmatter description must be non-empty for "
        f"({category!r}, {skill_name!r}), received {description!r}"
    )
