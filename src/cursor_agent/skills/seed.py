"""Idempotent flatten-seed of bundled product skills (PRD-016, FR-3/4/7, A6/A6b)."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Final

import yaml

from cursor_agent.errors import ConfigError
from cursor_agent.skills.discovery import SKILL_FILENAME
from cursor_agent.skills.skill_frontmatter import (
    is_safe_skill_file,
    parse_yaml_frontmatter,
    read_frontmatter_text,
)

# WHY: A6b — slug must be a single path segment ≤64 chars; rejects ``../x`` escapes.
_SLUG_PATTERN: Final[Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SLUG_PATTERN_HELP: Final[str] = (
    "^[a-z0-9][a-z0-9-]{0,63}$ "
    "(slug must start with a-z0-9, contain only a-z0-9-, and be at most 64 chars)"
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    """Outcome of seeding bundled skills into a flat destination root.

    Example:
        >>> summary = SeedSummary(
        ...     seeded=("plan",),
        ...     skipped=(),
        ...     overwritten=(),
        ...     failed=(),
        ... )
        >>> summary.seeded
        ('plan',)
    """

    seeded: tuple[str, ...]
    skipped: tuple[str, ...]
    overwritten: tuple[str, ...]
    failed: tuple[str, ...]


def seed_bundled_skills(
    *,
    pack_root: Path,
    destination_root: Path,
    force: bool = False,
) -> SeedSummary:
    """Copy bundled pack skills into a flat ``{destination_root}/{slug}/`` tree.

    Enumerates ``SKILL.md`` under ``pack_root``, derives a slug from frontmatter
    ``name`` (fallback: parent directory), and copies each skill directory.
    Existing destinations are skipped unless ``force`` is True. Per-skill
    problems are recorded in ``failed`` without aborting the run.

    Example:
        >>> from pathlib import Path
        >>> # seed_bundled_skills(pack_root=Path("skills"), destination_root=Path("out"))
    """
    _validate_seed_roots(pack_root, destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    seeded: list[str] = []
    skipped: list[str] = []
    overwritten: list[str] = []
    failed: list[str] = []
    seen_slugs: set[str] = set()

    for skill_md in sorted(pack_root.rglob(SKILL_FILENAME)):
        attempted_slug: str | None = None
        try:
            attempted_slug = _slug_for_pack_skill(skill_md, pack_root=pack_root)
            if attempted_slug in seen_slugs:
                raise ConfigError(
                    f"duplicate skill slug in pack: received {attempted_slug!r} "
                    f"from {skill_md}, expected unique frontmatter name / "
                    f"directory slug per pack run"
                )
            seen_slugs.add(attempted_slug)
            dest_dir = _validated_destination_dir(destination_root, attempted_slug)
            dest_existed = dest_dir.exists()
            if dest_existed and not force:
                skipped.append(attempted_slug)
                continue
            _copy_skill_directory(skill_md.parent, dest_dir)
            if dest_existed:
                overwritten.append(attempted_slug)
            else:
                seeded.append(attempted_slug)
        except ConfigError:
            failed.append(_failed_label(skill_md, attempted_slug=attempted_slug))

    return SeedSummary(
        seeded=tuple(seeded),
        skipped=tuple(skipped),
        overwritten=tuple(overwritten),
        failed=tuple(failed),
    )


def _failed_label(skill_md: Path, *, attempted_slug: str | None) -> str:
    """Prefer the attempted slug; fall back to the skill directory name."""
    if attempted_slug is not None:
        return attempted_slug
    return skill_md.parent.name


def _validate_seed_roots(pack_root: Path, destination_root: Path) -> None:
    """Refuse missing pack roots and symlink destinations (A6b)."""
    if not pack_root.is_dir():
        raise ConfigError(
            f"missing pack root: received {pack_root}, "
            "expected an existing directory containing bundled skills"
        )
    if destination_root.is_symlink():
        raise ConfigError(
            f"destination root is a symlink: received {destination_root}, "
            "expected a real (non-symlink) directory path"
        )


def _slug_for_pack_skill(skill_md: Path, *, pack_root: Path) -> str:
    """Return sanitized frontmatter name, falling back to the skill directory name."""
    # WHY: reuse discovery safety so seed and list share the same symlink policy.
    if not is_safe_skill_file(skill_md, pack_root):
        raise ConfigError(
            f"unsafe pack SKILL.md: received {skill_md}, "
            "expected a regular file under the pack root (not a symlink)"
        )
    try:
        frontmatter = parse_yaml_frontmatter(read_frontmatter_text(skill_md))
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        # WHY: Wave 3 CLI maps ConfigError → non-zero exit; raw parse errors omit path.
        raise ConfigError(
            f"unparseable pack SKILL.md: received {skill_md}, "
            f"expected agentskills.io YAML frontmatter with string name/description "
            f"fields; parse error={exc!r}"
        ) from exc
    return frontmatter.get("name", "").strip() or skill_md.parent.name


def _validated_destination_dir(destination_root: Path, slug: str) -> Path:
    """Return ``destination_root / slug`` after A6b slug and containment checks."""
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ConfigError(
            f"invalid skill slug: received {slug!r}, "
            f"expected pattern matching {_SLUG_PATTERN_HELP}"
        )
    resolved_root = destination_root.resolve()
    dest_dir = (destination_root / slug).resolve()
    if not dest_dir.is_relative_to(resolved_root):
        raise ConfigError(
            f"skill destination escapes destination_root: "
            f"received slug={slug!r} resolved={dest_dir}, "
            f"expected path relative to {resolved_root}"
        )
    return dest_dir


def _ignore_symlinks_in_skill_tree(directory: str, names: list[str]) -> set[str]:
    """Skip symlink entries so copytree does not dereference pack contents (A6b)."""
    ignored: set[str] = set()
    for name in names:
        if (Path(directory) / name).is_symlink():
            ignored.add(name)
    return ignored


def _copy_skill_directory(source_dir: Path, dest_dir: Path) -> None:
    """Replace ``dest_dir`` with a copy of ``source_dir`` contents (force-safe)."""
    try:
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        # WHY: default copytree dereferences sibling symlinks into user skills (C4).
        shutil.copytree(source_dir, dest_dir, ignore=_ignore_symlinks_in_skill_tree)
    except OSError as exc:
        raise ConfigError(
            f"failed to copy skill directory: received source={source_dir}, "
            f"dest={dest_dir}, expected readable pack skill dir and writable "
            f"destination; os_error={exc!r}"
        ) from exc
