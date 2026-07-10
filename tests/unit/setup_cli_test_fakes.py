"""Shared helpers for ``cursor-agent setup`` CLI unit tests (apply / wizard)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

PLACEHOLDER_API_KEY = "sk-test-placeholder"
SETUP_EXAMPLE = "cursor-agent setup"


def patch_non_interactive(monkeypatch: MonkeyPatch, *, is_ci: bool = False) -> None:
    """Force non-interactive apply guards for CliRunner (non-TTY; optional CI).

    Example:
        >>> patch_non_interactive(monkeypatch)
    """
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: False,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: is_ci,
    )


def patch_tty_not_ci(monkeypatch: MonkeyPatch) -> None:
    """Simulate interactive TTY with CI disabled (wizard eligibility guard).

    Example:
        >>> patch_tty_not_ci(monkeypatch)
    """
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: False,
    )


def apply_args(
    *,
    workspace: Path,
    config_path: Path,
    env_file: Path,
    api_key: str = PLACEHOLDER_API_KEY,
    extra: list[str] | None = None,
) -> list[str]:
    """Build a headless ``setup`` invocation with injectable paths.

    Example:
        >>> apply_args(workspace=ws, config_path=cfg, env_file=env)
        ['setup', '--api-key', '...', ...]
    """
    args = [
        "setup",
        "--api-key",
        api_key,
        "--workspace",
        str(workspace),
        "--config-path",
        str(config_path),
        "--env-file",
        str(env_file),
        "--yes",
    ]
    if extra:
        args.extend(extra)
    return args
