"""Shared helpers for messaging hook unit tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MESSAGING_HOOKS_SOURCE = REPO_ROOT / "hooks" / "messaging"

REQUIRED_HOOK_FILES: tuple[str, ...] = (
    "hooks.json",
    "pre-tool-deny-write.sh",
    "shell-gate.sh",
    "mcp-deny.sh",
    "read-sensitive-deny.sh",
    "sensitive-paths.sh",
)

REQUIRED_HOOK_SCRIPTS: tuple[str, ...] = tuple(
    filename for filename in REQUIRED_HOOK_FILES if filename.endswith(".sh")
)

REQUIRED_HOOK_EVENTS: tuple[str, ...] = (
    "preToolUse",
    "beforeShellExecution",
    "beforeMCPExecution",
    "beforeReadFile",
)

EVENT_SCRIPT_MAP: dict[str, str] = {
    "preToolUse": "pre-tool-deny-write.sh",
    "beforeShellExecution": "shell-gate.sh",
    "beforeMCPExecution": "mcp-deny.sh",
    "beforeReadFile": "read-sensitive-deny.sh",
}


def run_hook_script(
    script_path: Path,
    payload: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    """Execute a hook script with JSON stdin and capture stdout/stderr."""
    return subprocess.run(
        [str(script_path)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )


def hook_permission(result: subprocess.CompletedProcess[str]) -> str:
    """Parse permission from hook stdout JSON."""
    assert result.stdout.strip(), (
        f"hook produced empty stdout: stderr={result.stderr!r}, "
        f"returncode={result.returncode}"
    )
    output = json.loads(result.stdout)
    return str(output["permission"])


def hook_script(name: str) -> Path:
    """Return path to a messaging hook script under the repo source tree."""
    return MESSAGING_HOOKS_SOURCE / name
