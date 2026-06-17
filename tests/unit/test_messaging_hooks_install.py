"""Unit tests for messaging hook user-directory install."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from cursor_agent.errors import ConfigError
from tests.unit.messaging_hook_test_helpers import REQUIRED_HOOK_FILES


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


def test_ensure_messaging_hooks_installs_once(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """ensure_messaging_hooks must not invoke install more than once per call."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks" / "messaging"
    install_calls = 0
    original_install = messaging_hooks.install_messaging_hooks

    def counting_install(**kwargs: object) -> Path:
        nonlocal install_calls
        install_calls += 1
        return original_install(**kwargs)

    monkeypatch.setattr(messaging_hooks, "install_messaging_hooks", counting_install)
    messaging_hooks.ensure_messaging_hooks(
        workspace,
        user_hooks_dir=user_hooks,
    )
    assert install_calls == 1


def test_resolve_missing_hook_sources_raises_config_error(
    monkeypatch: MonkeyPatch,
) -> None:
    """Missing hook sources must raise ConfigError with an actionable message."""
    from cursor_agent import messaging_hooks

    messaging_hooks.messaging_hook_source_fingerprint.cache_clear()
    monkeypatch.setattr(
        messaging_hooks,
        "_is_complete_hook_source_dir",
        lambda _directory: False,
    )

    with pytest.raises(ConfigError, match="messaging hook sources not found"):
        messaging_hooks.resolve_messaging_hook_source_dir()
