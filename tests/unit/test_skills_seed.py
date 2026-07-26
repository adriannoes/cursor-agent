"""Unit tests for idempotent bundled skills seed (PRD-016, FR-3, FR-4, FR-7, A6/A6b).

WHY: lock flatten-to-slug, skip/force, and path-safety before implementing
``cursor_agent.skills.seed`` (TDD RED for Wave 2 / Task 3.1).

Hermetic: destinations and mini packs live under ``tmp_path`` only — never
touch real ``~/.cursor/skills/``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cursor_agent.errors import ConfigError
from cursor_agent.skills.pack_paths import bundled_skills_pack_root
from cursor_agent.skills.seed import SeedFailure, SeedSummary, seed_bundled_skills

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

# Locked catalog names from PRD-016 FR-2 (flat destination slugs after seed).
EXPECTED_SEEDED_SKILL_SLUGS: frozenset[str] = frozenset(
    {
        "deep-research",
        "brief",
        "compare-sources",
        "summarize-url",
        "plan",
        "debug",
        "tdd",
        "spike",
        "dogfood",
        "simplify",
        "pr-review",
        "pr-workflow",
        "issues",
        "build-skill",
    }
)

# Repo-only category dirs must not appear under the flat destination root.
PACK_CATEGORY_DIR_NAMES: frozenset[str] = frozenset(
    {"research", "software-development", "github", "meta"}
)


def _write_skill_md(skill_dir: Path, *, name: str, description: str) -> Path:
    """Create a minimal AgentSkills SKILL.md and return its path."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path: Path = skill_dir / "SKILL.md"
    skill_path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody for {name}.\n",
        encoding="utf-8",
    )
    return skill_path


def _mini_pack_with_category_tree(pack_root: Path) -> Path:
    """Build a controllable mini pack with category nesting (flatten contract)."""
    _write_skill_md(
        pack_root / "research" / "alpha-skill",
        name="alpha-skill",
        description="Mini pack research skill",
    )
    _write_skill_md(
        pack_root / "meta" / "beta-skill",
        name="beta-skill",
        description="Mini pack meta skill",
    )
    return pack_root


def _destination_skill_slugs(destination_root: Path) -> set[str]:
    """Return immediate child directory names under the seed destination."""
    if not destination_root.is_dir():
        return set()
    return {path.name for path in destination_root.iterdir() if path.is_dir()}


def _failed_slugs(summary: SeedSummary) -> set[str]:
    """Return the set of slugs recorded in ``summary.failed``."""
    return {failure.slug for failure in summary.failed}


def _assert_failure_has_reason(summary: SeedSummary, slug: str) -> None:
    """Assert ``slug`` appears in failed with a non-empty reason string."""
    for failure in summary.failed:
        if failure.slug == slug:
            assert isinstance(failure, SeedFailure), (
                f"failed entry must be SeedFailure, received {failure!r}"
            )
            assert failure.reason.strip(), (
                f"SeedFailure for slug={slug!r} must include a non-empty reason, "
                f"received reason={failure.reason!r}"
            )
            return
    raise AssertionError(
        f"expected SeedFailure for slug={slug!r}, received failed={summary.failed!r}"
    )


def _assert_seed_summary_shape(summary: SeedSummary) -> None:
    """Lock SeedSummary field types expected by Task 3.2 / CLI consumers."""
    assert isinstance(summary.seeded, tuple), (
        f"SeedSummary.seeded must be tuple[str, ...], "
        f"received type={type(summary.seeded)!r} value={summary.seeded!r}"
    )
    assert isinstance(summary.skipped, tuple), (
        f"SeedSummary.skipped must be tuple[str, ...], "
        f"received type={type(summary.skipped)!r} value={summary.skipped!r}"
    )
    assert isinstance(summary.overwritten, tuple), (
        f"SeedSummary.overwritten must be tuple[str, ...], "
        f"received type={type(summary.overwritten)!r} value={summary.overwritten!r}"
    )
    assert isinstance(summary.failed, tuple), (
        f"SeedSummary.failed must be tuple[SeedFailure, ...], "
        f"received type={type(summary.failed)!r} value={summary.failed!r}"
    )
    for field_name, values in (
        ("seeded", summary.seeded),
        ("skipped", summary.skipped),
        ("overwritten", summary.overwritten),
    ):
        for item in values:
            assert isinstance(item, str), (
                f"SeedSummary.{field_name} items must be str, "
                f"received item={item!r} type={type(item)!r}"
            )
    for failure in summary.failed:
        assert isinstance(failure, SeedFailure), (
            f"SeedSummary.failed items must be SeedFailure, "
            f"received item={failure!r} type={type(failure)!r}"
        )
        assert isinstance(failure.slug, str), (
            f"SeedFailure.slug must be str, received {failure.slug!r}"
        )
        assert isinstance(failure.reason, str), (
            f"SeedFailure.reason must be str, received {failure.reason!r}"
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

    _assert_seed_summary_shape(summary)
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

    dest_slugs: set[str] = _destination_skill_slugs(destination_root)
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

    _assert_seed_summary_shape(second)
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

    _assert_seed_summary_shape(forced)
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
    pack_root: Path = _mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert set(summary.seeded) == {"alpha-skill", "beta-skill"}, (
        f"mini pack must seed both frontmatter names, "
        f"received seeded={sorted(summary.seeded)!r}"
    )
    assert summary.skipped == ()
    assert summary.overwritten == ()
    assert summary.failed == ()
    assert _destination_skill_slugs(destination_root) == {
        "alpha-skill",
        "beta-skill",
    }, (
        f"mini pack destination must be flat, "
        f"received={sorted(_destination_skill_slugs(destination_root))!r}"
    )
    assert not (destination_root / "research").exists(), (
        f"category dir research must not be copied, "
        f"destination_root={destination_root!r}"
    )
    assert (destination_root / "alpha-skill" / "SKILL.md").is_file()
    assert (destination_root / "beta-skill" / "SKILL.md").is_file()


def test_seed_bundled_skills_records_invalid_slug_in_failed(
    tmp_path: Path,
) -> None:
    """Frontmatter name ``../x`` must land in failed; sibling valid skill still seeds."""
    pack_root: Path = tmp_path / "evil-pack"
    _write_skill_md(
        pack_root / "research" / "evil",
        name="../x",
        description="Path traversal attempt via frontmatter name",
    )
    _write_skill_md(
        pack_root / "meta" / "good-skill",
        name="good-skill",
        description="Valid sibling skill",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()
    outside_probe: Path = tmp_path / "x"

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert "../x" in _failed_slugs(summary), (
        f"invalid slug must appear in failed, received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, "../x")
    assert "good-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )
    assert not outside_probe.exists(), (
        f"seed must not write escaped path {outside_probe}, "
        f"destination_root={destination_root!r}"
    )
    assert "good-skill" in _destination_skill_slugs(destination_root)
    assert "x" not in _destination_skill_slugs(destination_root)


def test_seed_bundled_skills_refuses_symlink_destination(
    tmp_path: Path,
) -> None:
    """destination_root that is a symlink must be refused (A6b)."""
    pack_root: Path = _mini_pack_with_category_tree(tmp_path / "mini-pack")
    real_dest: Path = tmp_path / "real-dest"
    real_dest.mkdir()
    symlink_dest: Path = tmp_path / "symlink-dest"
    symlink_dest.symlink_to(real_dest, target_is_directory=True)

    with pytest.raises(ConfigError) as exc_info:
        seed_bundled_skills(
            pack_root=pack_root,
            destination_root=symlink_dest,
            force=False,
        )

    message: str = str(exc_info.value)
    assert str(symlink_dest) in message, (
        f"symlink dest error must include offending path {symlink_dest!r}, "
        f"received {message!r}"
    )
    assert "symlink" in message.lower(), (
        f"error must state symlink refusal, received {message!r}"
    )
    assert _destination_skill_slugs(real_dest) == set(), (
        f"refused symlink dest must not receive copies, "
        f"received={sorted(_destination_skill_slugs(real_dest))!r}"
    )


def test_seed_bundled_skills_missing_pack_root_errors_clearly(
    tmp_path: Path,
) -> None:
    """Missing pack_root must raise ConfigError naming the offending path."""
    missing_pack: Path = tmp_path / "does-not-exist-pack"
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    with pytest.raises(ConfigError) as exc_info:
        seed_bundled_skills(
            pack_root=missing_pack,
            destination_root=destination_root,
            force=False,
        )

    message: str = str(exc_info.value)
    assert str(missing_pack) in message, (
        f"missing pack error must include offending path {missing_pack!r}, "
        f"received {message!r}"
    )
    assert "pack" in message.lower() or "directory" in message.lower(), (
        f"error must describe expected existing pack directory, received {message!r}"
    )


def test_seed_bundled_skills_records_symlink_skill_md_in_failed(
    tmp_path: Path,
) -> None:
    """Pack SKILL.md symlink must go to failed; sibling valid skill still seeds."""
    pack_root: Path = tmp_path / "symlink-pack"
    outside_skill: Path = tmp_path / "outside" / "SKILL.md"
    outside_skill.parent.mkdir(parents=True)
    outside_skill.write_text(
        "---\nname: leaked\ndescription: outside pack\n---\n\nLeaked.\n",
        encoding="utf-8",
    )
    skill_dir: Path = pack_root / "research" / "leaked"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").symlink_to(outside_skill)
    _write_skill_md(
        pack_root / "meta" / "ok-skill",
        name="ok-skill",
        description="Valid sibling",
    )

    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert any("leaked" in failure.slug for failure in summary.failed), (
        f"symlink pack entry must appear in failed, received failed={summary.failed!r}"
    )
    for failure in summary.failed:
        if "leaked" in failure.slug:
            assert failure.reason.strip(), (
                f"symlink failure must include reason, received {failure!r}"
            )
    assert "ok-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )
    assert "leaked" not in _destination_skill_slugs(destination_root), (
        f"symlink pack entry must not be seeded, "
        f"received={sorted(_destination_skill_slugs(destination_root))!r}"
    )


def test_seed_bundled_skills_records_symlinked_slug_dir_escape_in_failed(
    tmp_path: Path,
) -> None:
    """Pre-existing slug dir symlink escaping dest root → failed; sibling seeds (C1/C3)."""
    pack_root: Path = _mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()
    outside_dir: Path = tmp_path / "outside-secret"
    outside_dir.mkdir()
    marker: Path = outside_dir / "SHOULD_NOT_TOUCH.txt"
    marker.write_text("secret\n", encoding="utf-8")
    symlink_slug: Path = destination_root / "alpha-skill"
    symlink_slug.symlink_to(outside_dir, target_is_directory=True)

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert "alpha-skill" in _failed_slugs(summary), (
        f"escape must record alpha-skill in failed, received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, "alpha-skill")
    assert "beta-skill" in summary.seeded, (
        f"sibling beta-skill must still seed, received seeded={summary.seeded!r}"
    )
    assert marker.read_text(encoding="utf-8") == "secret\n", (
        f"seed must not write through escaped symlink, marker at {marker}"
    )
    assert not (outside_dir / "SKILL.md").exists(), (
        f"seed must not copy into symlink target {outside_dir}"
    )


def test_seed_bundled_skills_force_records_symlinked_slug_dir_escape_in_failed(
    tmp_path: Path,
) -> None:
    """force=True must still record escaping slug symlink in failed; sibling seeds."""
    pack_root: Path = _mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()
    outside_dir: Path = tmp_path / "outside-force"
    outside_dir.mkdir()
    (destination_root / "alpha-skill").symlink_to(outside_dir, target_is_directory=True)

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=True,
    )

    assert "alpha-skill" in _failed_slugs(summary), (
        f"force escape must record alpha-skill in failed, "
        f"received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, "alpha-skill")
    assert "beta-skill" in summary.seeded, (
        f"sibling beta-skill must still seed under force, "
        f"received seeded={summary.seeded!r}"
    )
    assert not (outside_dir / "SKILL.md").exists()


def test_seed_bundled_skills_refuses_in_tree_slug_symlink_clobber(
    tmp_path: Path,
) -> None:
    """In-tree slug symlink must fail; target sibling contents must stay intact."""
    pack_root: Path = _mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    # Seed beta first so the in-tree symlink target has known body content.
    seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )
    beta_skill_md: Path = destination_root / "beta-skill" / "SKILL.md"
    beta_body: str = beta_skill_md.read_text(encoding="utf-8")
    alpha_dir: Path = destination_root / "alpha-skill"
    # Replace seeded alpha dir with symlink → beta (in-tree clobber hazard).
    shutil.rmtree(alpha_dir)
    alpha_dir.symlink_to(destination_root / "beta-skill", target_is_directory=True)

    for force in (False, True):
        summary: SeedSummary = seed_bundled_skills(
            pack_root=pack_root,
            destination_root=destination_root,
            force=force,
        )
        assert "alpha-skill" in _failed_slugs(summary), (
            f"in-tree symlink must fail for force={force}, "
            f"received failed={summary.failed!r}"
        )
        _assert_failure_has_reason(summary, "alpha-skill")
        assert alpha_dir.is_symlink(), (
            f"alpha-skill must remain a symlink (not followed/deleted), "
            f"force={force}, path={alpha_dir}"
        )
        assert beta_skill_md.read_text(encoding="utf-8") == beta_body, (
            f"beta-skill body must not be replaced by alpha pack content, "
            f"force={force}, received={beta_skill_md.read_text(encoding='utf-8')!r}"
        )
        assert "Body for alpha-skill" not in beta_body
        assert "Body for alpha-skill" not in beta_skill_md.read_text(encoding="utf-8")


def test_seed_bundled_skills_force_preserves_tree_when_copytree_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Failed force overwrite must leave prior SKILL.md intact and record failure."""
    pack_root: Path = tmp_path / "atomic-pack"
    _write_skill_md(
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

    _assert_seed_summary_shape(forced)
    assert "stable-skill" in _failed_slugs(forced), (
        f"failed force copy must record slug in failed, "
        f"received failed={forced.failed!r}"
    )
    _assert_failure_has_reason(forced, "stable-skill")
    assert skill_md.is_file(), (
        f"prior SKILL.md must survive failed force overwrite at {skill_md}"
    )
    assert skill_md.read_text(encoding="utf-8") == original_text, (
        f"prior SKILL.md contents must be unchanged after failed force, "
        f"received={skill_md.read_text(encoding='utf-8')!r}, "
        f"expected={original_text!r}"
    )


def test_seed_bundled_skills_records_unparseable_frontmatter_in_failed(
    tmp_path: Path,
) -> None:
    """Broken YAML frontmatter → failed; sibling valid skill still seeds (C2/C3)."""
    pack_root: Path = tmp_path / "bad-pack"
    skill_dir: Path = pack_root / "meta" / "broken"
    skill_dir.mkdir(parents=True)
    skill_md: Path = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: [unclosed\ndescription: bad\n---\n\nBody.\n",
        encoding="utf-8",
    )
    _write_skill_md(
        pack_root / "research" / "ok-skill",
        name="ok-skill",
        description="Valid sibling",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert any("broken" in failure.slug for failure in summary.failed), (
        f"unparseable skill must appear in failed, received failed={summary.failed!r}"
    )
    assert "ok-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )


def test_seed_bundled_skills_skips_symlinks_inside_skill_directory(
    tmp_path: Path,
) -> None:
    """Sibling symlinks under a pack skill dir must not be dereferenced (C4)."""
    pack_root: Path = tmp_path / "symlink-content-pack"
    skill_dir: Path = pack_root / "meta" / "with-link"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: with-link\ndescription: has symlink sibling\n---\n\nBody.\n",
        encoding="utf-8",
    )
    secret: Path = tmp_path / "secret-payload.txt"
    secret.write_text("TOP_SECRET\n", encoding="utf-8")
    (skill_dir / "leaked.txt").symlink_to(secret)

    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert "with-link" in summary.seeded
    dest_skill: Path = destination_root / "with-link"
    assert (dest_skill / "SKILL.md").is_file()
    leaked_dest: Path = dest_skill / "leaked.txt"
    assert not leaked_dest.exists(), (
        f"symlink sibling must be ignored by copytree, found {leaked_dest}"
    )
    assert not any(
        path.read_text(encoding="utf-8") == "TOP_SECRET\n"
        for path in dest_skill.rglob("*")
        if path.is_file() and not path.is_symlink()
    ), f"secret payload must not be copied into {dest_skill}"


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
    _write_skill_md(
        pack_root / "research" / "first-dup",
        name="dup-skill",
        description="First occurrence",
    )
    _write_skill_md(
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

    _assert_seed_summary_shape(summary)
    assert "dup-skill" in summary.seeded, (
        f"first dup-skill occurrence must seed, received seeded={summary.seeded!r}"
    )
    assert "dup-skill" in _failed_slugs(summary), (
        f"second dup-skill occurrence must fail, received failed={summary.failed!r}"
    )
    assert summary.seeded.count("dup-skill") == 1
    assert sum(1 for failure in summary.failed if failure.slug == "dup-skill") == 1
    assert (destination_root / "dup-skill" / "SKILL.md").is_file()


def test_seed_bundled_skills_failed_first_slug_does_not_block_later_valid(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Failed first same-slug must not enter seen_slugs; later occurrence still seeds.

    First copy fails via monkeypatched copytree; second pack entry shares the slug
    and must seed (not be misclassified as a duplicate).
    """
    pack_root: Path = tmp_path / "flaky-pack"
    _write_skill_md(
        pack_root / "a-first" / "first",
        name="shared-slug",
        description="First occurrence — copy will fail",
    )
    _write_skill_md(
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

    _assert_seed_summary_shape(summary)
    assert "shared-slug" in _failed_slugs(summary), (
        f"first failed copy must record shared-slug, received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, "shared-slug")
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


def test_seed_bundled_skills_records_slug_exceeding_length_cap_in_failed(
    tmp_path: Path,
) -> None:
    """Frontmatter name of 65 valid chars must fail the 64-char slug cap."""
    pack_root: Path = tmp_path / "long-slug-pack"
    long_name: str = "a" * 65
    _write_skill_md(
        pack_root / "meta" / "long-dir",
        name=long_name,
        description="Too long slug",
    )
    _write_skill_md(
        pack_root / "research" / "ok-skill",
        name="ok-skill",
        description="Valid sibling",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert long_name in _failed_slugs(summary), (
        f"65-char slug must appear in failed, received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, long_name)
    assert "ok-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )


def test_seed_bundled_skills_records_invalid_directory_fallback_in_failed(
    tmp_path: Path,
) -> None:
    """Uppercase directory name without frontmatter name must fail slug validation."""
    pack_root: Path = tmp_path / "bad-dirname-pack"
    skill_dir: Path = pack_root / "meta" / "BadName"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: no name field\n---\n\nBody.\n",
        encoding="utf-8",
    )
    _write_skill_md(
        pack_root / "research" / "ok-skill",
        name="ok-skill",
        description="Valid sibling",
    )
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert "BadName" in _failed_slugs(summary), (
        f"invalid directory fallback must appear in failed, "
        f"received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, "BadName")
    assert "ok-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )


def test_seed_bundled_skills_records_resolved_destination_escape_in_failed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """When resolved dest escapes destination_root, seed records A6b failure.

    WHY (PR review): avoid class-wide ``Path.is_relative_to`` patches. Remap
    ``Path.resolve`` only for ``{destination_root}/{slug}`` so production
    ``_validated_destination_dir`` hits the real ``is_relative_to`` guard.
    """
    pack_root: Path = _mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()
    outside_root: Path = tmp_path / "outside"
    outside_root.mkdir()
    real_resolve = Path.resolve

    def _resolve_slug_outside_destination(
        self: Path,
        strict: bool = False,
    ) -> Path:
        """Resolve ``{destination_root}/{slug}`` to a sibling outside the dest root."""
        if self.parent == destination_root and self.name in {
            "alpha-skill",
            "beta-skill",
        }:
            return (outside_root / self.name).resolve()
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _resolve_slug_outside_destination)

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    _assert_seed_summary_shape(summary)
    assert "alpha-skill" in _failed_slugs(summary), (
        f"escaped alpha-skill must appear in failed, received failed={summary.failed!r}"
    )
    assert "beta-skill" in _failed_slugs(summary), (
        f"escaped beta-skill must appear in failed, received failed={summary.failed!r}"
    )
    _assert_failure_has_reason(summary, "alpha-skill")
    assert any(
        "escapes destination_root" in failure.reason for failure in summary.failed
    ), (
        f"escape failure must name destination_root escape, "
        f"received failed={summary.failed!r}"
    )
    assert summary.seeded == (), (
        f"escaped destinations must not seed, received seeded={summary.seeded!r}"
    )
    assert _destination_skill_slugs(destination_root) == set(), (
        f"escaped seed must leave dest empty, "
        f"received={sorted(_destination_skill_slugs(destination_root))!r}"
    )


def test_seed_bundled_skills_force_restores_prior_when_staging_rename_fails(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """OSError on staging→dest rename must restore backup and record failure.

    Also exercises ``_cleanup_tree_if_exists`` when the leftover staging tree exists.
    """
    pack_root: Path = tmp_path / "rename-fail-pack"
    _write_skill_md(
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

    _assert_seed_summary_shape(forced)
    assert "stable-skill" in _failed_slugs(forced), (
        f"failed staging rename must record slug in failed, "
        f"received failed={forced.failed!r}"
    )
    _assert_failure_has_reason(forced, "stable-skill")
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
