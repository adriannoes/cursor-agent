"""Unit tests for skill discovery from workspace and user roots (PRD-009, FR-1, FR-6)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.skills.discovery import (
    SKILL_CONTENT_MAX_BYTES,
    SkillDiscovery,
    SkillEntry,
    skill_discovery_from_config,
)

SkillSource = Literal["project", "user"]


def _write_bytes(path: Path, byte_count: int, fill: str = "a") -> None:
    """Write exactly ``byte_count`` UTF-8 bytes using a single-byte fill character."""
    if len(fill.encode("utf-8")) != 1:
        raise ValueError(
            f"fill must be a single UTF-8 byte character, received {fill!r}"
        )
    path.write_text(fill * byte_count, encoding="utf-8")


def _project_skills_root(workspace: Path) -> Path:
    """Return the project skills directory under an injectable workspace cwd."""
    root = workspace / ".cursor" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_skill_md(
    skills_root: Path,
    relative_dir: str,
    *,
    body: str = "Skill body content.",
    name: str | None = None,
    description: str | None = None,
    include_frontmatter: bool = True,
) -> Path:
    """Create ``relative_dir/SKILL.md`` under a skills root with optional YAML frontmatter."""
    skill_dir = skills_root / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"

    if not include_frontmatter:
        skill_path.write_text(body, encoding="utf-8")
        return skill_path

    frontmatter_lines = ["---"]
    if name is not None:
        frontmatter_lines.append(f"name: {name}")
    if description is not None:
        frontmatter_lines.append(f"description: {description}")
    frontmatter_lines.append("---")
    skill_path.write_text(
        "\n".join(frontmatter_lines) + f"\n\n{body}", encoding="utf-8"
    )
    return skill_path


def _load_discovery_config(
    tmp_path: Path,
    *,
    workspace: Path,
    setting_sources: list[str] | None = None,
) -> CursorAgentConfig:
    """Build config pointing ``runtime.local.cwd`` at an injectable workspace."""
    local: dict[str, object] = {"cwd": str(workspace)}
    if setting_sources is not None:
        local["setting_sources"] = setting_sources
    return load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={"runtime": {"local": local}},
    )


def _discovery_from_fixtures(
    tmp_path: Path,
    *,
    workspace: Path,
    user_skills_root: Path,
    setting_sources: list[str] | None = None,
) -> SkillDiscovery:
    """Construct discovery with injectable project workspace and user skills roots."""
    config = _load_discovery_config(
        tmp_path,
        workspace=workspace,
        setting_sources=setting_sources,
    )
    return skill_discovery_from_config(
        config,
        override_workspace=workspace,
        override_user_skills=user_skills_root,
    )


def _entry_by_name(skills: list[SkillEntry], name: str) -> SkillEntry:
    """Return the single skill entry matching ``name`` or fail the test."""
    matches = [skill for skill in skills if skill.name == name]
    assert len(matches) == 1, f"expected one skill named {name!r}, found {matches!r}"
    return matches[0]


def test_single_project_skill_is_discovered(tmp_path: Path) -> None:
    """FR-1: a flat ``SKILL.md`` under project ``.cursor/skills/`` is listed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "canvas",
        name="canvas",
        description="Rich layout artifact skill.",
        body="Create a canvas when output benefits from visual layout.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    skills = discovery.list_skills()

    assert len(skills) == 1
    entry = skills[0]
    assert entry.name == "canvas"
    assert entry.description == "Rich layout artifact skill."
    assert entry.source == "project"
    assert entry.path == "canvas/SKILL.md"
    assert "Create a canvas" in entry.content
    assert discovery.get_skill("canvas") == entry


def test_nested_category_skill_md_is_discovered(tmp_path: Path) -> None:
    """FR-1: ``SKILL.md`` files nested in subfolders are discovered for organization."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "testing/tdd",
        name="test-driven-development",
        description="Red-green-refactor workflow.",
        body="Write the failing test first.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    entry = _entry_by_name(discovery.list_skills(), "test-driven-development")

    assert entry.source == "project"
    assert entry.path == "testing/tdd/SKILL.md"
    assert entry.description == "Red-green-refactor workflow."
    assert "failing test first" in entry.content


def test_missing_frontmatter_description_defaults_to_empty(tmp_path: Path) -> None:
    """Listing uses an empty description when frontmatter omits ``description``."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "no-description",
        name="no-description",
        description=None,
        body="Body without a description field.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    entry = _entry_by_name(discovery.list_skills(), "no-description")

    assert entry.description == ""
    assert "Body without a description field." in entry.content


def test_project_wins_over_user_on_name_collision(tmp_path: Path) -> None:
    """Precedence: ``project`` source wins when the same skill ``name`` exists in both roots."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "user-skills"
    user_skills_root.mkdir()

    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "shared-name",
        name="shared-skill",
        description="Project copy.",
        body="Project skill body.",
    )
    _write_skill_md(
        user_skills_root,
        "shared-name",
        name="shared-skill",
        description="User copy.",
        body="User skill body.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=user_skills_root,
        setting_sources=["project", "user"],
    )
    skills = discovery.list_skills()

    assert [skill.name for skill in skills] == ["shared-skill"]
    entry = skills[0]
    assert entry.source == "project"
    assert entry.description == "Project copy."
    assert entry.path == "shared-name/SKILL.md"
    assert "Project skill body." in entry.content
    assert "User skill body." not in entry.content


def test_empty_directories_are_ignored(tmp_path: Path) -> None:
    """Empty folders under skills roots do not produce placeholder skill entries."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "user-skills"
    user_skills_root.mkdir()

    project_root = _project_skills_root(workspace)
    (project_root / "empty-category").mkdir()
    (project_root / "nested" / "also-empty").mkdir(parents=True)
    (user_skills_root / "user-empty").mkdir()

    _write_skill_md(
        project_root,
        "real-skill",
        name="real-skill",
        description="Only real skill.",
        body="Real content.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=user_skills_root,
        setting_sources=["project", "user"],
    )
    skills = discovery.list_skills()

    assert len(skills) == 1
    assert skills[0].name == "real-skill"


def test_list_skills_sorted_alphabetically_by_name(tmp_path: Path) -> None:
    """``/skills`` contract: discovery returns skills sorted by name."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    for skill_name in ("zebra", "alpha", "middle"):
        _write_skill_md(
            project_root,
            skill_name,
            name=skill_name,
            description=f"{skill_name} skill",
            body=f"{skill_name} body",
        )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )

    assert [skill.name for skill in discovery.list_skills()] == [
        "alpha",
        "middle",
        "zebra",
    ]


def test_oversized_skill_md_truncates_from_end_preserving_tail(tmp_path: Path) -> None:
    """Skill budget: SKILL.md content over 32 KB keeps the tail within the cap."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    skill_dir = project_root / "huge-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"

    tail = "SKILL_TAIL_MARKER"
    frontmatter = "---\nname: huge-skill\ndescription: Oversized fixture.\n---\n\n"
    body_prefix = "x" * (SKILL_CONTENT_MAX_BYTES + 5000)
    skill_path.write_text(frontmatter + body_prefix + tail, encoding="utf-8")

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    entry = _entry_by_name(discovery.list_skills(), "huge-skill")

    assert len(entry.content.encode("utf-8")) <= SKILL_CONTENT_MAX_BYTES
    assert entry.content.endswith(tail)
    assert not entry.content.startswith("x" * 100)


def test_frontmatter_name_overrides_directory_name(tmp_path: Path) -> None:
    """Frontmatter ``name`` is the canonical skill identifier, not the directory name."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "directory-name",
        name="canonical-name",
        description="Name comes from frontmatter.",
        body="Canonical skill body.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    skills = discovery.list_skills()

    assert [skill.name for skill in skills] == ["canonical-name"]
    assert discovery.get_skill("directory-name") is None
    assert discovery.get_skill("canonical-name") is not None


def test_missing_frontmatter_name_falls_back_to_directory(tmp_path: Path) -> None:
    """When frontmatter omits ``name``, the parent directory name is used."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "fallback-name",
        name=None,
        description="Directory fallback.",
        body="Fallback body.",
        include_frontmatter=True,
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    entry = _entry_by_name(discovery.list_skills(), "fallback-name")

    assert entry.path == "fallback-name/SKILL.md"
    assert entry.description == "Directory fallback."
    assert discovery.get_skill("fallback-name") == entry


def test_user_skill_discovered_when_setting_sources_include_user(
    tmp_path: Path,
) -> None:
    """User-level skills are listed with ``source='user'`` when configured."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "user-skills"
    user_skills_root.mkdir()
    _write_skill_md(
        user_skills_root,
        "personal-skill",
        name="personal-skill",
        description="User-level playbook.",
        body="Personal skill body.",
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=user_skills_root,
        setting_sources=["project", "user"],
    )
    entry = _entry_by_name(discovery.list_skills(), "personal-skill")

    assert entry.source == "user"
    assert entry.path == "personal-skill/SKILL.md"
    assert "Personal skill body." in entry.content


def test_discovery_never_reads_operator_home_or_real_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injectable overrides isolate discovery from the operator home and real cwd."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "user-skills"
    user_skills_root.mkdir()
    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "isolated",
        name="isolated",
        description="Only from injectable roots.",
        body="Isolated body.",
    )

    fake_home = tmp_path / "must-not-be-used"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=user_skills_root,
    )
    entry = _entry_by_name(discovery.list_skills(), "isolated")

    assert entry.source == "project"
    assert not fake_home.exists()


def test_skill_content_max_bytes_constant_is_thirty_two_kb() -> None:
    """MVP skill cap is 32 KB, separate from the 8 KB memory budget."""
    assert SKILL_CONTENT_MAX_BYTES == 32 * 1024


def test_oversized_skill_uses_bounded_tail_read(tmp_path: Path) -> None:
    """Very large SKILL.md files truncate from the tail without loading the full file."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    skill_dir = project_root / "massive-skill"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"

    tail = "HUGE_SKILL_TAIL_MARKER"
    frontmatter = "---\nname: massive-skill\ndescription: Huge fixture.\n---\n\n"
    skill_path.write_bytes(
        frontmatter.encode("utf-8") + (b"y" * (2 * 1024 * 1024)) + tail.encode("utf-8")
    )

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )
    entry = _entry_by_name(discovery.list_skills(), "massive-skill")

    assert len(entry.content.encode("utf-8")) <= SKILL_CONTENT_MAX_BYTES
    assert entry.content.endswith(tail)


def test_skill_symlink_outside_root_is_ignored(tmp_path: Path) -> None:
    """A workspace skill symlink must not expose files outside the skills root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_root = _project_skills_root(workspace)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_skill = outside_dir / "SKILL.md"
    outside_skill.write_text(
        "---\nname: leaked\ndescription: Outside root.\n---\n\nsecret body",
        encoding="utf-8",
    )
    symlink_dir = project_root / "leaked"
    symlink_dir.mkdir()
    (symlink_dir / "SKILL.md").symlink_to(outside_skill)

    discovery = _discovery_from_fixtures(
        tmp_path,
        workspace=workspace,
        user_skills_root=tmp_path / "user-skills",
    )

    assert discovery.list_skills() == []
