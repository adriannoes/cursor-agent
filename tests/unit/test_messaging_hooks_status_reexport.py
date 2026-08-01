"""Compatibility re-export of status API from messaging_hooks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_messaging_hooks_reexports_status_api() -> None:
    """Old import path keeps MessagingHooksStatusReport / messaging_hooks_status."""
    from cursor_agent import messaging_hooks
    from cursor_agent.messaging_hooks_status import (
        MessagingHooksStatusReport as CanonicalReport,
        messaging_hooks_status as canonical_status,
    )

    assert messaging_hooks.MessagingHooksStatusReport is CanonicalReport
    assert messaging_hooks.messaging_hooks_status is canonical_status


def test_messaging_hooks_status_imports_before_messaging_hooks() -> None:
    """Canonical status module must load without messaging_hooks pre-imported.

    WHY (PR #80 review): a module-level re-export cycle made
    ``import cursor_agent.messaging_hooks_status`` fail unless ``messaging_hooks``
    was already fully loaded. Subprocess keeps ``sys.modules`` hermetic.
    """
    src_root = Path(__file__).resolve().parents[2] / "src"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import cursor_agent.messaging_hooks_status as status; "
                "assert status.MessagingHooksStatusReport is not None; "
                "assert callable(status.messaging_hooks_status)"
            ),
        ],
        cwd=str(src_root.parent),
        env={
            **os.environ,
            "PYTHONPATH": str(src_root),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "messaging_hooks_status must import alone: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
