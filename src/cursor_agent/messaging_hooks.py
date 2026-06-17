"""Install and resolve versioned messaging hook sources (PRD-005 T3)."""

from __future__ import annotations

import json
import logging
import shutil
import stat
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from cursor_agent.facade_logging import emit_hook_deploy

MESSAGING_HOOK_FILENAMES: tuple[str, ...] = (
    "hooks.json",
    "pre-tool-deny-write.sh",
    "shell-gate.sh",
    "mcp-deny.sh",
    "read-sensitive-deny.sh",
    "sensitive-paths.sh",
)

DEFAULT_USER_MESSAGING_HOOKS_DIR = Path.home() / ".cursor-agent" / "hooks" / "messaging"
WORKSPACE_MESSAGING_HOOKS_RELATIVE = Path(".cursor") / "hooks" / "messaging"
WORKSPACE_PROJECT_HOOKS_RELATIVE = Path(".cursor") / "hooks.json"
WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX = ".cursor/hooks/messaging"


class HookEntry(BaseModel):
    """Single hook binding in a Cursor hooks.json manifest."""

    model_config = ConfigDict(extra="allow")

    command: str
    matcher: str | None = None
    failClosed: bool | None = None


class HookManifest(BaseModel):
    """Cursor hooks.json schema v1 manifest."""

    version: int = 1
    hooks: dict[str, list[HookEntry]] = Field(default_factory=dict)


def _packaged_messaging_hooks_dir() -> Path:
    """Return the wheel-packaged messaging hooks directory."""
    packaged = resources.files("cursor_agent").joinpath("hooks/messaging")
    return Path(str(packaged))


def _checkout_messaging_hooks_dir() -> Path:
    """Return the repository checkout messaging hooks directory."""
    module_dir = Path(__file__).resolve().parent
    return module_dir.parents[1] / "hooks" / "messaging"


def resolve_messaging_hook_source_dir() -> Path:
    """Resolve messaging hook sources from package or repository checkout.

    Example:
        >>> path = resolve_messaging_hook_source_dir()
        >>> (path / "hooks.json").is_file()
        True
    """
    for candidate in (_packaged_messaging_hooks_dir(), _checkout_messaging_hooks_dir()):
        if _is_complete_hook_source_dir(candidate):
            return candidate.resolve()

    searched = ", ".join(
        str(path)
        for path in (_packaged_messaging_hooks_dir(), _checkout_messaging_hooks_dir())
    )
    msg = (
        f"messaging hook sources not found: searched [{searched}], "
        f"expected files {list(MESSAGING_HOOK_FILENAMES)!r}"
    )
    raise FileNotFoundError(msg)


def _is_complete_hook_source_dir(directory: Path) -> bool:
    """Return True when directory contains the full messaging hook manifest."""
    if not directory.is_dir():
        return False
    return all((directory / name).is_file() for name in MESSAGING_HOOK_FILENAMES)


def _copy_hook_tree(source_dir: Path, target_dir: Path) -> None:
    """Copy hook manifest files into target_dir, preserving script executability."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in MESSAGING_HOOK_FILENAMES:
        src = source_dir / filename
        dst = target_dir / filename
        if not src.is_file():
            msg = (
                f"missing messaging hook source file: expected {src!r} to exist "
                f"before install to {target_dir!r}"
            )
            raise FileNotFoundError(msg)
        shutil.copy2(src, dst)
        if filename.endswith(".sh"):
            mode = dst.stat().st_mode
            dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_messaging_hooks(
    *,
    target_dir: Path | None = None,
    source_dir: Path | None = None,
) -> Path:
    """Copy messaging hook sources into the user hook directory idempotently.

    Example:
        >>> installed = install_messaging_hooks(target_dir=Path("/tmp/hooks/messaging"))
        >>> (installed / "hooks.json").is_file()
        True
    """
    resolved_target = (
        DEFAULT_USER_MESSAGING_HOOKS_DIR if target_dir is None else target_dir
    ).resolve()
    resolved_source = (
        resolve_messaging_hook_source_dir() if source_dir is None else source_dir
    ).resolve()
    _copy_hook_tree(resolved_source, resolved_target)
    return resolved_target


def workspace_messaging_hooks_dir(workspace: Path | str) -> Path:
    """Return the workspace-relative messaging hook deploy directory.

    Example:
        >>> workspace_messaging_hooks_dir("/tmp/project").name
        'messaging'
    """
    return Path(workspace).resolve() / WORKSPACE_MESSAGING_HOOKS_RELATIVE


def workspace_project_hooks_manifest_path(workspace: Path | str) -> Path:
    """Return Cursor's project-level hooks.json path for a workspace.

    Example:
        >>> workspace_project_hooks_manifest_path("/tmp/project").name
        'hooks.json'
    """
    return Path(workspace).resolve() / WORKSPACE_PROJECT_HOOKS_RELATIVE


def _prune_stale_hook_files(target_dir: Path) -> None:
    """Remove messaging hook files no longer present in the manifest."""
    if not target_dir.is_dir():
        return
    allowed = {
        filename for filename in MESSAGING_HOOK_FILENAMES if filename.endswith(".sh")
    }
    for entry in target_dir.iterdir():
        if entry.is_file() and entry.name not in allowed:
            entry.unlink()


def _copy_hook_scripts(source_dir: Path, target_dir: Path) -> None:
    """Copy only hook scripts into the workspace script directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in MESSAGING_HOOK_FILENAMES:
        if not filename.endswith(".sh"):
            continue
        src = source_dir / filename
        dst = target_dir / filename
        if not src.is_file():
            msg = f"missing messaging hook script: expected {src!r} to exist"
            raise FileNotFoundError(msg)
        shutil.copy2(src, dst)
        mode = dst.stat().st_mode
        dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _read_manifest(path: Path) -> HookManifest:
    """Read a hooks.json manifest or return an empty schema v1 manifest."""
    if not path.is_file():
        return HookManifest()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"invalid hooks manifest: received {loaded!r}, expected JSON object"
        raise ValueError(msg)
    return HookManifest.model_validate(loaded)


def _messaging_command_path(script_name: str) -> str:
    """Return project-root-relative command path for a messaging hook script."""
    return f"{WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX}/{script_name}"


def _rewrite_messaging_manifest(source_manifest: HookManifest) -> HookManifest:
    """Rewrite source hook commands for Cursor project hook execution."""
    rewritten_hooks: dict[str, list[HookEntry]] = {}
    for event, entries in source_manifest.hooks.items():
        rewritten_entries: list[HookEntry] = []
        for entry in entries:
            script_name = Path(entry.command).name
            rewritten_entries.append(
                entry.model_copy(
                    update={"command": _messaging_command_path(script_name)}
                )
            )
        rewritten_hooks[str(event)] = rewritten_entries
    return HookManifest(hooks=rewritten_hooks)


def _without_existing_messaging_hooks(manifest: HookManifest) -> HookManifest:
    """Return manifest with prior messaging hook command entries removed."""
    kept_hooks: dict[str, list[HookEntry]] = {}
    for event, entries in manifest.hooks.items():
        kept_entries = [
            entry
            for entry in entries
            if not entry.command.startswith(
                f"{WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX}/"
            )
        ]
        if kept_entries:
            kept_hooks[str(event)] = kept_entries
    return HookManifest(hooks=kept_hooks)


def _write_project_manifest(source_dir: Path, manifest_path: Path) -> None:
    """Write project-level hooks.json with messaging entries using project paths."""
    existing = _without_existing_messaging_hooks(_read_manifest(manifest_path))
    messaging = _rewrite_messaging_manifest(_read_manifest(source_dir / "hooks.json"))
    merged_hooks = dict(existing.hooks)
    for event, entries in messaging.hooks.items():
        merged_hooks.setdefault(event, [])
        merged_hooks[event].extend(entries)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            HookManifest(hooks=merged_hooks).model_dump(mode="json"),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _resolve_installed_hooks_dir(user_hooks_dir: Path | None) -> Path:
    """Return the installed user hook directory or raise when hooks are missing."""
    resolved = (
        DEFAULT_USER_MESSAGING_HOOKS_DIR if user_hooks_dir is None else user_hooks_dir
    ).resolve()
    if not _is_complete_hook_source_dir(resolved):
        msg = (
            f"messaging hooks not installed: expected {resolved!r} to contain "
            f"{list(MESSAGING_HOOK_FILENAMES)!r}; call ensure_messaging_hooks first"
        )
        raise FileNotFoundError(msg)
    return resolved


def deploy_messaging_hooks_to_workspace(
    workspace: Path | str,
    *,
    user_hooks_dir: Path | None = None,
    logger: logging.Logger | None = None,
) -> Path:
    """Copy installed messaging hooks into the active workspace hook directory.

    Example:
        >>> deploy_messaging_hooks_to_workspace("/tmp/project")
        PosixPath('/tmp/project/.cursor/hooks/messaging')
    """
    workspace_path = Path(workspace).resolve()
    target_dir = workspace_messaging_hooks_dir(workspace_path)
    manifest_path = workspace_project_hooks_manifest_path(workspace_path)
    installed_dir = _resolve_installed_hooks_dir(user_hooks_dir)
    try:
        _prune_stale_hook_files(target_dir)
        _copy_hook_scripts(installed_dir, target_dir)
        _write_project_manifest(installed_dir, manifest_path)
    except OSError as exc:
        if logger is not None:
            emit_hook_deploy(
                logger,
                profile="messaging",
                workspace=str(workspace_path),
                status="error",
                error=str(exc),
            )
        raise
    if logger is not None:
        emit_hook_deploy(
            logger,
            profile="messaging",
            workspace=str(workspace_path),
            status="ok",
        )
    return target_dir


def ensure_messaging_hooks(
    workspace: Path | str,
    *,
    user_hooks_dir: Path | None = None,
    source_dir: Path | None = None,
    logger: logging.Logger | None = None,
) -> Path:
    """Install messaging hooks once and deploy them into the workspace.

    Example:
        >>> ensure_messaging_hooks("/tmp/project")
        PosixPath('/tmp/project/.cursor/hooks/messaging')
    """
    installed_dir = install_messaging_hooks(
        target_dir=user_hooks_dir,
        source_dir=source_dir,
    )
    return deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=installed_dir,
        logger=logger,
    )
