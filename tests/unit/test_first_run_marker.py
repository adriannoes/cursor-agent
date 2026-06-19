"""Unit tests for first-run marker persistence (PRD-011, T3)."""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.cli.first_run_marker import (
    MARKER_FILENAME,
    default_marker_home,
    is_first_run,
    mark_complete,
    marker_path_for,
    reset_warning_state_for_tests,
    resolve_marker_paths,
)
from cursor_agent.cli.startup import DEFAULT_DB_PATH

_SYMLINKS_SUPPORTED = hasattr(os, "symlink")


def _marker_home(tmp_path: Path) -> Path:
    """Injectable config home for marker tests."""
    home = tmp_path / "cursor-agent"
    home.mkdir(parents=True, exist_ok=True)
    return home


def test_default_marker_home_matches_sessions_db_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default marker home reuses the sessions DB parent directory."""
    monkeypatch.delenv("CURSOR_AGENT_SESSIONS_DB", raising=False)
    assert default_marker_home() == DEFAULT_DB_PATH.parent


def test_default_marker_home_follows_sessions_db_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """First-run marker home stays aligned with CURSOR_AGENT_SESSIONS_DB parent."""
    db_path = tmp_path / "nested" / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT_SESSIONS_DB", str(db_path))
    assert default_marker_home() == db_path.parent


def test_is_first_run_when_marker_absent(tmp_path: Path) -> None:
    """First run is detected when the marker file is absent."""
    marker_home = _marker_home(tmp_path)
    assert is_first_run(marker_home=marker_home) is True
    assert not marker_path_for(marker_home).exists()


def test_is_first_run_false_when_marker_present(tmp_path: Path) -> None:
    """Recurring run is detected when the marker file exists."""
    marker_home = _marker_home(tmp_path)
    marker_path_for(marker_home).write_text("", encoding="utf-8")
    assert is_first_run(marker_home=marker_home) is False


def test_mark_complete_skipped_when_banner_suppressed(tmp_path: Path) -> None:
    """Banner suppression skips marker persistence."""
    marker_home = _marker_home(tmp_path)
    result = mark_complete(marker_home=marker_home, banner_suppressed=True)
    assert result is False
    assert not marker_path_for(marker_home).exists()
    assert is_first_run(marker_home=marker_home) is True


def test_mark_complete_persists_marker_when_not_suppressed(tmp_path: Path) -> None:
    """Non-suppressed mark_complete creates the marker file."""
    marker_home = _marker_home(tmp_path)
    result = mark_complete(marker_home=marker_home, banner_suppressed=False)
    assert result is True
    assert marker_path_for(marker_home).exists()
    assert is_first_run(marker_home=marker_home) is False


def test_mark_complete_is_idempotent_when_marker_already_present(
    tmp_path: Path,
) -> None:
    """mark_complete returns True without rewriting an existing marker."""
    marker_home = _marker_home(tmp_path)
    marker_path = marker_path_for(marker_home)
    marker_path.write_text("existing\n", encoding="utf-8")
    with patch("cursor_agent.cli.first_run_marker.os.replace") as replace_mock:
        result = mark_complete(marker_home=marker_home, banner_suppressed=False)
    assert result is True
    replace_mock.assert_not_called()
    assert marker_path.read_text(encoding="utf-8") == "existing\n"


def test_mark_complete_writes_atomically_via_temp_in_same_parent(
    tmp_path: Path,
) -> None:
    """Marker is written with temp file + replace in the canonical parent."""
    marker_home = _marker_home(tmp_path)
    canonical_home = resolve_marker_paths(marker_home).canonical_home
    with (
        patch(
            "cursor_agent.cli.first_run_marker.tempfile.mkstemp",
            wraps=tempfile.mkstemp,
        ) as mkstemp_mock,
        patch(
            "cursor_agent.cli.first_run_marker.os.replace",
            wraps=os.replace,
        ) as replace_mock,
    ):
        result = mark_complete(marker_home=marker_home, banner_suppressed=False)
    assert result is True
    assert mkstemp_mock.call_args.kwargs["dir"] == canonical_home
    replace_mock.assert_called_once()
    src_path = Path(replace_mock.call_args.args[0])
    dst_path = Path(replace_mock.call_args.args[1])
    assert src_path.parent == canonical_home
    assert dst_path == marker_path_for(marker_home)
    assert not list(canonical_home.glob(f".{MARKER_FILENAME}.*.tmp"))


def test_mark_complete_unwritable_parent_degrades_without_crash(tmp_path: Path) -> None:
    """Unwritable marker home degrades gracefully without raising."""
    reset_warning_state_for_tests()
    marker_home = _marker_home(tmp_path)
    marker_home.chmod(stat.S_IRUSR | stat.S_IXUSR)
    stderr = StringIO()
    logger = logging.getLogger("test.first_run_marker.unwritable")
    log_messages: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: log_messages.append(record.getMessage())  # type: ignore[method-assign]
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    try:
        result = mark_complete(
            marker_home=marker_home,
            banner_suppressed=False,
            is_ci=False,
            logger=logger,
            stderr=stderr,
        )
    finally:
        marker_home.chmod(stat.S_IRWXU)

    assert result is False
    assert not marker_path_for(marker_home).exists()
    assert any(marker_home.as_posix() in message for message in log_messages)
    assert "warning:" in stderr.getvalue()


def test_mark_complete_unwritable_parent_skips_warning_in_ci(tmp_path: Path) -> None:
    """CI mode suppresses the one-time unwritable warning on stderr."""
    reset_warning_state_for_tests()
    marker_home = _marker_home(tmp_path)
    marker_home.chmod(stat.S_IRUSR | stat.S_IXUSR)
    stderr = StringIO()

    try:
        result = mark_complete(
            marker_home=marker_home,
            banner_suppressed=False,
            is_ci=True,
            stderr=stderr,
        )
    finally:
        marker_home.chmod(stat.S_IRWXU)

    assert result is False
    assert stderr.getvalue() == ""


def _symlinked_marker_home(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(marker_home_symlink, symlink_target)`` for degradation tests."""
    target = tmp_path / "marker-target"
    target.mkdir(parents=True, exist_ok=True)
    marker_home = tmp_path / "cursor-agent"
    marker_home.symlink_to(target, target_is_directory=True)
    return marker_home, target


@pytest.mark.skipif(not _SYMLINKS_SUPPORTED, reason="platform cannot create symlinks")
def test_symlinked_marker_home_warns_once_and_does_not_persist(tmp_path: Path) -> None:
    """Symlinked marker home warns once on stderr and skips persistence."""
    reset_warning_state_for_tests()
    marker_home, target = _symlinked_marker_home(tmp_path)
    stderr = StringIO()

    first = mark_complete(
        marker_home=marker_home, banner_suppressed=False, stderr=stderr
    )
    second = mark_complete(
        marker_home=marker_home, banner_suppressed=False, stderr=stderr
    )

    assert first is False
    assert second is False
    assert not (target / MARKER_FILENAME).exists()
    assert not marker_path_for(marker_home).exists()
    warning_lines = [
        line for line in stderr.getvalue().splitlines() if "warning:" in line
    ]
    assert len(warning_lines) == 1
    assert "symlink" in stderr.getvalue().lower()
    assert marker_home.as_posix() in stderr.getvalue()


def test_marker_writes_stay_contained_under_canonical_home(tmp_path: Path) -> None:
    """Marker and temp artifacts remain under the resolved config home."""
    canonical_home = (tmp_path / "cfg" / "nested").resolve()
    canonical_home.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker_home = tmp_path / "cfg" / "nested" / ".." / "nested"

    result = mark_complete(marker_home=marker_home, banner_suppressed=False)
    assert result is True

    for path in tmp_path.rglob("*"):
        if path.name == MARKER_FILENAME or (
            path.name.startswith(f".{MARKER_FILENAME}.") and path.name.endswith(".tmp")
        ):
            resolved = path.resolve()
            assert resolved.is_relative_to(canonical_home)
            assert not resolved.is_relative_to(outside)
