"""Interactive TTY setup wizard (PRD-013 Task 5.0 / FR-10; v1.1.0 Wave G3).

Collects API key (getpass), workspace, and optional fields with Proposal B
chrome, then returns values for ``apply_non_interactive``. Injectable
``_getpass_fn`` / ``_input_fn`` keep unit tests free of real terminal I/O
(ADR-027). Chrome is presentation only — still ≤7 interactive inputs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from cursor_agent.cli.setup_wizard_chrome import (
    GLYPH_TRUNK,
    format_prompt_leaf,
    format_radio_escape_hatch,
    format_radio_option,
    format_step,
    format_step_parts,
    format_summary,
    radio_option_label_width,
)
from cursor_agent.errors import ConfigError
from cursor_agent.first_party_models import (
    DEFAULT_AGENT_MODEL,
    WIZARD_MODEL_OTHER_ESCAPE_LABEL,
    resolve_wizard_model_choice,
    wizard_model_radio_options,
)
from cursor_agent.product_copy import (
    SETUP_CONFIRM,
    SETUP_HINT_API_KEY,
    SETUP_HINT_MEMORY_ROOT,
    SETUP_HINT_MODEL,
    SETUP_HINT_SESSIONS_DB,
    SETUP_HINT_TOOL_PROFILE,
    SETUP_HINT_WORKSPACE,
    SETUP_INTRO,
    SETUP_PROMPT_API_KEY,
    SETUP_PROMPT_MEMORY_ROOT,
    SETUP_PROMPT_MODEL,
    SETUP_PROMPT_SESSIONS_DB,
    SETUP_PROMPT_TOOL_PROFILE,
    SETUP_PROMPT_WORKSPACE,
    SETUP_SUMMARY_HEADER,
    SETUP_TITLE_API_KEY,
    SETUP_TITLE_INTRO,
    SETUP_TITLE_MEMORY_ROOT,
    SETUP_TITLE_MODEL,
    SETUP_TITLE_SESSIONS_DB,
    SETUP_TITLE_TOOL_PROFILE,
    SETUP_TITLE_WORKSPACE,
    SETUP_TOOL_PROFILE_OPTIONS,
)
from cursor_agent.tool_profiles import (
    DEFAULT_TOOL_PROFILE,
    resolve_wizard_tool_profile_choice,
)

# Monkeypatch targets for unit tests (ADR-027 injectable prompt style).
_getpass_fn: Callable[[str], str] = getpass
_input_fn: Callable[[str], str] = input

_SKIPPED_MEMORY_ROOT: str = "(skipped → ~/.cursor-agent)"
_SKIPPED_SESSIONS_DB: str = "(skipped → ~/.cursor-agent/sessions.db)"
_DEFAULT_TOOL_PROFILE_SUMMARY: str = f"(default: {DEFAULT_TOOL_PROFILE})"


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
    _echo_intro()
    api_key = _prompt_api_key()
    workspace = _prompt_workspace()
    memory_root = _prompt_optional_path(
        SETUP_TITLE_MEMORY_ROOT,
        SETUP_HINT_MEMORY_ROOT,
        SETUP_PROMPT_MEMORY_ROOT,
    )
    sessions_db = _prompt_optional_path(
        SETUP_TITLE_SESSIONS_DB,
        SETUP_HINT_SESSIONS_DB,
        SETUP_PROMPT_SESSIONS_DB,
    )
    model = _prompt_model()
    tool_profile = _prompt_tool_profile()
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


def _echo_intro() -> None:
    """Print Step 0 intro chrome (no interactive input)."""
    typer.echo(
        format_step(SETUP_TITLE_INTRO, SETUP_INTRO.splitlines(), ""),
    )


def _prompt_leaf(title: str, body_lines: Sequence[str], prompt: str) -> str:
    """Echo ◆/│ chrome and return the └ prompt string for input/getpass."""
    parts = format_step_parts(title, body_lines, prompt)
    if not parts.prompt_leaf:
        raise ConfigError(
            f"empty prompt_leaf for wizard step {title!r}: received {parts.prompt_leaf!r}, "
            "expected non-empty └ prompt string for input/getpass "
            "(use format_step for intro blocks without a prompt)",
        )
    typer.echo(parts.echo_block)
    return f"{parts.prompt_leaf} "


def _prompt_api_key() -> str:
    """Collect a non-empty API key via getpass (Step 1)."""
    leaf = _prompt_leaf(
        SETUP_TITLE_API_KEY,
        SETUP_HINT_API_KEY.splitlines(),
        SETUP_PROMPT_API_KEY,
    )
    api_key = _getpass_fn(leaf).strip()
    if not api_key:
        raise ConfigError(
            "empty API key from wizard prompt: received '', "
            "expected non-empty CURSOR_API_KEY value",
        )
    return api_key


def _prompt_workspace() -> Path:
    """Collect workspace path; empty Enter keeps ``Path.cwd()`` (Step 2)."""
    default_workspace = Path.cwd()
    leaf = _prompt_leaf(
        SETUP_TITLE_WORKSPACE,
        SETUP_HINT_WORKSPACE.splitlines(),
        SETUP_PROMPT_WORKSPACE.format(default=default_workspace),
    )
    workspace_raw = _input_fn(leaf).strip()
    workspace = Path(workspace_raw).expanduser() if workspace_raw else default_workspace
    if not workspace.is_dir():
        raise ConfigError(
            f"invalid workspace from wizard: received {str(workspace)!r}, "
            "expected an existing directory",
        )
    return workspace


def _prompt_optional_path(title: str, hint: str, prompt: str) -> Path | None:
    """Prompt for an optional path; empty Enter skips."""
    leaf = _prompt_leaf(title, hint.splitlines(), prompt)
    raw = _input_fn(leaf).strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _format_numbered_radio_rows(
    options: Sequence[tuple[int, str, str, bool]],
) -> list[str]:
    """Render numbered radio rows with chrome-owned glyphs and derived widths."""
    label_width = radio_option_label_width(tuple(label for _, label, _, _ in options))
    return [
        format_radio_option(
            index,
            label,
            detail,
            selected=selected,
            label_width=label_width,
        )
        for index, label, detail, selected in options
    ]


def _prompt_model() -> str | None:
    """Proposal B model step; resolve via soft catalog (Step 5)."""
    option_lines = [
        *_format_numbered_radio_rows(wizard_model_radio_options()),
        format_radio_escape_hatch(WIZARD_MODEL_OTHER_ESCAPE_LABEL),
    ]
    body: list[str] = [
        *SETUP_HINT_MODEL.splitlines(),
        "",
        *option_lines,
    ]
    leaf = _prompt_leaf(SETUP_TITLE_MODEL, body, SETUP_PROMPT_MODEL)
    return resolve_wizard_model_choice(_input_fn(leaf))


def _prompt_tool_profile() -> str | None:
    """Numbered tool-profile step; resolve before confirm (Step 6)."""
    option_lines = _format_numbered_radio_rows(SETUP_TOOL_PROFILE_OPTIONS)
    body: list[str] = [
        *SETUP_HINT_TOOL_PROFILE.splitlines(),
        "",
        *option_lines,
    ]
    leaf = _prompt_leaf(SETUP_TITLE_TOOL_PROFILE, body, SETUP_PROMPT_TOOL_PROFILE)
    return resolve_wizard_tool_profile_choice(_input_fn(leaf))


def print_wizard_summary(
    *,
    workspace: Path,
    memory_root: Path | None,
    sessions_db: Path | None,
    model: str | None,
    tool_profile: str | None,
) -> None:
    """Print redacted ◇ summary (API key always shown as ``***``)."""
    typer.echo(
        format_summary(
            [
                ("API key", "***"),
                ("workspace", str(workspace)),
                ("memory_root", _display_memory_root(memory_root)),
                ("sessions_db", _display_sessions_db(sessions_db)),
                ("model", _display_model(model)),
                ("tool_profile", _display_tool_profile(tool_profile)),
            ],
            title=SETUP_SUMMARY_HEADER,
        )
    )


def _display_memory_root(value: Path | None) -> str:
    """Render memory_root for the summary, including skipped default path."""
    if value is None:
        return _SKIPPED_MEMORY_ROOT
    return str(value)


def _display_sessions_db(value: Path | None) -> str:
    """Render sessions_db for the summary, including skipped default path."""
    if value is None:
        return _SKIPPED_SESSIONS_DB
    return str(value)


def _display_model(value: str | None) -> str:
    """Render model for the summary; omitted → default agent model."""
    if value is None:
        return f"(default: {DEFAULT_AGENT_MODEL})"
    return value


def _display_tool_profile(value: str | None) -> str:
    """Render tool_profile for the summary; omitted → catalog default."""
    if value is None:
        return _DEFAULT_TOOL_PROFILE_SUMMARY
    return value


def confirm_wizard_write() -> bool:
    """Return True when the operator confirms with y/yes (default N)."""
    # Blank │ trunk before └ matches approved Step 7 breathing room.
    typer.echo(GLYPH_TRUNK)
    prompt = f"{format_prompt_leaf(SETUP_CONFIRM)} "
    answer = _input_fn(prompt).strip().lower()
    return answer in {"y", "yes"}
