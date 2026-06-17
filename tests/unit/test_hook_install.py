"""Unit tests for messaging hook user-directory install (PRD-005)."""

from __future__ import annotations

import stat
from pathlib import Path

from tests.unit.hooks_helpers import REQUIRED_HOOK_FILES


def test_install_user_hooks_copies_manifest(tmp_path: Path) -> None:
    """Install must copy the full messaging hook manifest to the target dir."""
    from cursor_agent import messaging_hooks

    target = tmp_path / "hooks" / "messaging"
    installed = messaging_hooks.install_messaging_hooks(target_dir=target)
    assert installed == target.resolve()
    for filename in REQUIRED_HOOK_FILES:
        assert (target / filename).is_file(), f"missing installed file {filename!r}"


def test_install_user_hooks_preserves_executable_bits(tmp_path: Path) -> None:
    """Shell hook scripts must remain executable after install."""
    from cursor_agent import messaging_hooks

    target = tmp_path / "hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=target)
    for script_name in REQUIRED_HOOK_FILES:
        if not script_name.endswith(".sh"):
            continue
        mode = (target / script_name).stat().st_mode
        assert mode & stat.S_IXUSR, f"{script_name!r} must be executable for owner"


def test_install_user_hooks_is_idempotent(tmp_path: Path) -> None:
    """Repeated installs must not fail and must keep the same file set."""
    from cursor_agent import messaging_hooks

    target = tmp_path / "hooks" / "messaging"
    first = messaging_hooks.install_messaging_hooks(target_dir=target)
    before = {name: (target / name).read_bytes() for name in REQUIRED_HOOK_FILES}
    second = messaging_hooks.install_messaging_hooks(target_dir=target)
    after = {name: (target / name).read_bytes() for name in REQUIRED_HOOK_FILES}
    assert first == second
    assert before == after


def test_packaged_hook_sources_resolve_from_module() -> None:
    """Installed package must expose messaging hook sources via the module."""
    from cursor_agent import messaging_hooks

    source_dir = messaging_hooks.resolve_messaging_hook_source_dir()
    assert source_dir.is_dir(), (
        f"expected messaging hook source directory, got {source_dir!r}"
    )
    for filename in REQUIRED_HOOK_FILES:
        assert (source_dir / filename).is_file(), (
            f"packaged hook source missing {filename!r} under {source_dir!r}"
        )
