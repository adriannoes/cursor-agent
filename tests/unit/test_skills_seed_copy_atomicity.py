"""Copy-atomicity unit tests for bundled skills seed.

Locks force-overwrite restore, mid-loop soft-fail, and staging rename recovery.
Hermetic: destinations and mini packs live under ``tmp_path`` only.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from cursor_agent.skills.seed import SeedSummary, seed_bundled_skills
from tests.unit.skills_fixtures import (
    assert_failure_has_reason,
    assert_seed_summary_shape,
    failed_slugs,
    write_skill_md,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_seed_bundled_skills_force_preserves_tree_when_copytree_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Failed force overwrite must leave prior SKILL.md intact and record failure."""
    pack_root: Path = tmp_path / "atomic-pack"
    write_skill_md(
        pack_root / "meta" / "stable-skill",
        name="stable-skill",
        description="Survives failed force overwrite",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    first: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )
    assert "stable-skill" in first.seeded
    skill_md: Path = destination_root / "stable-skill" / "SKILL.md"
    original_text: str = skill_md.read_text(encoding="utf-8")

    def _raise_copytree(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated copytree failure")

    monkeypatch.setattr("cursor_agent.skills.seed.shutil.copytree", _raise_copytree)

    forced: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=True,
    )

    assert_seed_summary_shape(forced)
    assert "stable-skill" in failed_slugs(forced), (
        f"failed force copy must record slug in failed, "
        f"received failed={forced.failed!r}"
    )
    assert_failure_has_reason(forced, "stable-skill")
    assert skill_md.is_file(), (
        f"prior SKILL.md must survive failed force overwrite at {skill_md}"
    )
    assert skill_md.read_text(encoding="utf-8") == original_text, (
        f"prior SKILL.md contents must be unchanged after failed force, "
        f"received={skill_md.read_text(encoding='utf-8')!r}, "
        f"expected={original_text!r}"
    )


def test_seed_bundled_skills_failed_first_slug_does_not_block_later_valid(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Failed first same-slug must not enter seen_slugs; later occurrence still seeds.

    First copy fails via monkeypatched copytree; second pack entry shares the slug
    and must seed (not be misclassified as a duplicate).
    """
    pack_root: Path = tmp_path / "flaky-pack"
    write_skill_md(
        pack_root / "a-first" / "first",
        name="shared-slug",
        description="First occurrence — copy will fail",
    )
    write_skill_md(
        pack_root / "z-second" / "second",
        name="shared-slug",
        description="Second occurrence — must seed after first failed",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    real_copytree = shutil.copytree
    copy_attempts: list[int] = [0]

    def _flaky_copytree(*args: object, **kwargs: object) -> Path:
        copy_attempts[0] += 1
        if copy_attempts[0] == 1:
            raise OSError("simulated first-copy failure")
        return real_copytree(*args, **kwargs)

    monkeypatch.setattr(
        "cursor_agent.skills.seed.shutil.copytree",
        _flaky_copytree,
    )

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert_seed_summary_shape(summary)
    assert "shared-slug" in failed_slugs(summary), (
        f"first failed copy must record shared-slug, received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, "shared-slug")
    assert "shared-slug" in summary.seeded, (
        f"second same-slug must seed after failed first, "
        f"received seeded={summary.seeded!r}, failed={summary.failed!r}"
    )
    assert sum(1 for failure in summary.failed if failure.slug == "shared-slug") == 1
    assert all(
        "duplicate" not in failure.reason.lower() for failure in summary.failed
    ), (
        f"failed first must not cause duplicate misclassification, "
        f"received failed={summary.failed!r}"
    )
    assert (destination_root / "shared-slug" / "SKILL.md").is_file()


def test_seed_bundled_skills_force_restores_prior_when_staging_rename_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """OSError on staging→dest rename must restore backup and record failure.

    Also exercises ``_cleanup_tree_if_exists`` when the leftover staging tree exists.
    """
    pack_root: Path = tmp_path / "rename-fail-pack"
    write_skill_md(
        pack_root / "meta" / "stable-skill",
        name="stable-skill",
        description="Survives failed staging rename",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    first: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )
    assert "stable-skill" in first.seeded
    skill_md: Path = destination_root / "stable-skill" / "SKILL.md"
    original_text: str = skill_md.read_text(encoding="utf-8")

    real_rename = Path.rename

    def _fail_staging_rename(self: Path, target: Path | str) -> Path:
        """Fail only the staging→dest rename; allow backup/restore renames."""
        if self.name.startswith(".seed-staging-"):
            raise OSError(
                f"simulated staging rename failure: source={self!r}, target={target!r}"
            )
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", _fail_staging_rename)

    forced: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=True,
    )

    assert_seed_summary_shape(forced)
    assert "stable-skill" in failed_slugs(forced), (
        f"failed staging rename must record slug in failed, "
        f"received failed={forced.failed!r}"
    )
    assert_failure_has_reason(forced, "stable-skill")
    assert skill_md.is_file(), (
        f"prior SKILL.md must be restored after staging rename failure at {skill_md}"
    )
    assert skill_md.read_text(encoding="utf-8") == original_text, (
        f"restore path must leave prior SKILL.md unchanged, "
        f"received={skill_md.read_text(encoding='utf-8')!r}, "
        f"expected={original_text!r}"
    )
    leftover_staging = [
        path
        for path in destination_root.iterdir()
        if path.name.startswith(".seed-staging-")
    ]
    assert leftover_staging == [], (
        f"_cleanup_tree_if_exists must remove leftover staging trees, "
        f"received leftover={leftover_staging!r}"
    )
