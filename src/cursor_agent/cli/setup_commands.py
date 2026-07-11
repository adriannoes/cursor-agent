"""Typer ``setup`` commands: apply / check / show (PRD-013, ADR-028).

Default ``cursor-agent setup`` runs apply via
``@setup_app.callback(invoke_without_command=True)``. On TTY (not CI, no value
flags, no ``--yes``) the interactive wizard runs (FR-10); otherwise flags are
required for non-interactive apply.

Apply option metadata lives in shared ``Annotated`` aliases so the default
callback and ``setup apply`` cannot drift when flags change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cursor_agent.cli import setup_runtime
from cursor_agent.cli.setup_runtime import (
    exit_on_cursor_agent_error,
    resolve_config_path,
    resolve_env_file,
    run_setup_apply,
    run_setup_check,
    run_setup_show,
)
from cursor_agent.errors import CursorAgentError

# Monkeypatch targets for unit tests (FR-6 / ADR-027 injectable TTY/CI).
_stdout_is_tty = setup_runtime.stdout_is_tty
_is_ci_environment = setup_runtime.is_ci_environment

# Shared apply Option definitions (single source for callback + ``apply`` command).
ApplyApiKeyOpt = Annotated[
    str | None,
    typer.Option("--api-key", help="CURSOR_API_KEY value (written to .env only)."),
]
ApplyWorkspaceOpt = Annotated[
    Path | None,
    typer.Option(
        "--workspace",
        help="Workspace directory written to runtime.local.cwd.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]
ApplyMemoryRootOpt = Annotated[
    Path | None,
    typer.Option(
        "--memory-root",
        help="Optional memory_root directory (YAML).",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]
ApplySessionsDbOpt = Annotated[
    Path | None,
    typer.Option(
        "--sessions-db",
        help="Optional CURSOR_AGENT_SESSIONS_DB path (.env).",
        resolve_path=True,
    ),
]
ApplyModelOpt = Annotated[
    str | None,
    typer.Option("--model", help="Optional model id (YAML)."),
]
ApplyToolProfileOpt = Annotated[
    str | None,
    typer.Option(
        "--tool-profile",
        help="Tool profile: coding, messaging, or full (YAML).",
    ),
]
ApplyConfigPathOpt = Annotated[
    Path | None,
    typer.Option(
        "--config-path",
        help="Override config.yaml path (default: ~/.cursor-agent/config.yaml).",
        dir_okay=False,
        file_okay=True,
        resolve_path=True,
    ),
]
ApplyEnvFileOpt = Annotated[
    Path | None,
    typer.Option(
        "--env-file",
        help="Override .env path (default: ./{cwd}/.env).",
        dir_okay=False,
        file_okay=True,
        resolve_path=True,
    ),
]
ApplyDryRunOpt = Annotated[
    bool,
    typer.Option("--dry-run", help="Print plan without writing files."),
]
ApplyYesOpt = Annotated[
    bool,
    typer.Option(
        "--yes",
        "-y",
        help="Skip the interactive wizard (non-interactive apply with flags).",
    ),
]
ApplyForceOpt = Annotated[
    bool,
    typer.Option("--force", help="Overwrite differing env values after backup."),
]

setup_app = typer.Typer(
    help="Configure local cursor-agent settings (API key, workspace, and related paths).",
    epilog=(
        "Examples:\n"
        "  cursor-agent setup --api-key <CURSOR_API_KEY> --workspace /path/to/project --yes\n"
        "  cursor-agent setup check\n"
        "  cursor-agent setup show\n"
        "\n"
        "--yes skips the interactive wizard when running with value flags."
    ),
    no_args_is_help=False,
)


def _apply_from_flags(
    *,
    api_key: str | None,
    workspace: Path | None,
    memory_root: Path | None,
    sessions_db: Path | None,
    model: str | None,
    tool_profile: str | None,
    config_path: Path | None,
    env_file: Path | None,
    dry_run: bool,
    yes: bool,
    force: bool,
) -> None:
    """Dispatch apply using module-level TTY/CI helpers (monkeypatch-friendly)."""
    run_setup_apply(
        api_key=api_key,
        workspace=workspace,
        memory_root=memory_root,
        sessions_db=sessions_db,
        model=model,
        tool_profile=tool_profile,
        config_path=config_path,
        env_file=env_file,
        dry_run=dry_run,
        yes=yes,
        force=force,
        is_tty=_stdout_is_tty(),
        is_ci=_is_ci_environment(),
    )


@setup_app.callback(invoke_without_command=True)
def setup_entry(
    ctx: typer.Context,
    api_key: ApplyApiKeyOpt = None,
    workspace: ApplyWorkspaceOpt = None,
    memory_root: ApplyMemoryRootOpt = None,
    sessions_db: ApplySessionsDbOpt = None,
    model: ApplyModelOpt = None,
    tool_profile: ApplyToolProfileOpt = None,
    config_path: ApplyConfigPathOpt = None,
    env_file: ApplyEnvFileOpt = None,
    dry_run: ApplyDryRunOpt = False,
    yes: ApplyYesOpt = False,
    force: ApplyForceOpt = False,
) -> None:
    """Configure local cursor-agent settings (default: apply).

    Examples:
      cursor-agent setup --api-key <CURSOR_API_KEY> --workspace /path/to/project --yes
      cursor-agent setup apply --api-key <CURSOR_API_KEY> --workspace . --yes
      cursor-agent setup check
      cursor-agent setup show
    """
    if ctx.invoked_subcommand is not None:
        return
    _apply_from_flags(
        api_key=api_key,
        workspace=workspace,
        memory_root=memory_root,
        sessions_db=sessions_db,
        model=model,
        tool_profile=tool_profile,
        config_path=config_path,
        env_file=env_file,
        dry_run=dry_run,
        yes=yes,
        force=force,
    )


@setup_app.command("apply")
def setup_apply_command(
    api_key: ApplyApiKeyOpt = None,
    workspace: ApplyWorkspaceOpt = None,
    memory_root: ApplyMemoryRootOpt = None,
    sessions_db: ApplySessionsDbOpt = None,
    model: ApplyModelOpt = None,
    tool_profile: ApplyToolProfileOpt = None,
    config_path: ApplyConfigPathOpt = None,
    env_file: ApplyEnvFileOpt = None,
    dry_run: ApplyDryRunOpt = False,
    yes: ApplyYesOpt = False,
    force: ApplyForceOpt = False,
) -> None:
    """Persist configuration (same as ``cursor-agent setup``).

    Examples:
      cursor-agent setup apply --api-key <CURSOR_API_KEY> --workspace /path --yes
      cursor-agent setup apply --dry-run --api-key <CURSOR_API_KEY> --workspace .
    """
    _apply_from_flags(
        api_key=api_key,
        workspace=workspace,
        memory_root=memory_root,
        sessions_db=sessions_db,
        model=model,
        tool_profile=tool_profile,
        config_path=config_path,
        env_file=env_file,
        dry_run=dry_run,
        yes=yes,
        force=force,
    )


@setup_app.command("check")
def setup_check_command(
    config_path: ApplyConfigPathOpt = None,
    env_file: ApplyEnvFileOpt = None,
) -> None:
    """Validate configuration read-only (offline; no live API probe).

    Examples:
      cursor-agent setup check
      cursor-agent setup check --config-path ~/.cursor-agent/config.yaml
    """
    try:
        run_setup_check(
            config_path=resolve_config_path(config_path),
            env_file=resolve_env_file(env_file),
        )
    except CursorAgentError as exc:
        exit_on_cursor_agent_error(exc)


@setup_app.command("show")
def setup_show_command(
    config_path: ApplyConfigPathOpt = None,
    env_file: ApplyEnvFileOpt = None,
) -> None:
    """Print effective configuration with secrets redacted and source labels.

    Examples:
      cursor-agent setup show
      cursor-agent setup show --env-file ./.env
    """
    try:
        run_setup_show(
            config_path=resolve_config_path(config_path),
            env_file=resolve_env_file(env_file),
        )
    except CursorAgentError as exc:
        exit_on_cursor_agent_error(exc)
