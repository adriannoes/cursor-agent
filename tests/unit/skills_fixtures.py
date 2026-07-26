"""Shared fixtures for skills seed and CLI unit tests.

Hermetic helpers only — destinations and mini packs live under ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

from cursor_agent.skills.seed import SeedFailure, SeedSummary

# Locked catalog (category → skill name) — single source for layout + seed slug tests.
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

# Flat destination slugs after seed (derived — do not maintain a second list).
EXPECTED_SEEDED_SKILL_SLUGS: frozenset[str] = frozenset(
    skill_name for _, skill_name in EXPECTED_SKILLS_PACK_ENTRIES
)

# Repo-only category dirs must not appear under the flat destination root.
PACK_CATEGORY_DIR_NAMES: frozenset[str] = frozenset(
    category for category, _ in EXPECTED_SKILLS_PACK_ENTRIES
)


def write_skill_md(skill_dir: Path, *, name: str, description: str) -> Path:
    """Create a minimal AgentSkills SKILL.md and return its path.

    Example:
        write_skill_md(tmp_path / "plan", name="plan", description="Plan skill")
    """
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path: Path = skill_dir / "SKILL.md"
    skill_path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody for {name}.\n",
        encoding="utf-8",
    )
    return skill_path


def mini_pack_with_category_tree(pack_root: Path) -> Path:
    """Build a controllable mini pack with category nesting (flatten contract).

    Example:
        mini_pack_with_category_tree(tmp_path / "mini-pack")
    """
    write_skill_md(
        pack_root / "research" / "alpha-skill",
        name="alpha-skill",
        description="Mini pack research skill",
    )
    write_skill_md(
        pack_root / "meta" / "beta-skill",
        name="beta-skill",
        description="Mini pack meta skill",
    )
    return pack_root


def destination_skill_slugs(destination_root: Path) -> set[str]:
    """Return immediate child directory names under the seed destination."""
    if not destination_root.is_dir():
        return set()
    return {path.name for path in destination_root.iterdir() if path.is_dir()}


def failed_slugs(summary: SeedSummary) -> set[str]:
    """Return the set of slugs recorded in ``summary.failed``."""
    return {failure.slug for failure in summary.failed}


def assert_failure_has_reason(summary: SeedSummary, slug: str) -> None:
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


def assert_seed_summary_shape(summary: SeedSummary) -> None:
    """Lock SeedSummary field types expected by CLI consumers."""
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
