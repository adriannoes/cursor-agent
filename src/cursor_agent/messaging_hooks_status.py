"""Messaging hooks status reporting for ``doctor`` (PRD-017 FR-2).

Separated from deploy/install in ``messaging_hooks`` so doctor completeness
checks do not grow the install module past the preferred size band.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cursor_agent.errors import ConfigError
from cursor_agent.messaging_hooks import (
    MESSAGING_HOOK_FILENAMES,
    WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX,
    HookManifest,
    read_hook_manifest,
    resolve_messaging_hook_source_dir,
    rewrite_messaging_manifest,
    workspace_messaging_hooks_dir,
    workspace_project_hooks_manifest_path,
)


@dataclass(frozen=True)
class MessagingHooksStatusReport:
    """Public messaging-hooks status for ``doctor`` (PRD-017 FR-2).

    Example::

        report = messaging_hooks_status(workspace=".", tool_profile="coding")
        assert report.severity == "ok"
    """

    severity: Literal["ok", "error"]
    lines: list[str]
    complete: bool
    tool_profile: str


def _workspace_messaging_scripts_complete(scripts_dir: Path) -> bool:
    """Return True when every messaging ``.sh`` script is present and executable.

    WHY (PR #80): deploy sets execute bits; ``is_file()`` alone would report
    ``complete=True`` after ``chmod 0644``, even though Cursor cannot run hooks.
    """
    if not scripts_dir.is_dir():
        return False
    for filename in MESSAGING_HOOK_FILENAMES:
        if not filename.endswith(".sh"):
            continue
        script_path = scripts_dir / filename
        if not script_path.is_file():
            return False
        if not os.access(script_path, os.X_OK):
            return False
    return True


# WHY: Completeness must be event-aware — same script under the wrong Cursor
# event is not an equivalent security binding (matcher / failClosed matter too).
MessagingHookBinding = tuple[str, str, str | None, bool | None]


def _messaging_hook_bindings(manifest: HookManifest) -> frozenset[MessagingHookBinding]:
    """Return ``(event, command, matcher, failClosed)`` bindings from a manifest."""
    return frozenset(
        (event, entry.command, entry.matcher, entry.failClosed)
        for event, entries in manifest.hooks.items()
        for entry in entries
    )


def _expected_messaging_hook_bindings() -> frozenset[MessagingHookBinding]:
    """Return rewritten messaging bindings from packaged/source hooks.json.

    WHY: doctor completeness must match deploy — every rewritten source binding
    (event + command + matcher + failClosed), not a command-path set alone.
    ``sensitive-paths.sh`` is helper-only and is not a hooks.json entry.
    """
    try:
        source_dir = resolve_messaging_hook_source_dir()
        source_manifest = read_hook_manifest(source_dir / "hooks.json")
    except (ConfigError, OSError, ValueError, json.JSONDecodeError):
        return frozenset()
    rewritten = rewrite_messaging_manifest(source_manifest)
    return _messaging_hook_bindings(rewritten)


def _project_manifest_messaging_bindings(
    manifest: HookManifest,
) -> frozenset[MessagingHookBinding]:
    """Return messaging-prefixed bindings present in a project manifest."""
    prefix = f"{WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX}/"
    return frozenset(
        (event, entry.command, entry.matcher, entry.failClosed)
        for event, entries in manifest.hooks.items()
        for entry in entries
        if entry.command.startswith(prefix)
    )


def _project_manifest_has_messaging_hooks(manifest_path: Path) -> bool:
    """Return True when project hooks.json has all expected messaging bindings."""
    if not manifest_path.is_file():
        return False
    try:
        manifest = read_hook_manifest(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    expected = _expected_messaging_hook_bindings()
    if not expected:
        return False
    return expected.issubset(_project_manifest_messaging_bindings(manifest))


def _workspace_messaging_hooks_complete(workspace: Path) -> bool:
    """Return True when workspace deploy targets match a successful deploy."""
    scripts_dir = workspace_messaging_hooks_dir(workspace)
    # WHY: deploy copies only ``.sh`` scripts into the messaging dir; hooks.json
    # lives at the project manifest path — do not use ``_is_complete_hook_source_dir``.
    if not _workspace_messaging_scripts_complete(scripts_dir):
        return False
    return _project_manifest_has_messaging_hooks(
        workspace_project_hooks_manifest_path(workspace)
    )


def messaging_hooks_status(
    *,
    workspace: Path | str,
    tool_profile: str,
) -> MessagingHooksStatusReport:
    """Report whether workspace messaging hooks are complete for ``tool_profile``.

    Severity rules (PRD-017 FR-2):
    - ``messaging`` + missing/incomplete → ``error``
    - ``coding`` / ``full`` without hooks → greppable ``ok: … (not required …)``
    - ``coding`` / ``full`` with hooks already deployed → ``ok:`` deployed state

    Example::

        report = messaging_hooks_status(workspace=".", tool_profile="messaging")
        assert report.severity in {"ok", "error"}
    """
    workspace_path = Path(workspace).resolve()
    complete = _workspace_messaging_hooks_complete(workspace_path)
    scripts_dir = workspace_messaging_hooks_dir(workspace_path)

    if tool_profile == "messaging":
        if complete:
            return MessagingHooksStatusReport(
                severity="ok",
                lines=[f"ok: messaging hooks — deployed at {scripts_dir}"],
                complete=True,
                tool_profile=tool_profile,
            )
        return MessagingHooksStatusReport(
            severity="error",
            lines=[
                "error: messaging hooks — missing or incomplete "
                f"(expected scripts under {scripts_dir} and messaging "
                f"entries in {workspace_project_hooks_manifest_path(workspace_path)})"
            ],
            complete=False,
            tool_profile=tool_profile,
        )

    if complete:
        return MessagingHooksStatusReport(
            severity="ok",
            lines=[f"ok: messaging hooks — deployed at {scripts_dir}"],
            complete=True,
            tool_profile=tool_profile,
        )
    return MessagingHooksStatusReport(
        severity="ok",
        lines=[f"ok: messaging hooks — (not required for profile {tool_profile})"],
        complete=False,
        tool_profile=tool_profile,
    )
