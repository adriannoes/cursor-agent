"""First-run marker persistence for CLI onboarding (PRD-011, ADR-027 §5)."""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from cursor_agent.cli.startup import resolve_sessions_db_path

MARKER_FILENAME = "first_run_complete"
_MODULE_LOGGER = logging.getLogger(__name__)
_warned_symlink_homes: set[str] = set()
_warned_unwritable_homes: set[str] = set()


@dataclass(frozen=True, slots=True)
class MarkerPaths:
    """Canonical marker home and contained marker file path.

    Example:
        >>> paths = resolve_marker_paths(Path("/tmp/cursor-agent"))
        >>> paths.marker_path.name
        'first_run_complete'
    """

    marker_home: Path
    canonical_home: Path
    marker_path: Path


def default_marker_home() -> Path:
    """Return the default config home for the first-run marker."""
    return resolve_sessions_db_path().parent


def resolve_marker_paths(marker_home: Path) -> MarkerPaths:
    """Return canonical marker paths without requiring the marker file."""
    canonical_home = _canonicalize_marker_home(marker_home)
    marker_path = canonical_home / MARKER_FILENAME
    _reject_escaping_marker_path(
        marker_home=marker_home,
        canonical_home=canonical_home,
        marker_path=marker_path,
    )
    return MarkerPaths(
        marker_home=marker_home,
        canonical_home=canonical_home,
        marker_path=marker_path,
    )


def marker_path_for(marker_home: Path) -> Path:
    """Return the resolved marker file path under ``marker_home``."""
    return resolve_marker_paths(marker_home).marker_path


def is_first_run(*, marker_home: Path) -> bool:
    """Return ``True`` when the first-run marker file is absent."""
    return not marker_path_for(marker_home).exists()


def mark_complete(
    *,
    marker_home: Path,
    banner_suppressed: bool = False,
    is_ci: bool = False,
    logger: logging.Logger | None = None,
    stderr: TextIO | None = None,
) -> bool:
    """Persist first-run completion after a non-suppressed banner.

    Returns ``True`` when the marker already exists or was written successfully.
    Returns ``False`` when persistence is skipped or degraded.
    """
    if banner_suppressed:
        return False

    paths = resolve_marker_paths(marker_home)
    if paths.marker_path.exists():
        return True

    if marker_home.is_symlink():
        _warn_symlink_once(marker_home=marker_home, stderr=stderr)
        return False

    active_logger = logger if logger is not None else _MODULE_LOGGER
    active_stderr = stderr if stderr is not None else sys.stderr

    try:
        paths.canonical_home.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _degrade_unwritable(
            marker_home=marker_home,
            marker_path=paths.marker_path,
            reason=exc,
            is_ci=is_ci,
            logger=active_logger,
            stderr=active_stderr,
        )
        return False

    try:
        _write_marker_atomic(paths)
    except OSError as exc:
        _degrade_unwritable(
            marker_home=marker_home,
            marker_path=paths.marker_path,
            reason=exc,
            is_ci=is_ci,
            logger=active_logger,
            stderr=active_stderr,
        )
        return False

    return True


def reset_warning_state_for_tests() -> None:
    """Clear warn-once state so unit tests stay isolated."""
    _warned_symlink_homes.clear()
    _warned_unwritable_homes.clear()


def _canonicalize_marker_home(marker_home: Path) -> Path:
    """Resolve ``marker_home`` to its canonical directory path."""
    try:
        return marker_home.resolve(strict=False)
    except OSError as exc:
        msg = (
            f"invalid marker home: could not resolve {marker_home!s}: {exc}, "
            "expected a valid config directory"
        )
        raise ValueError(msg) from exc


def _reject_escaping_marker_path(
    *,
    marker_home: Path,
    canonical_home: Path,
    marker_path: Path,
) -> None:
    """Reject a marker path that resolves outside the canonical config home."""
    try:
        resolved_marker = marker_path.resolve(strict=False)
    except OSError as exc:
        msg = (
            f"invalid marker path: could not resolve {marker_path!s} under "
            f"{marker_home!s}: {exc}, expected path contained under the config home"
        )
        raise ValueError(msg) from exc
    if not resolved_marker.is_relative_to(canonical_home):
        msg = (
            f"marker path {marker_path!s} escapes config home {marker_home!s}, "
            f"expected path contained under {canonical_home!s}"
        )
        raise ValueError(msg)


def _write_marker_atomic(paths: MarkerPaths) -> None:
    """Write the marker through a temp file and atomic replace in the same parent."""
    if paths.marker_path.is_symlink():
        msg = (
            f"marker file {paths.marker_path!s} must not be a symlink, "
            f"expected regular file contained under {paths.canonical_home!s}"
        )
        raise OSError(msg)

    fd, temp_path_str = tempfile.mkstemp(
        prefix=f".{MARKER_FILENAME}.",
        suffix=".tmp",
        dir=paths.canonical_home,
    )
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, paths.marker_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise


def _warn_symlink_once(*, marker_home: Path, stderr: TextIO | None) -> None:
    """Emit a single stderr warning for symlinked config homes."""
    warning_key = str(marker_home)
    if warning_key in _warned_symlink_homes:
        return
    _warned_symlink_homes.add(warning_key)
    active_stderr = stderr if stderr is not None else sys.stderr
    message = (
        f"warning: first-run marker home {marker_home!s} is a symlink; "
        "expected a regular directory — marker will not be persisted"
    )
    print(message, file=active_stderr)


def _degrade_unwritable(
    *,
    marker_home: Path,
    marker_path: Path,
    reason: BaseException,
    is_ci: bool,
    logger: logging.Logger,
    stderr: TextIO,
) -> None:
    """Log debug context and optionally warn once when persistence is impossible."""
    logger.debug(
        "first-run marker not persisted at %s under %s: %s, "
        "expected writable config directory",
        marker_path,
        marker_home,
        reason,
    )
    if is_ci:
        return
    warning_key = str(marker_home)
    if warning_key in _warned_unwritable_homes:
        return
    _warned_unwritable_homes.add(warning_key)
    print(
        f"warning: could not persist first-run marker at {marker_path!s}: {reason}, "
        "expected writable config directory",
        file=stderr,
    )
