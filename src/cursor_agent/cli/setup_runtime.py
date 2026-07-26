"""Setup apply / check / show runtime helpers (PRD-013, ADR-028).

Non-interactive apply shares ``apply_non_interactive`` with the interactive
TTY wizard in ``setup_wizard`` (Task 5.0 / FR-10).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final, NoReturn

import typer
from dotenv import load_dotenv

from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.cli.setup_wizard import run_interactive_wizard
from cursor_agent.cli.setup_wizard_chrome import format_success
from cursor_agent.cli.startup import (
    load_cwd_dotenv,
    snapshot_process_environ_before_dotenv,
)
from cursor_agent.config.effective import (
    REDACTION_TOKEN,
    build_effective_config,
    render_effective_config_redacted,
)
from cursor_agent.config.loader import (
    DEFAULT_CONFIG_PATH,
    CursorAgentConfig,
    load_config,
)
from cursor_agent.config.writer import (
    WriteConfigResult,
    check_env_merge_allowed,
    merge_env_file,
    write_config_yaml,
)
from cursor_agent.errors import ConfigError, CursorAgentError
from cursor_agent.product_copy import SETUP_ALREADY_CONFIGURED, SETUP_SUCCESS

_CI_DISABLED_VALUES: Final[frozenset[str]] = frozenset({"", "0", "false", "no", "off"})
_DEFAULT_ENV_FILENAME: Final[str] = ".env"
_DEFAULT_SESSIONS_DB: Final[Path] = Path.home() / ".cursor-agent" / "sessions.db"

NON_INTERACTIVE_EXAMPLE: Final[str] = (
    "cursor-agent setup --api-key <CURSOR_API_KEY> --workspace <path> --yes"
)


def stdout_is_tty() -> bool:
    """Return whether stdout is an interactive terminal."""
    return sys.stdout.isatty()


def is_ci_environment() -> bool:
    """Return whether CI suppression is active via a truthy ``CI`` env value."""
    raw = os.environ.get("CI")
    if raw is None:
        return False
    return raw.strip().lower() not in _CI_DISABLED_VALUES


def exit_on_cursor_agent_error(exc: CursorAgentError) -> NoReturn:
    """Echo error text and exit with the mapped CLI exit code."""
    typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for_error(exc)) from exc


def default_env_file() -> Path:
    """Return the default CWD ``.env`` path for setup writes."""
    return Path.cwd() / _DEFAULT_ENV_FILENAME


def resolve_config_path(config_path: Path | None) -> Path:
    """Resolve YAML config path; default ``~/.cursor-agent/config.yaml``."""
    return config_path if config_path is not None else DEFAULT_CONFIG_PATH


def resolve_env_file(env_file: Path | None) -> Path:
    """Resolve env file path; default ``{cwd}/.env``."""
    return env_file if env_file is not None else default_env_file()


def has_value_bearing_flags(
    *,
    api_key: str | None,
    workspace: Path | None,
    memory_root: Path | None,
    sessions_db: Path | None,
    model: str | None,
    tool_profile: str | None,
) -> bool:
    """Return True when any FR-7 value flag was provided."""
    return any(
        value is not None
        for value in (api_key, workspace, memory_root, sessions_db, model, tool_profile)
    )


def require_non_interactive_inputs(
    *,
    api_key: str | None,
    workspace: Path | None,
) -> None:
    """Raise ``ConfigError`` when required headless flags are missing."""
    missing: list[str] = []
    if api_key is None or not api_key.strip():
        missing.append("--api-key")
    if workspace is None:
        missing.append("--workspace")
    if not missing:
        return
    raise ConfigError(
        f"missing required setup flags for non-interactive apply: "
        f"received missing {missing!r}, expected both --api-key and --workspace. "
        f"Example: {NON_INTERACTIVE_EXAMPLE}",
    )


def load_setup_dotenv(env_file: Path) -> None:
    """Load the setup env file into ``os.environ`` without overriding exports.

    When the path is the CWD default, reuse ``load_cwd_dotenv`` (ADR-028).
    Snapshots process environ before the first dotenv merge for ``setup show``.
    """
    snapshot_process_environ_before_dotenv()
    if env_file.resolve() == default_env_file().resolve():
        load_cwd_dotenv()
        return
    if env_file.is_file():
        load_dotenv(env_file, override=False)


def run_setup_apply(
    *,
    api_key: str | None = None,
    workspace: Path | None = None,
    memory_root: Path | None = None,
    sessions_db: Path | None = None,
    model: str | None = None,
    tool_profile: str | None = None,
    config_path: Path | None = None,
    env_file: Path | None = None,
    dry_run: bool = False,
    yes: bool = False,
    force: bool = False,
    is_tty: bool | None = None,
    is_ci: bool | None = None,
) -> None:
    """Persist setup via flags or the interactive TTY wizard (FR-10).

    Example:
        >>> # run_setup_apply(api_key="sk-test", workspace=Path("."), yes=True)
    """
    tty = stdout_is_tty() if is_tty is None else is_tty
    ci = is_ci_environment() if is_ci is None else is_ci
    value_flags = has_value_bearing_flags(
        api_key=api_key,
        workspace=workspace,
        memory_root=memory_root,
        sessions_db=sessions_db,
        model=model,
        tool_profile=tool_profile,
    )
    resolved_config = resolve_config_path(config_path)
    resolved_env = resolve_env_file(env_file)

    # FR-10: TTY + not CI + no value flags + no --yes → interactive wizard.
    if tty and not ci and not value_flags and not yes and not dry_run:
        try:
            collected = run_interactive_wizard()
            apply_non_interactive(
                api_key=collected.api_key,
                workspace=collected.workspace,
                memory_root=collected.memory_root,
                sessions_db=collected.sessions_db,
                model=collected.model,
                tool_profile=collected.tool_profile,
                config_path=resolved_config,
                env_file=resolved_env,
                dry_run=False,
                force=force,
                wizard_success_chrome=True,
            )
        except CursorAgentError as exc:
            exit_on_cursor_agent_error(exc)
        return

    try:
        require_non_interactive_inputs(api_key=api_key, workspace=workspace)
        assert api_key is not None and workspace is not None
        apply_non_interactive(
            api_key=api_key,
            workspace=workspace,
            memory_root=memory_root,
            sessions_db=sessions_db,
            model=model,
            tool_profile=tool_profile,
            config_path=resolved_config,
            env_file=resolved_env,
            dry_run=dry_run,
            force=force,
        )
    except CursorAgentError as exc:
        exit_on_cursor_agent_error(exc)


def apply_non_interactive(
    *,
    api_key: str,
    workspace: Path,
    memory_root: Path | None,
    sessions_db: Path | None,
    model: str | None,
    tool_profile: str | None,
    config_path: Path,
    env_file: Path,
    dry_run: bool,
    force: bool,
    wizard_success_chrome: bool = False,
) -> None:
    """Write YAML + env (or print dry-run plan) and post-validate on success.

    Preflights env refuse-without-force before any YAML/memory mutation so a
    refused overwrite cannot leave orphan ``config.yaml`` or memory placeholders.
    ``wizard_success_chrome`` renders Step 8 ``format_success`` for the
    interactive wizard only; non-interactive apply stays terse (D14 / rec. 12).
    """
    yaml_updates = build_yaml_updates(
        workspace=workspace,
        memory_root=memory_root,
        model=model,
        tool_profile=tool_profile,
    )
    env_updates = build_env_updates(api_key=api_key, sessions_db=sessions_db)

    if dry_run:
        print_dry_run_plan(
            config_path=config_path,
            env_file=env_file,
            yaml_updates=yaml_updates,
            env_updates=env_updates,
        )
        return

    # Preflight: refuse check (no writes) before YAML / memory touch.
    check_env_merge_allowed(env_file, env_updates, force=force)
    yaml_result = write_config_yaml(config_path, yaml_updates)
    env_result = merge_env_file(env_file, env_updates, force=force)
    print_apply_outcome(
        yaml_result=yaml_result,
        env_result=env_result,
        config_path=config_path,
        env_file=env_file,
        wizard_success_chrome=wizard_success_chrome,
    )
    load_setup_dotenv(env_file)
    load_config(config_path=config_path)


def build_yaml_updates(
    *,
    workspace: Path,
    memory_root: Path | None,
    model: str | None,
    tool_profile: str | None,
) -> dict[str, object]:
    """Build writer YAML updates from apply flags."""
    updates: dict[str, object] = {
        "runtime": {"local": {"cwd": str(workspace)}},
    }
    if memory_root is not None:
        updates["memory_root"] = str(memory_root)
    if model is not None:
        updates["model"] = model
    if tool_profile is not None:
        updates["tool_profile"] = tool_profile
    return updates


def build_env_updates(
    *,
    api_key: str,
    sessions_db: Path | None,
) -> dict[str, str]:
    """Build allowlisted env updates from apply flags."""
    updates: dict[str, str] = {"CURSOR_API_KEY": api_key}
    if sessions_db is not None:
        updates["CURSOR_AGENT_SESSIONS_DB"] = str(sessions_db)
    return updates


def print_dry_run_plan(
    *,
    config_path: Path,
    env_file: Path,
    yaml_updates: dict[str, object],
    env_updates: dict[str, str],
) -> None:
    """Print planned paths and key names with secrets redacted (FR-8)."""
    typer.echo("Dry run — no files will be written.")
    typer.echo(f"  yaml: {config_path}")
    typer.echo(f"  env:  {env_file}")
    typer.echo(f"  yaml keys: {sorted(yaml_updates)}")
    for key in sorted(env_updates):
        display = REDACTION_TOKEN if key == "CURSOR_API_KEY" else env_updates[key]
        typer.echo(f"  env {key}={display}")


def print_apply_outcome(
    *,
    yaml_result: WriteConfigResult,
    env_result: WriteConfigResult,
    config_path: Path,
    env_file: Path,
    wizard_success_chrome: bool = False,
) -> None:
    """Print success or already-configured messaging after writes."""
    if not yaml_result.changed and not env_result.changed:
        typer.echo(SETUP_ALREADY_CONFIGURED)
        return
    # SETUP_SUCCESS may include a Next: line; print paths between header and Next
    # on the terse non-interactive path. Interactive wizard uses format_success.
    header, separator, next_hint = SETUP_SUCCESS.partition("\n")
    if wizard_success_chrome:
        typer.echo(
            format_success(
                header,
                next_hint if separator else "",
                detail_lines=_wizard_success_detail_lines(
                    env_file=env_file,
                    config_path=config_path,
                    backup_path=env_result.backup_path,
                ),
            )
        )
        return
    typer.echo(header)
    typer.echo(f"  env:  {env_file}")
    typer.echo(f"  yaml: {config_path}")
    if env_result.backup_path is not None:
        typer.echo(f"  backup: {env_result.backup_path}")
    if separator and next_hint:
        typer.echo(next_hint)


def _wizard_success_detail_lines(
    *,
    env_file: Path,
    config_path: Path,
    backup_path: Path | None,
) -> list[str]:
    """Return interactive success details while keeping chrome formatting pure."""
    details = [f"env: {env_file}", f"yaml: {config_path}"]
    if backup_path is not None:
        details.append(f"backup: {backup_path}")
    return details


def collect_setup_check_lines(
    *,
    config_path: Path,
    env_file: Path,
) -> tuple[list[str], bool]:
    """Collect offline FR-18 setup check lines without printing.

    Loads ``env_file`` into the process environ (same as ``setup check``), then
    returns ``(lines, failed)`` for CLI echo or ``doctor`` reuse.

    Example::

        lines, failed = collect_setup_check_lines(
            config_path=Path("~/.cursor-agent/config.yaml"),
            env_file=Path(".env"),
        )
    """
    load_setup_dotenv(env_file)
    lines: list[str] = []
    failed = False

    config = None
    try:
        config = load_config(config_path=config_path)
        lines.append("ok: config load")
    except CursorAgentError as exc:
        lines.append(f"error: config load — {exc}")
        failed = True

    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if api_key:
        lines.append("ok: API key")
    else:
        lines.append("error: API key — CURSOR_API_KEY is empty or unset")
        failed = True

    if config is not None:
        failed = _append_path_check_lines(config, lines) or failed

    return lines, failed


def run_setup_check(*, config_path: Path, env_file: Path) -> None:
    """Run offline FR-18 checks; exit 1 when any check fails."""
    lines, failed = collect_setup_check_lines(
        config_path=config_path,
        env_file=env_file,
    )
    for line in lines:
        typer.echo(line)
    if failed:
        raise typer.Exit(1)


def _append_path_check_lines(config: CursorAgentConfig, lines: list[str]) -> bool:
    """Append workspace / memory / sessions-db check lines; return True if failed."""
    failed = False
    workspace = Path(config.runtime.local.cwd)
    if workspace.is_dir():
        lines.append(f"ok: workspace — {workspace}")
    else:
        lines.append(
            f"error: workspace — received {str(workspace)!r}, "
            "expected existing directory",
        )
        failed = True

    if config.memory_root is not None:
        memory_root = Path(config.memory_root)
        if memory_root.exists():
            lines.append(f"ok: memory root — {memory_root}")
        else:
            lines.append(
                f"error: memory root — received {str(memory_root)!r}, "
                "expected existing path",
            )
            failed = True
    else:
        lines.append("ok: memory root — (unset)")

    sessions_raw = os.environ.get("CURSOR_AGENT_SESSIONS_DB", "").strip()
    sessions_db = (
        Path(sessions_raw).expanduser() if sessions_raw else _DEFAULT_SESSIONS_DB
    )
    if parent_writable_or_creatable(sessions_db):
        lines.append(f"ok: sessions-db parent — {sessions_db.parent}")
    else:
        lines.append(
            f"error: sessions-db parent — received {str(sessions_db.parent)!r}, "
            "expected writable or creatable directory",
        )
        failed = True
    return failed


def parent_writable_or_creatable(target: Path) -> bool:
    """Return True when the parent of ``target`` is writable or can be created."""
    parent = target.expanduser().parent
    if parent.exists():
        return parent.is_dir() and os.access(parent, os.W_OK)

    current = parent
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    if not current.exists() or not current.is_dir():
        return False
    return os.access(current, os.W_OK)


def run_setup_show(*, config_path: Path, env_file: Path) -> None:
    """Print redacted effective config with source attribution (FR-4).

    Uses the process-environ snapshot taken before any dotenv load so keys
    present only in the env file attribute as ``env``, not ``shell``.
    ``build_effective_config`` merges ``dotenv_path`` itself (override=False).
    """
    process_environ = dict(snapshot_process_environ_before_dotenv())
    view = build_effective_config(
        config_path=config_path,
        environ=process_environ,
        dotenv_path=env_file if env_file.is_file() else None,
    )
    typer.echo(render_effective_config_redacted(view), nl=False)
