"""Interactive TTY setup wizard (PRD-013 Task 5.0 / FR-10).

Collects API key (getpass), workspace, and optional fields, then returns
values for ``apply_non_interactive``. Injectable ``_getpass_fn`` /
``_input_fn`` keep unit tests free of real terminal I/O (ADR-027).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from cursor_agent.errors import ConfigError
from cursor_agent.product_copy import (
    SETUP_CONFIRM,
    SETUP_INTRO,
    SETUP_PROMPT_API_KEY,
    SETUP_PROMPT_MEMORY_ROOT,
    SETUP_PROMPT_MODEL,
    SETUP_PROMPT_SESSIONS_DB,
    SETUP_PROMPT_TOOL_PROFILE,
    SETUP_PROMPT_WORKSPACE,
    SETUP_SUMMARY_HEADER,
)

# Monkeypatch targets for unit tests (ADR-027 injectable prompt style).
_getpass_fn: Callable[[str], str] = getpass
_input_fn: Callable[[str], str] = input


@dataclass(frozen=True, slots=True)
class WizardCollectedValues:
    """Values collected by the interactive setup wizard before confirm."""

    api_key: str
    workspace: Path
    memory_root: Path | None
    sessions_db: Path | None
    model: str | None
    tool_profile: str | None


def run_interactive_wizard() -> WizardCollectedValues:
    """Run the short FR-10 wizard (≤7 interactive steps) and return collected values.

    Example:
        >>> # values = run_interactive_wizard()  # prompts on a real TTY
    """
    typer.echo(SETUP_INTRO)

    api_key = _getpass_fn(SETUP_PROMPT_API_KEY).strip()
    if not api_key:
        raise ConfigError(
            "empty API key from wizard prompt: received '', "
            "expected non-empty CURSOR_API_KEY value",
        )

    default_workspace = Path.cwd()
    workspace_prompt = SETUP_PROMPT_WORKSPACE.format(default=default_workspace)
    workspace_raw = _input_fn(workspace_prompt).strip()
    workspace = Path(workspace_raw).expanduser() if workspace_raw else default_workspace
    if not workspace.is_dir():
        raise ConfigError(
            f"invalid workspace from wizard: received {str(workspace)!r}, "
            "expected an existing directory",
        )

    memory_root = _optional_path_from_prompt(SETUP_PROMPT_MEMORY_ROOT)
    sessions_db = _optional_path_from_prompt(SETUP_PROMPT_SESSIONS_DB)
    model = _optional_str_from_prompt(SETUP_PROMPT_MODEL)
    tool_profile = _optional_str_from_prompt(SETUP_PROMPT_TOOL_PROFILE)

    print_wizard_summary(
        workspace=workspace,
        memory_root=memory_root,
        sessions_db=sessions_db,
        model=model,
        tool_profile=tool_profile,
    )
    if not confirm_wizard_write():
        typer.echo("Setup cancelled.", err=True)
        raise typer.Exit(1)

    return WizardCollectedValues(
        api_key=api_key,
        workspace=workspace,
        memory_root=memory_root,
        sessions_db=sessions_db,
        model=model,
        tool_profile=tool_profile,
    )


def _optional_path_from_prompt(prompt: str) -> Path | None:
    """Prompt for an optional path; empty Enter skips."""
    raw = _input_fn(prompt).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _optional_str_from_prompt(prompt: str) -> str | None:
    """Prompt for an optional string; empty Enter skips."""
    raw = _input_fn(prompt).strip()
    return raw if raw else None


def print_wizard_summary(
    *,
    workspace: Path,
    memory_root: Path | None,
    sessions_db: Path | None,
    model: str | None,
    tool_profile: str | None,
) -> None:
    """Print redacted wizard summary (API key always shown as ``***``)."""
    typer.echo(SETUP_SUMMARY_HEADER)
    typer.echo("  API key: ***")
    typer.echo(f"  workspace: {workspace}")
    typer.echo(f"  memory_root: {_display_optional(memory_root)}")
    typer.echo(f"  sessions_db: {_display_optional(sessions_db)}")
    typer.echo(f"  model: {_display_optional(model)}")
    typer.echo(f"  tool_profile: {_display_optional(tool_profile)}")


def _display_optional(value: Path | str | None) -> str:
    """Render optional wizard fields for the summary."""
    if value is None:
        return "(skipped)"
    return str(value)


def confirm_wizard_write() -> bool:
    """Return True when the operator confirms with y/yes (default N)."""
    answer = _input_fn(SETUP_CONFIRM).strip().lower()
    return answer in {"y", "yes"}
