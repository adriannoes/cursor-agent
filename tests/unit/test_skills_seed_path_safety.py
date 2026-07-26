"""Path-safety unit tests for bundled skills seed.

Locks invalid slugs, symlink refusals, escapes, and frontmatter parse failures.
Hermetic: destinations and mini packs live under ``tmp_path`` only.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from cursor_agent.errors import ConfigError, SeedSkillError
from cursor_agent.skills import seed as seed_module
from cursor_agent.skills.seed import SeedSummary, seed_bundled_skills
from tests.unit.skills_fixtures import (
    assert_failure_has_reason,
    assert_seed_summary_shape,
    destination_skill_slugs,
    failed_slugs,
    mini_pack_with_category_tree,
    write_skill_md,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_seed_soft_fail_records_seed_skill_error_without_propagating(
    tmp_path: Path,
) -> None:
    """Known soft-fail (invalid slug) must record SeedFailure and not raise."""
    pack_root: Path = tmp_path / "soft-fail-pack"
    write_skill_md(
        pack_root / "meta" / "evil",
        name="../x",
        description="Soft-fail via invalid slug",
    )
    write_skill_md(
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

    assert_seed_summary_shape(summary)
    assert "../x" in failed_slugs(summary)
    assert_failure_has_reason(summary, "../x")
    assert "ok-skill" in summary.seeded
    assert summary.failed[0].reason  # non-empty; raised as SeedSkillError internally


def test_seed_config_error_mid_loop_aborts_run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """ConfigError raised mid-loop must abort the entire seed run (not soft-fail)."""
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()

    def _raise_config_error(skill_md: Path, *, pack_root: Path) -> str:
        raise ConfigError(
            f"simulated fatal mid-loop: received skill_md={skill_md}, "
            "expected SeedSkillError for soft-fail only"
        )

    monkeypatch.setattr(
        "cursor_agent.skills.seed._slug_for_pack_skill",
        _raise_config_error,
    )

    with pytest.raises(ConfigError, match="simulated fatal mid-loop"):
        seed_bundled_skills(
            pack_root=pack_root,
            destination_root=destination_root,
            force=False,
        )

    assert destination_skill_slugs(destination_root) == set(), (
        f"aborted run must leave dest empty, "
        f"received={sorted(destination_skill_slugs(destination_root))!r}"
    )


def test_seed_skill_error_mid_loop_records_failed_and_continues(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """SeedSkillError mid-loop must enter summary.failed and continue siblings."""
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
    destination_root: Path = tmp_path / "dest"
    destination_root.mkdir()
    real_slug_for = seed_module._slug_for_pack_skill
    call_count: list[int] = [0]

    def _fail_first_then_real(skill_md: Path, *, pack_root: Path) -> str:
        call_count[0] += 1
        if call_count[0] == 1:
            raise SeedSkillError(
                f"simulated soft-fail: received skill_md={skill_md}, "
                "expected SoftFail recorded in summary.failed"
            )
        return real_slug_for(skill_md, pack_root=pack_root)

    monkeypatch.setattr(
        "cursor_agent.skills.seed._slug_for_pack_skill",
        _fail_first_then_real,
    )

    summary: SeedSummary = seed_bundled_skills(
        pack_root=pack_root,
        destination_root=destination_root,
        force=False,
    )

    assert_seed_summary_shape(summary)
    assert len(summary.failed) == 1, (
        f"first SeedSkillError must soft-fail once, received failed={summary.failed!r}"
    )
    assert "simulated soft-fail" in summary.failed[0].reason
    assert len(summary.seeded) == 1, (
        f"sibling after soft-fail must still seed, received seeded={summary.seeded!r}"
    )


def test_seed_bundled_skills_records_invalid_slug_in_failed(
    tmp_path: Path,
) -> None:
    """Frontmatter name ``../x`` must land in failed; sibling valid skill still seeds."""
    pack_root: Path = tmp_path / "evil-pack"
    write_skill_md(
        pack_root / "research" / "evil",
        name="../x",
        description="Path traversal attempt via frontmatter name",
    )
    write_skill_md(
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

    assert_seed_summary_shape(summary)
    assert "../x" in failed_slugs(summary), (
        f"invalid slug must appear in failed, received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, "../x")
    assert "good-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )
    assert not outside_probe.exists(), (
        f"seed must not write escaped path {outside_probe}, "
        f"destination_root={destination_root!r}"
    )
    assert "good-skill" in destination_skill_slugs(destination_root)
    assert "x" not in destination_skill_slugs(destination_root)


def test_seed_bundled_skills_refuses_symlink_destination(
    tmp_path: Path,
) -> None:
    """destination_root that is a symlink must be refused."""
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
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
    assert destination_skill_slugs(real_dest) == set(), (
        f"refused symlink dest must not receive copies, "
        f"received={sorted(destination_skill_slugs(real_dest))!r}"
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
    write_skill_md(
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

    assert_seed_summary_shape(summary)
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
    assert "leaked" not in destination_skill_slugs(destination_root), (
        f"symlink pack entry must not be seeded, "
        f"received={sorted(destination_skill_slugs(destination_root))!r}"
    )


def test_seed_bundled_skills_records_symlinked_slug_dir_escape_in_failed(
    tmp_path: Path,
) -> None:
    """Pre-existing slug dir symlink escaping dest root → failed; sibling seeds."""
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
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

    assert_seed_summary_shape(summary)
    assert "alpha-skill" in failed_slugs(summary), (
        f"escape must record alpha-skill in failed, received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, "alpha-skill")
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
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
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

    assert "alpha-skill" in failed_slugs(summary), (
        f"force escape must record alpha-skill in failed, "
        f"received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, "alpha-skill")
    assert "beta-skill" in summary.seeded, (
        f"sibling beta-skill must still seed under force, "
        f"received seeded={summary.seeded!r}"
    )
    assert not (outside_dir / "SKILL.md").exists()


def test_seed_bundled_skills_refuses_in_tree_slug_symlink_clobber(
    tmp_path: Path,
) -> None:
    """In-tree slug symlink must fail; target sibling contents must stay intact."""
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
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
        assert "alpha-skill" in failed_slugs(summary), (
            f"in-tree symlink must fail for force={force}, "
            f"received failed={summary.failed!r}"
        )
        assert_failure_has_reason(summary, "alpha-skill")
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


def test_seed_bundled_skills_records_unparseable_frontmatter_in_failed(
    tmp_path: Path,
) -> None:
    """Broken YAML frontmatter → failed; sibling valid skill still seeds."""
    pack_root: Path = tmp_path / "bad-pack"
    skill_dir: Path = pack_root / "meta" / "broken"
    skill_dir.mkdir(parents=True)
    skill_md: Path = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: [unclosed\ndescription: bad\n---\n\nBody.\n",
        encoding="utf-8",
    )
    write_skill_md(
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

    assert_seed_summary_shape(summary)
    assert any("broken" in failure.slug for failure in summary.failed), (
        f"unparseable skill must appear in failed, received failed={summary.failed!r}"
    )
    assert "ok-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )


def test_seed_bundled_skills_skips_symlinks_inside_skill_directory(
    tmp_path: Path,
) -> None:
    """Sibling symlinks under a pack skill dir must not be dereferenced."""
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


def test_seed_bundled_skills_records_slug_exceeding_length_cap_in_failed(
    tmp_path: Path,
) -> None:
    """Frontmatter name of 65 valid chars must fail the 64-char slug cap."""
    pack_root: Path = tmp_path / "long-slug-pack"
    long_name: str = "a" * 65
    write_skill_md(
        pack_root / "meta" / "long-dir",
        name=long_name,
        description="Too long slug",
    )
    write_skill_md(
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

    assert_seed_summary_shape(summary)
    assert long_name in failed_slugs(summary), (
        f"65-char slug must appear in failed, received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, long_name)
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
    write_skill_md(
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

    assert_seed_summary_shape(summary)
    assert "BadName" in failed_slugs(summary), (
        f"invalid directory fallback must appear in failed, "
        f"received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, "BadName")
    assert "ok-skill" in summary.seeded, (
        f"valid sibling must still seed, received seeded={summary.seeded!r}"
    )


def test_seed_bundled_skills_records_resolved_destination_escape_in_failed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """When resolved dest escapes destination_root, seed records escape failure.

    WHY: avoid class-wide ``Path.is_relative_to`` patches. Remap
    ``Path.resolve`` only for ``{destination_root}/{slug}`` so production
    ``_validated_destination_dir`` hits the real ``is_relative_to`` guard.
    """
    pack_root: Path = mini_pack_with_category_tree(tmp_path / "mini-pack")
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

    assert_seed_summary_shape(summary)
    assert "alpha-skill" in failed_slugs(summary), (
        f"escaped alpha-skill must appear in failed, received failed={summary.failed!r}"
    )
    assert "beta-skill" in failed_slugs(summary), (
        f"escaped beta-skill must appear in failed, received failed={summary.failed!r}"
    )
    assert_failure_has_reason(summary, "alpha-skill")
    assert any(
        "escapes destination_root" in failure.reason for failure in summary.failed
    ), (
        f"escape failure must name destination_root escape, "
        f"received failed={summary.failed!r}"
    )
    assert summary.seeded == (), (
        f"escaped destinations must not seed, received seeded={summary.seeded!r}"
    )
    assert destination_skill_slugs(destination_root) == set(), (
        f"escaped seed must leave dest empty, "
        f"received={sorted(destination_skill_slugs(destination_root))!r}"
    )
