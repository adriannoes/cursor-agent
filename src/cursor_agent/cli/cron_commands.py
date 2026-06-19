"""Typer handlers for ``cursor-agent cron`` (PRD-010, FR-5)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.cli.rich_display import format_cron_jobs_table
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.cron.models import CronJob, CronJobSummary, cron_trigger_for_schedule
from cursor_agent.cron.store import (
    add_cron_job_atomic,
    build_cron_job,
    default_cron_root,
    load_cron_job_summaries_catalog,
    load_cron_jobs_catalog,
    remove_cron_job_atomic,
)
from cursor_agent.errors import ConfigError, CursorAgentError

cron_app = typer.Typer(help="Manage scheduled cron jobs")

_EMPTY_CRON_JOBS_MESSAGE = "No cron jobs configured."


def _exit_on_cursor_agent_error(exc: CursorAgentError) -> NoReturn:
    """Print an actionable CLI error and exit with the mapped code."""
    typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for_error(exc)) from exc


def resolve_cron_root(_config: CursorAgentConfig) -> Path:
    """Return the cron config directory for CLI commands.

    Tests monkeypatch this hook to inject ``tmp_path`` roots.
    """
    return default_cron_root()


def _next_run_for_schedule(schedule: str) -> datetime | None:
    """Compute the next UTC fire time for a validated schedule expression."""
    trigger = cron_trigger_for_schedule(schedule)
    next_fire = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
    if isinstance(next_fire, datetime):
        return next_fire
    return None


def _format_next_run(next_run: datetime | None) -> str:
    """Format next-run metadata for tabular CLI output."""
    if next_run is None:
        return "-"
    return next_run.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _telegram_chat_id(job: CronJob | CronJobSummary) -> str:
    """Return configured Telegram chat id or a dash placeholder."""
    if job.delivery is None or job.delivery.telegram is None:
        return "-"
    return job.delivery.telegram.chat_id


@cron_app.command("list")
def cron_list() -> None:
    """List configured cron jobs with schedule and next-run metadata."""
    try:
        config = load_config()
        cron_root = resolve_cron_root(config)
        catalog = load_cron_job_summaries_catalog(config, cron_root)
        summaries = catalog.list_summaries()
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    if not summaries:
        typer.echo(_EMPTY_CRON_JOBS_MESSAGE)
        return

    rows = [
        {
            "id": summary.id,
            "schedule": summary.schedule,
            "next_run": _format_next_run(_next_run_for_schedule(summary.schedule)),
            "runtime": summary.runtime,
            "telegram_chat_id": _telegram_chat_id(summary),
        }
        for summary in summaries
    ]
    typer.echo(format_cron_jobs_table(rows))


@cron_app.command("show")
def cron_show(
    job_id: Annotated[str, typer.Argument(help="Case-sensitive cron job id to show.")],
) -> None:
    """Show the full configuration for a single cron job."""
    try:
        config = load_config()
        cron_root = resolve_cron_root(config)
        catalog = load_cron_jobs_catalog(config, cron_root)
        job = catalog.get_job(job_id)
        if job is None:
            raise ConfigError(
                f"cron job not found: received id {job_id!r}, "
                "expected an existing case-sensitive job id"
            )
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    lines = [
        f"id: {job.id}",
        f"schedule: {job.schedule}",
        f"next_run: {_format_next_run(_next_run_for_schedule(job.schedule))}",
        f"runtime: {job.runtime}",
        f"telegram_chat_id: {_telegram_chat_id(job)}",
        f"prompt: {job.prompt}",
    ]
    typer.echo("\n".join(lines))


@cron_app.command("add")
def cron_add(
    job_id: Annotated[str, typer.Argument(help="Unique case-sensitive cron job id.")],
    schedule: Annotated[
        str,
        typer.Option("--schedule", help="Cron schedule expression (UTC)."),
    ],
    prompt: Annotated[
        str,
        typer.Option(
            "--prompt",
            help="Prompt sent to the agent on each run (max 64 KiB).",
        ),
    ],
    runtime: Annotated[
        str,
        typer.Option(
            "--runtime",
            help="Execution runtime override (local or cloud).",
        ),
    ] = "local",
    chat_id: Annotated[
        str | None,
        typer.Option(
            "--chat-id",
            help="Optional Telegram chat id for post-run delivery.",
        ),
    ] = None,
) -> None:
    """Add a cron job to jobs.yaml."""
    try:
        config = load_config()
        cron_root = resolve_cron_root(config)
        job = build_cron_job(
            job_id=job_id,
            schedule=schedule,
            prompt=prompt,
            runtime=runtime,
            chat_id=chat_id,
        )
        add_cron_job_atomic(config, cron_root, job)
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    typer.echo(f"Added cron job {job_id!r}.")


@cron_app.command("remove")
def cron_remove(
    job_id: Annotated[
        str, typer.Argument(help="Case-sensitive cron job id to remove.")
    ],
) -> None:
    """Remove a cron job from jobs.yaml."""
    try:
        config = load_config()
        cron_root = resolve_cron_root(config)
        remove_cron_job_atomic(config, cron_root, job_id)
    except CursorAgentError as exc:
        _exit_on_cursor_agent_error(exc)

    typer.echo(f"Removed cron job {job_id!r}.")
