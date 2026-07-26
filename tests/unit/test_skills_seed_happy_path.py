"""Happy-path unit tests for idempotent bundled skills seed.

Locks flatten-to-slug, skip/force, directory-name fallback, and duplicate slug.
Hermetic: destinations and mini packs live under ``tmp_path`` only.
"""

from __future__ import annotations

from pathlib import Path

from cursor_agent.skills.pack_paths import bundled_skills_pack_root
from cursor_agent.skills.seed import SeedSummary, seed_bundled_skills
from tests.unit.skills_fixtures import (
    EXPECTED_SEEDED_SKILL_SLUGS,
    PACK_CATEGORY_DIR_NAMES,
    assert_seed_summary_shape,
    destination_skill_slugs,
    failed_slugs,
    mini_pack_with_category_tree,
    write_skill_md,
)


def test_seed_bundled_skills_copies_all_fourteen_into_flat_destination(
    tmp_path: Path,
) -> None:
    """First seed from the real bundled pack must flatten all 14 SKILL.md entries.

    Categories remain repo-only: destination children are slug dirs only.
    """
    pack_root: Path = bundled_skills_pack_root()
    destination_root: Path = tmp_path / "user-skills"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert_seed_summary_shape(summary)
    assert set(summary.seeded) == EXPECTED_SEEDED_SKILL_SLUGS, (
        f"first seed must copy all 14 locked slugs, "
        f"received seeded={sorted(summary.seeded)!r}, "
        f"expected={sorted(EXPECTED_SEEDED_SKILL_SLUGS)!r}"
    )
    assert summary.skipped == (), (
        f"first seed into empty dest must skip nothing, "
        f"received skipped={summary.skipped!r}"
    )
    assert summary.overwritten == (), (
        f"first seed into empty dest must overwrite nothing, "
        f"received overwritten={summary.overwritten!r}"
    )
    assert summary.failed == (), (
        f"first seed of valid pack must fail nothing, "
        f"received failed={summary.failed!r}"
    )

    dest_slugs: set[str] = destination_skill_slugs(destination_root)
    assert dest_slugs == EXPECTED_SEEDED_SKILL_SLUGS, (
        f"destination must be flat slug dirs only, "
        f"received={sorted(dest_slugs)!r}, "
        f"expected={sorted(EXPECTED_SEEDED_SKILL_SLUGS)!r}"
    )
    assert dest_slugs.isdisjoint(PACK_CATEGORY_DIR_NAMES), (
        f"category trees must not be copied into destination, "
        f"received category dirs={sorted(dest_slugs & PACK_CATEGORY_DIR_NAMES)!r}"
    )
    for slug in EXPECTED_SEEDED_SKILL_SLUGS:
        skill_md: Path = destination_root / slug / "SKILL.md"
        assert skill_md.is_file(), (
            f"expected SKILL.md after seed at {skill_md}, pack_root={pack_root!r}"
        )


def test_seed_bundled_skills_second_run_skips_all_existing(
    tmp_path: Path,
) -> None:
    """Idempotent re-seed without force must skip every existing slug dir."""
    pack_root: Path = bundled_skills_pack_root()
    destination_root: Path = tmp_path / "user-skills"
    destination_root.mkdir()

    first: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )
    assert set(first.seeded) == EXPECTED_SEEDED_SKILL_SLUGS

    marker_path: Path = destination_root / "plan" / "LOCAL_MARKER.txt"
    marker_path.write_text("do-not-clobber\n", encoding="utf-8")

    second: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert_seed_summary_shape(second)
    assert second.seeded == (), (
        f"second seed without force must seed nothing, "
        f"received seeded={second.seeded!r}"
    )
    assert set(second.skipped) == EXPECTED_SEEDED_SKILL_SLUGS, (
        f"second seed must skip all 14 existing slugs, "
        f"received skipped={sorted(second.skipped)!r}"
    )
    assert second.overwritten == (), (
        f"second seed without force must overwrite nothing, "
        f"received overwritten={second.overwritten!r}"
    )
    assert second.failed == (), (
        f"second seed of valid pack must fail nothing, "
        f"received failed={second.failed!r}"
    )
    assert marker_path.read_text(encoding="utf-8") == "do-not-clobber\n", (
        f"skip path must leave existing dir contents untouched, "
        f"marker missing or changed at {marker_path}"
    )


def test_seed_bundled_skills_force_overwrites_one_existing_skill(
    tmp_path: Path,
) -> None:
    """force=True must re-copy an existing slug and report it under overwritten."""
    pack_root: Path = bundled_skills_pack_root()
    destination_root: Path = tmp_path / "user-skills"
    destination_root.mkdir()

    seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    target_skill_md: Path = destination_root / "debug" / "SKILL.md"
    original_text: str = target_skill_md.read_text(encoding="utf-8")
    target_skill_md.write_text(
        "---\nname: debug\ndescription: locally mutated\n---\n\nMUTATED\n",
        encoding="utf-8",
    )
    assert target_skill_md.read_text(encoding="utf-8") != original_text

    forced: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=True,
    )

    assert_seed_summary_shape(forced)
    assert "debug" in forced.overwritten, (
        f"force re-copy must list overwritten slug in overwritten, "
        f"received overwritten={forced.overwritten!r}"
    )
    assert "debug" not in forced.seeded, (
        f"force re-copy must not also list slug in seeded, "
        f"received seeded={forced.seeded!r}"
    )
    assert set(forced.overwritten) == EXPECTED_SEEDED_SKILL_SLUGS, (
        f"force=True on full existing tree must overwrite all 14, "
        f"received overwritten={sorted(forced.overwritten)!r}"
    )
    assert forced.seeded == (), (
        f"force overwrite of existing dirs must seed nothing fresh, "
        f"received seeded={forced.seeded!r}"
    )
    assert forced.failed == (), (
        f"force re-copy of valid pack must fail nothing, "
        f"received failed={forced.failed!r}"
    )
    restored: str = target_skill_md.read_text(encoding="utf-8")
    assert restored == original_text, (
        f"force=True must restore pack SKILL.md contents for debug, "
        f"received {restored!r}, expected {original_text!r}"
    )
    assert "MUTATED" not in restored, (
        f"force overwrite must replace mutated body, received {restored!r}"
    )


def test_seed_bundled_skills_mini_pack_flattens_category_tree(
    tmp_path: Path,
) -> None:
    """Mini pack under tmp_path proves flatten without relying on checkout size.

    Count: exactly 2 skills (alpha-skill, beta-skill) from nested categories.
    """
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert_seed_summary_shape(summary)
    assert set(summary.seeded) == {"alpha-skill", "beta-skill"}, (
        f"mini pack must seed both frontmatter names, "
        f"received seeded={sorted(summary.seeded)!r}"
    )
    assert summary.skipped == ()
    assert summary.overwritten == ()
    assert summary.failed == ()
    assert destination_skill_slugs(destination_root) == {
        "alpha-skill",
        "beta-skill",
    }, (
        f"mini pack destination must be flat, "
        f"received={sorted(destination_skill_slugs(destination_root))!r}"
    )
    assert not (destination_root / "research").exists(), (
        f"category dir research must not be copied, "
        f"destination_root={destination_root!r}"
    )
    assert (destination_root / "alpha-skill" / "SKILL.md").is_file()
    assert (destination_root / "beta-skill" / "SKILL.md").is_file()


def test_seed_bundled_skills_falls_back_to_directory_name_when_name_missing(
    tmp_path: Path,
) -> None:
    """Missing frontmatter name must fall back to the skill directory name."""
    pack_root: Path = tmp_path / "fallback-pack"
    skill_dir: Path = pack_root / "meta" / "dir-only-slug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: no name field\n---\n\nBody.\n",
        encoding="utf-8",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert summary.seeded == ("dir-only-slug",), (
        f"fallback slug must be directory name, received seeded={summary.seeded!r}"
    )
    assert (destination_root / "dir-only-slug" / "SKILL.md").is_file()


def test_seed_bundled_skills_records_duplicate_slug_in_failed(
    tmp_path: Path,
) -> None:
    """Second pack SKILL.md resolving to the same slug must go to failed."""
    pack_root: Path = tmp_path / "dup-pack"
    write_skill_md(
        pack_root / "research" / "first-dup",
        name="dup-skill",
        description="First occurrence",
    )
    write_skill_md(
        pack_root / "meta" / "second-dup",
        name="dup-skill",
        description="Duplicate occurrence",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert_seed_summary_shape(summary)
    assert "dup-skill" in summary.seeded, (
        f"first dup-skill occurrence must seed, received seeded={summary.seeded!r}"
    )
    assert "dup-skill" in failed_slugs(summary), (
        f"second dup-skill occurrence must fail, received failed={summary.failed!r}"
    )
    assert summary.seeded.count("dup-skill") == 1
    assert sum(1 for failure in summary.failed if failure.slug == "dup-skill") == 1
    assert (destination_root / "dup-skill" / "SKILL.md").is_file()
