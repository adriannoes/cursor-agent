"""Typer handlers for ``cursor-agent skills`` (PRD-016 FR-3 / FR-7).

WHY: operators need path/list/seed without the REPL; hooks are injectable so
unit tests stay hermetic under ``tmp_path`` (never real ``~/.cursor/skills/``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.cli.rich_display import format_skills_list_output
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.errors import CursorAgentError
from cursor_agent.skills.discovery import skill_discovery_from_config
from cursor_agent.skills.pack_paths import (
    bundled_skills_pack_root,
    project_skills_root,
    user_skills_root,
)
from cursor_agent.skills.seed import SeedSummary, seed_bundled_skills

skills_app = typer.Typer(
    help="Inspect and seed product skills (path, list, seed)",
    # WHY: Click's no_args_is_help exits 2; tests require bare ``skills`` → help, exit 0.
    no_args_is_help=False,
)


@skills_app.callback(invoke_without_command=True)
def skills_entry(ctx: typer.Context) -> None:
    """Inspect and seed product skills (path, list, seed)."""
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(ctx.get_help())


def _exit_on_cursor_agent_error(exc: CursorAgentError) -> NoReturn:
    """Print an actionable CLI error and exit with the mapped code."""
    typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for_error(exc)) from exc


def resolve_skills_cwd(config: CursorAgentConfig) -> Path:
    """Return the workspace cwd used for project skills roots.

    Tests monkeypatch this hook to inject ``tmp_path`` workspaces.

    Example:
        >>> from cursor_agent.config.loader import load_config
        >>> resolve_skills_cwd(load_config()).is_absolute()
        True
    """
    return Path(config.runtime.local.cwd).resolve()


def resolve_skills_home() -> Path:
    """Return the home directory used for user skills roots.

    Tests monkeypatch this hook to inject ``tmp_path`` homes.

    Example:
        >>> resolve_skills_home().is_absolute()
        True
    """
    return Path.home()


def resolve_skills_pack_root() -> Path:
    """Return the bundled product skills pack root.

    Tests monkeypatch this hook to inject a mini pack under ``tmp_path``.

    Example:
        >>> resolve_skills_pack_root().is_dir()
        True
    """
    return bundled_skills_pack_root()


def _format_seed_summary(summary: SeedSummary) -> str:
    """Render seed outcomes as human-readable stdout lines."""
    lines: list[str] = []
    if summary.seeded:
        lines.append(f"Seeded: {', '.join(summary.seeded)}")
    if summary.skipped:
        lines.append(f"Skipped: {', '.join(summary.skipped)}")
    if summary.overwritten:
        lines.append(f"Overwritten: {', '.join(summary.overwritten)}")
    if summary.failed:
        for failure in summary.failed:
            lines.append(f"Failed: {failure.slug} ({failure.reason})")
    if not lines:
        lines.append("No skills seeded, skipped, overwritten, or failed.")
    return "\n".join(lines)


@skills_app.command("path")
def skills_path() -> None:
    """Print project and user skills roots plus a short BYO paste hint.

    Example:
        cursor-agent skills path
    """
    try:
        config = load_config()
        cwd = resolve_skills_cwd(config)
        home = resolve_skills_home()
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    project_root = project_skills_root(cwd).resolve()
    user_root = user_skills_root(home).resolve()
    lines = [
        f"project: {project_root}",
        f"user: {user_root}",
        "",
        "Bring your own skills: paste an AgentSkills folder (with SKILL.md)",
        "into either root above. No marketplace — paste third-party skills only.",
    ]
    typer.echo("\n".join(lines))


@skills_app.command("list")
def skills_list() -> None:
    """List discovered skills from configured project and user roots.

    Example:
        cursor-agent skills list
    """
    try:
        config = load_config()
        cwd = resolve_skills_cwd(config)
        home = resolve_skills_home()
        # WHY: align with REPL /skills — formatter needs metadata only (review N1).
        discovery = skill_discovery_from_config(
            config,
            override_workspace=cwd,
            override_user_skills=user_skills_root(home),
            include_content=False,
        )
        output = format_skills_list_output(discovery.list_skills())
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    typer.echo(output)


@skills_app.command("seed")
def skills_seed(
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite existing skill directories under the user skills root.",
        ),
    ] = False,
) -> None:
    """Seed bundled product skills into the user skills root (flat layout).

    Example:
        cursor-agent skills seed
        cursor-agent skills seed --force
    """
    try:
        pack_root = resolve_skills_pack_root()
        destination_root = user_skills_root(resolve_skills_home())
        summary = seed_bundled_skills(
            pack_root=pack_root,
            destination_root=destination_root,
            force=force,
        )
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    typer.echo(_format_seed_summary(summary))
    if summary.failed:
        raise typer.Exit(1)
