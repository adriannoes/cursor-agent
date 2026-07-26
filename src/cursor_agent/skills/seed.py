"""Idempotent flatten-seed of bundled product skills into a flat user root."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from re import Pattern
from typing import Final

import yaml

from cursor_agent.errors import ConfigError, SeedSkillError
from cursor_agent.skills.skill_frontmatter import (
    SKILL_FILENAME,
    is_safe_skill_file,
    parse_yaml_frontmatter,
    read_frontmatter_text,
    skill_name_from_frontmatter,
)

# WHY: slug must be a single path segment ≤64 chars; rejects ``../x`` escapes.
_SLUG_PATTERN: Final[Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_SLUG_PATTERN_HELP: Final[str] = (
    "^[a-z0-9][a-z0-9-]{0,63}$ "
    "(slug must start with a-z0-9, contain only a-z0-9-, and be at most 64 chars)"
)
_MODULE_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SeedFailure:
    """Per-skill seed failure with a structured reason for CLI / logs.

    Example:
        >>> SeedFailure(slug="plan", reason="invalid skill slug: ...").slug
        'plan'
    """

    slug: str
    reason: str


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
    failed: tuple[SeedFailure, ...]


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
    failed: list[SeedFailure] = []
    seen_slugs: set[str] = set()

    for skill_md in sorted(pack_root.rglob(SKILL_FILENAME)):
        attempted_slug: str | None = None
        try:
            attempted_slug = _slug_for_pack_skill(skill_md, pack_root=pack_root)
            if attempted_slug in seen_slugs:
                raise SeedSkillError(
                    f"duplicate skill slug in pack: received {attempted_slug!r} "
                    f"from {skill_md}, expected unique frontmatter name / "
                    f"directory slug per pack run"
                )
            dest_dir = _validated_destination_dir(destination_root, attempted_slug)
            dest_existed = dest_dir.exists()
            if dest_existed and not force:
                skipped.append(attempted_slug)
                seen_slugs.add(attempted_slug)
                continue
            _copy_skill_directory(skill_md.parent, dest_dir)
            if dest_existed:
                overwritten.append(attempted_slug)
            else:
                seeded.append(attempted_slug)
            seen_slugs.add(attempted_slug)
        except SeedSkillError as exc:
            label = _failed_label(skill_md, attempted_slug=attempted_slug)
            failed.append(SeedFailure(slug=label, reason=str(exc)))
            _MODULE_LOGGER.warning(
                "skill seed failed: slug=%s reason=%s",
                label,
                exc,
            )

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
    """Refuse missing pack roots and symlink destinations."""
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
    """Return frontmatter name (or dir fallback) validated later by slug checks.

    WHY: validate-and-fail — do not sanitize; callers refuse invalid slugs via
    ``SeedSkillError`` into ``summary.failed``.
    """
    # WHY: reuse discovery safety so seed and list share the same symlink policy.
    if not is_safe_skill_file(skill_md, pack_root):
        raise SeedSkillError(
            f"unsafe pack SKILL.md: received {skill_md}, "
            "expected a regular file under the pack root (not a symlink)"
        )
    try:
        frontmatter = parse_yaml_frontmatter(read_frontmatter_text(skill_md))
    except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
        # WHY: SeedSkillError soft-fails into summary.failed; raw parse errors omit path.
        raise SeedSkillError(
            f"unparseable pack SKILL.md: received {skill_md}, "
            f"expected agentskills.io YAML frontmatter with string name/description "
            f"fields; parse error={exc!r}"
        ) from exc
    return skill_name_from_frontmatter(frontmatter, directory_name=skill_md.parent.name)


def _validated_destination_dir(destination_root: Path, slug: str) -> Path:
    """Return unresolved ``destination_root / slug`` after path-safety checks.

    Refuses symlink destinations (in-tree or escaping) so force overwrite cannot
    follow a slug symlink and clobber a sibling skill tree.
    """
    if not _SLUG_PATTERN.fullmatch(slug):
        raise SeedSkillError(
            f"invalid skill slug: received {slug!r}, "
            f"expected pattern matching {_SLUG_PATTERN_HELP}"
        )
    dest_dir = destination_root / slug
    if dest_dir.is_symlink():
        raise SeedSkillError(
            f"skill destination is a symlink: received {dest_dir}, "
            "expected a real (non-symlink) directory path under destination_root"
        )
    resolved_root = destination_root.resolve()
    resolved_dest = dest_dir.resolve()
    if not resolved_dest.is_relative_to(resolved_root):
        raise SeedSkillError(
            f"skill destination escapes destination_root: "
            f"received slug={slug!r} resolved={resolved_dest}, "
            f"expected path relative to {resolved_root}"
        )
    return dest_dir


def _ignore_symlinks_in_skill_tree(directory: str, names: list[str]) -> set[str]:
    """Skip symlink entries so copytree does not dereference pack contents."""
    ignored: set[str] = set()
    for name in names:
        if (Path(directory) / name).is_symlink():
            ignored.add(name)
    return ignored


def _unique_sibling_path(destination_root: Path, *, prefix: str, slug: str) -> Path:
    """Return a unique path under ``destination_root`` for staging or backup."""
    return destination_root / f".{prefix}-{slug}-{uuid.uuid4().hex}"


def _cleanup_tree_if_exists(path: Path) -> None:
    """Best-effort removal of a staging/backup tree."""
    if path.exists() or path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)


def _copy_skill_directory(source_dir: Path, dest_dir: Path) -> None:
    """Atomically replace ``dest_dir`` via staging + rename (force-safe).

    WHY: rmtree-then-copytree leaves a partial hole if copytree fails mid-way;
    staging + backup rename keeps the prior tree until the new tree is in place.
    """
    destination_root = dest_dir.parent
    staging_dir = _unique_sibling_path(
        destination_root, prefix="seed-staging", slug=dest_dir.name
    )
    try:
        # WHY: default copytree dereferences sibling symlinks into user skills.
        shutil.copytree(source_dir, staging_dir, ignore=_ignore_symlinks_in_skill_tree)
        if dest_dir.exists() or dest_dir.is_symlink():
            backup_dir = _unique_sibling_path(
                destination_root, prefix="seed-backup", slug=dest_dir.name
            )
            dest_dir.rename(backup_dir)
            try:
                staging_dir.rename(dest_dir)
            except OSError:
                # WHY: restore prior tree; leave backup if restore itself fails.
                backup_dir.rename(dest_dir)
                raise
            shutil.rmtree(backup_dir)
        else:
            staging_dir.rename(dest_dir)
    except OSError as exc:
        # WHY: never rmtree backup here — it may still hold the operator's prior skill.
        _cleanup_tree_if_exists(staging_dir)
        raise SeedSkillError(
            f"failed to copy skill directory: received source={source_dir}, "
            f"dest={dest_dir}, expected readable pack skill dir and writable "
            f"destination; os_error={exc!r}"
        ) from exc
