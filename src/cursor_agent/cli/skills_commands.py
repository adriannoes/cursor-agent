"""Typer handlers for ``cursor-agent skills``.

WHY: operators need path/list/seed without the REPL; hooks are injectable so
unit tests stay hermetic under ``tmp_path`` (never real ``~/.cursor/skills/``).
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class SkillsCliPaths:
    """Resolved hermetic roots for skills CLI path/list commands.

    WHY: path/list never need the bundled pack — pack resolution stays on
    ``resolve_skills_seed_roots`` so a missing pack does not break BYO inspect.

    Example:
        >>> # paths = resolve_skills_cli_paths(load_config())
        >>> # paths.project_skills
    """

    cwd: Path
    home: Path

    @property
    def project_skills(self) -> Path:
        """Project ``.cursor/skills`` root derived from ``cwd``."""
        return project_skills_root(self.cwd)

    @property
    def user_skills(self) -> Path:
        """User ``.cursor/skills`` root derived from ``home``."""
        return user_skills_root(self.home)


@dataclass(frozen=True, slots=True)
class SkillsCliRuntime:
    """Config plus resolved paths for skills path/list commands.

    Example:
        >>> # runtime = load_skills_cli_runtime()
        >>> # runtime.paths.project_skills
    """

    config: CursorAgentConfig
    paths: SkillsCliPaths


def resolve_skills_cli_paths(config: CursorAgentConfig) -> SkillsCliPaths:
    """Compose cwd/home via the public ``resolve_skills_*`` hooks (no pack).

    Example:
        >>> # resolve_skills_cli_paths(load_config()).cwd.is_absolute()
    """
    return SkillsCliPaths(
        cwd=resolve_skills_cwd(config),
        home=resolve_skills_home(),
    )


def load_skills_cli_runtime() -> SkillsCliRuntime:
    """Load config and resolve skills CLI paths in one step.

    Example:
        >>> # load_skills_cli_runtime().paths.user_skills
    """
    config = load_config()
    return SkillsCliRuntime(config=config, paths=resolve_skills_cli_paths(config))


def resolve_skills_seed_roots() -> tuple[Path, Path]:
    """Return ``(home, pack_root)`` for seed via injectable hooks (no ``load_config``).

    Example:
        >>> # home, pack = resolve_skills_seed_roots()
    """
    return resolve_skills_home(), resolve_skills_pack_root()


def _format_seed_summary(summary: SeedSummary) -> str:
    """Render non-failure seed outcomes as human-readable stdout lines.

    WHY: soft ``Failed:`` lines go to stderr (see ``_echo_seed_failures``) so
    scripts that watch stderr do not miss them, matching cron warning sink.
    """
    lines: list[str] = []
    if summary.seeded:
        lines.append(f"Seeded: {', '.join(summary.seeded)}")
    if summary.skipped:
        lines.append(f"Skipped: {', '.join(summary.skipped)}")
    if summary.overwritten:
        lines.append(f"Overwritten: {', '.join(summary.overwritten)}")
    if not lines and not summary.failed:
        lines.append("No skills seeded, skipped, overwritten, or failed.")
    return "\n".join(lines)


def _echo_seed_failures(summary: SeedSummary) -> None:
    """Echo each soft seed failure on stderr for operators/scripts."""
    for failure in summary.failed:
        typer.echo(f"Failed: {failure.slug} ({failure.reason})", err=True)


@skills_app.command("path")
def skills_path() -> None:
    """Print project and user skills roots plus a short BYO paste hint.

    Example:
        cursor-agent skills path
    """
    try:
        runtime = load_skills_cli_runtime()
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    project_root = runtime.paths.project_skills.resolve()
    user_root = runtime.paths.user_skills.resolve()
    lines = [
        f"project: {project_root}",
        f"user: {user_root}",
        "",
        "Bring your own skills: paste an AgentSkills folder (with SKILL.md)",
        "into either root above. No marketplace — paste third-party skills only.",
        "Note: path always prints both roots; skills list respects setting_sources.",
    ]
    typer.echo("\n".join(lines))


@skills_app.command("list")
def skills_list() -> None:
    """List discovered skills from configured project and user roots.

    Example:
        cursor-agent skills list
    """
    try:
        runtime = load_skills_cli_runtime()
        # WHY: align with REPL /skills — formatter needs metadata only.
        discovery = skill_discovery_from_config(
            runtime.config,
            override_workspace=runtime.paths.cwd,
            override_user_skills=runtime.paths.user_skills,
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
        home, pack_root = resolve_skills_seed_roots()
        destination_root = user_skills_root(home)
        summary = seed_bundled_skills(
            pack_root=pack_root,
            destination_root=destination_root,
            force=force,
        )
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    summary_text = _format_seed_summary(summary)
    if summary_text:
        typer.echo(summary_text)
    _echo_seed_failures(summary)
    if summary.failed:
        raise typer.Exit(1)
