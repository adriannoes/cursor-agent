"""Filesystem path containment for cron configuration (PRD-010)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cursor_agent.cron.models import JOBS_FILENAME
from cursor_agent.errors import ConfigError

DEFAULT_CRON_ROOT = Path.home() / ".cursor-agent" / "cron"


@dataclass(frozen=True, slots=True)
class CronPaths:
    """Canonical cron root and contained ``jobs.yaml`` path.

    Example:
        >>> paths = resolve_cron_paths(Path("/tmp/cron"))
        >>> paths.jobs_file.name
        'jobs.yaml'
    """

    canonical_root: Path
    jobs_file: Path


def canonicalize_cron_root(cron_root: Path) -> Path:
    """Return the resolved cron root, rejecting symlinked configuration roots."""
    if cron_root.is_symlink():
        msg = (
            f"cron root {cron_root!s} must not be a symlink, "
            "expected a regular directory for cron configuration"
        )
        raise ConfigError(msg)
    try:
        return cron_root.resolve(strict=False)
    except OSError as exc:
        msg = (
            f"invalid cron root: could not resolve {cron_root!s}: {exc}, "
            "expected a valid cron configuration directory"
        )
        raise ConfigError(msg) from exc


def resolve_cron_paths(cron_root: Path) -> CronPaths:
    """Return canonical root and ``jobs.yaml`` path without requiring the file."""
    canonical_root = canonicalize_cron_root(cron_root)
    return CronPaths(
        canonical_root=canonical_root,
        jobs_file=canonical_root / JOBS_FILENAME,
    )


def resolve_cron_jobs_file(cron_root: Path) -> Path | None:
    """Return ``jobs.yaml`` when present and contained; ``None`` when missing."""
    paths = resolve_cron_paths(cron_root)
    jobs_path = paths.jobs_file
    if not jobs_path.exists():
        return None
    _reject_unsafe_jobs_file(
        cron_root=cron_root,
        canonical_root=paths.canonical_root,
        jobs_path=jobs_path,
        resolve_strict=True,
    )
    return jobs_path


def validate_cron_jobs_file_for_write(cron_root: Path) -> CronPaths:
    """Validate cron paths before atomic writes, lock acquisition, or temp files."""
    paths = resolve_cron_paths(cron_root)
    if paths.jobs_file.exists():
        _reject_unsafe_jobs_file(
            cron_root=cron_root,
            canonical_root=paths.canonical_root,
            jobs_path=paths.jobs_file,
            resolve_strict=False,
        )
    else:
        _reject_escaping_jobs_path(
            cron_root=cron_root,
            canonical_root=paths.canonical_root,
            jobs_path=paths.jobs_file,
        )
    return paths


def _reject_unsafe_jobs_file(
    *,
    cron_root: Path,
    canonical_root: Path,
    jobs_path: Path,
    resolve_strict: bool,
) -> None:
    """Reject symlinked or escaping ``jobs.yaml`` paths."""
    if jobs_path.is_symlink():
        msg = (
            f"cron jobs file {jobs_path!s} must not be a symlink, "
            f"expected regular file contained under {canonical_root!s}"
        )
        raise ConfigError(msg)
    try:
        resolved_jobs = jobs_path.resolve(strict=resolve_strict)
    except OSError as exc:
        msg = (
            f"invalid cron jobs path: could not resolve {jobs_path!s} under "
            f"{cron_root!s}: {exc}"
        )
        raise ConfigError(msg) from exc
    if not resolved_jobs.is_relative_to(canonical_root):
        msg = (
            f"cron jobs file {jobs_path!s} escapes cron root {cron_root!s}, "
            "expected path contained under the configured cron directory"
        )
        raise ConfigError(msg)


def _reject_escaping_jobs_path(
    *,
    cron_root: Path,
    canonical_root: Path,
    jobs_path: Path,
) -> None:
    """Reject a would-be ``jobs.yaml`` path that resolves outside the cron root."""
    try:
        resolved_jobs = jobs_path.resolve(strict=False)
    except OSError as exc:
        msg = (
            f"invalid cron jobs path: could not resolve {jobs_path!s} under "
            f"{cron_root!s}: {exc}"
        )
        raise ConfigError(msg) from exc
    if not resolved_jobs.is_relative_to(canonical_root):
        msg = (
            f"cron jobs file {jobs_path!s} escapes cron root {cron_root!s}, "
            "expected path contained under the configured cron directory"
        )
        raise ConfigError(msg)
