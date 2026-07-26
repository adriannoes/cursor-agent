"""Unit tests for bundled pack and project/user skills roots (PRD-016, FR-1, FR-3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.monkeypatch import MonkeyPatch

from cursor_agent.config.loader import load_config
from cursor_agent.errors import ConfigError
from cursor_agent.skills import discovery as discovery_mod
from cursor_agent.skills import pack_paths
from cursor_agent.skills.discovery import skill_discovery_from_config
from cursor_agent.skills.pack_paths import (
    bundled_skills_pack_root,
    project_skills_root,
    user_skills_root,
)


def test_bundled_skills_pack_root_returns_existing_directory() -> None:
    """bundled_skills_pack_root must resolve to an on-disk directory."""
    pack_root: Path = bundled_skills_pack_root()
    assert pack_root.is_dir(), (
        f"bundled_skills_pack_root must return an existing directory, "
        f"received {pack_root!r}"
    )


def test_bundled_skills_pack_root_is_not_python_skills_package() -> None:
    """Pack root must not collide with cursor_agent.skills (Q5 / discovery.py)."""
    pack_root: Path = bundled_skills_pack_root().resolve()
    python_skills_package: Path = Path(discovery_mod.__file__).resolve().parent
    assert (python_skills_package / "discovery.py").is_file(), (
        f"expected discovery.py under Python skills package, "
        f"received package={python_skills_package!r}"
    )
    assert pack_root != python_skills_package, (
        f"bundled pack root must not be the Python package dir that contains "
        f"discovery.py: pack_root={pack_root!r}, "
        f"python_skills_package={python_skills_package!r}"
    )


def test_bundled_skills_pack_root_prefers_packaged_over_checkout(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """When both candidates exist, packaged skills_pack wins (Q5 dual resolve)."""
    packaged: Path = tmp_path / "skills_pack"
    checkout: Path = tmp_path / "checkout_skills"
    packaged.mkdir()
    checkout.mkdir()
    monkeypatch.setattr(pack_paths, "_packaged_skills_pack_dir", lambda: packaged)
    monkeypatch.setattr(pack_paths, "_checkout_skills_pack_dir", lambda: checkout)

    resolved: Path = bundled_skills_pack_root()
    assert resolved == packaged.resolve(), (
        f"expected packaged-first resolve, received {resolved!r}, "
        f"expected {packaged.resolve()!r}"
    )


def test_bundled_skills_pack_root_falls_back_to_checkout_when_packaged_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """When packaged skills_pack is absent, resolve checkout skills/ (dual resolve)."""
    packaged: Path = tmp_path / "missing_packaged"
    checkout: Path = tmp_path / "checkout_skills"
    checkout.mkdir()
    monkeypatch.setattr(pack_paths, "_packaged_skills_pack_dir", lambda: packaged)
    monkeypatch.setattr(pack_paths, "_checkout_skills_pack_dir", lambda: checkout)

    resolved: Path = bundled_skills_pack_root()
    assert resolved == checkout.resolve(), (
        f"expected checkout fallback, received {resolved!r}, "
        f"expected {checkout.resolve()!r}"
    )


def test_bundled_skills_pack_root_raises_when_both_sources_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Neither packaged nor checkout directory → ConfigError with searched paths."""
    packaged: Path = tmp_path / "missing_packaged"
    checkout: Path = tmp_path / "missing_checkout"
    monkeypatch.setattr(pack_paths, "_packaged_skills_pack_dir", lambda: packaged)
    monkeypatch.setattr(pack_paths, "_checkout_skills_pack_dir", lambda: checkout)

    with pytest.raises(ConfigError, match="bundled skills pack not found") as exc_info:
        bundled_skills_pack_root()
    message: str = str(exc_info.value)
    assert str(packaged) in message, (
        f"error must include packaged path {packaged!r}, received {message!r}"
    )
    assert str(checkout) in message, (
        f"error must include checkout path {checkout!r}, received {message!r}"
    )


def test_project_skills_root_joins_cwd_cursor_skills(tmp_path: Path) -> None:
    """project_skills_root(cwd) must be {{cwd}}/.cursor/skills without touching disk."""
    cwd: Path = tmp_path / "workspace"
    expected: Path = cwd / ".cursor" / "skills"
    assert project_skills_root(cwd) == expected


def test_user_skills_root_joins_home_cursor_skills(tmp_path: Path) -> None:
    """user_skills_root(home) must be {{home}}/.cursor/skills without touching disk."""
    home: Path = tmp_path / "fake-home"
    expected: Path = home / ".cursor" / "skills"
    assert user_skills_root(home) == expected


def test_skill_discovery_from_config_uses_pack_paths_roots(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Discovery must build project/user roots via pack_paths (single source of truth).

    WHY: discovery, ``skills path``, and seed must share one root helper so BYO
    destinations cannot drift across surfaces.
    """
    workspace: Path = tmp_path / "workspace"
    home: Path = tmp_path / "home"
    alt_project: Path = tmp_path / "alt-project-skills"
    alt_user: Path = tmp_path / "alt-user-skills"
    workspace.mkdir()
    home.mkdir()
    alt_project.mkdir(parents=True)
    alt_user.mkdir(parents=True)

    (alt_project / "from-project").mkdir()
    (alt_project / "from-project" / "SKILL.md").write_text(
        "---\nname: from-project\ndescription: via pack_paths project root\n---\n\nBody.\n",
        encoding="utf-8",
    )
    (alt_user / "from-user").mkdir()
    (alt_user / "from-user" / "SKILL.md").write_text(
        "---\nname: from-user\ndescription: via pack_paths user root\n---\n\nBody.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pack_paths, "project_skills_root", lambda cwd: alt_project)
    monkeypatch.setattr(pack_paths, "user_skills_root", lambda home_arg: alt_user)
    monkeypatch.setattr(Path, "home", lambda: home)

    config = load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={"runtime": {"local": {"cwd": str(workspace)}}},
    )
    discovery = skill_discovery_from_config(config)
    names: set[str] = {entry.name for entry in discovery.list_skills()}
    assert names == {"from-project", "from-user"}, (
        f"discovery must resolve skills through pack_paths roots, "
        f"received names={sorted(names)!r}, "
        f"expected ['from-project', 'from-user'] under "
        f"project={alt_project!r} user={alt_user!r}"
    )
