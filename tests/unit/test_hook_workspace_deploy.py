"""Unit tests for messaging hook workspace deploy (PRD-005)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

from tests.unit.hooks_helpers import EVENT_SCRIPT_MAP, REQUIRED_HOOK_SCRIPTS


def test_deploy_workspace_hooks_copies_manifest(tmp_path: Path) -> None:
    """Deploy must write Cursor's project hook manifest plus messaging scripts."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=user_hooks)

    deployed = messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )
    manifest_path = workspace / ".cursor" / "hooks.json"
    scripts_dir = workspace / ".cursor" / "hooks" / "messaging"
    assert deployed == scripts_dir.resolve()
    assert manifest_path.is_file()
    assert not (scripts_dir / "hooks.json").exists()
    for filename in REQUIRED_HOOK_SCRIPTS:
        assert (scripts_dir / filename).is_file(), f"missing deployed file {filename!r}"
    assert (scripts_dir / "sensitive-paths.sh").is_file()


def test_ensure_messaging_hooks_is_single_entry_point(tmp_path: Path) -> None:
    """ensure_messaging_hooks must install user hooks and deploy to workspace."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    deployed = messaging_hooks.ensure_messaging_hooks(workspace)
    scripts_dir = workspace / ".cursor" / "hooks" / "messaging"
    assert deployed == scripts_dir.resolve()
    assert (workspace / ".cursor" / "hooks.json").is_file()
    assert (scripts_dir / "sensitive-paths.sh").is_file()


def test_deploy_workspace_hooks_manifest_uses_project_root_paths(
    tmp_path: Path,
) -> None:
    """Deployed hook commands must be relative to the project root."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=user_hooks)

    messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )
    manifest_path = workspace / ".cursor" / "hooks.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hooks = manifest["hooks"]
    for event, script_name in EVENT_SCRIPT_MAP.items():
        commands = [entry["command"] for entry in hooks[event]]
        expected = f".cursor/hooks/messaging/{script_name}"
        assert expected in commands
        assert f"./{script_name}" not in commands


def test_deploy_workspace_hooks_preserves_executable_bits(tmp_path: Path) -> None:
    """Deployed shell hook scripts must remain executable."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=user_hooks)
    messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )
    target = workspace / ".cursor" / "hooks" / "messaging"
    for script_name in REQUIRED_HOOK_SCRIPTS:
        mode = (target / script_name).stat().st_mode
        assert mode & stat.S_IXUSR, f"{script_name!r} must be executable for owner"


def test_deploy_workspace_hooks_is_idempotent(tmp_path: Path) -> None:
    """Repeated workspace deploys must not fail and must keep the same file set."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=user_hooks)

    first = messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )
    manifest_path = workspace / ".cursor" / "hooks.json"
    before_manifest = manifest_path.read_bytes()
    before = {name: (first / name).read_bytes() for name in REQUIRED_HOOK_SCRIPTS}
    second = messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )
    after_manifest = manifest_path.read_bytes()
    after = {name: (second / name).read_bytes() for name in REQUIRED_HOOK_SCRIPTS}
    assert first == second
    assert before_manifest == after_manifest
    assert before == after


def test_deploy_workspace_hooks_replaces_stale_profile_files(tmp_path: Path) -> None:
    """Deploy must remove stale messaging hook files from prior deploys."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=user_hooks)
    target = workspace / ".cursor" / "hooks" / "messaging"
    target.mkdir(parents=True)
    stale = target / "legacy-hook.sh"
    stale.write_text("#!/bin/sh\necho stale\n", encoding="utf-8")

    messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )

    assert not stale.exists()
    for filename in REQUIRED_HOOK_SCRIPTS:
        assert (target / filename).is_file()
