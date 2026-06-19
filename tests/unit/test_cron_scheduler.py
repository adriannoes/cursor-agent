"""Unit tests for core APScheduler cron lifecycle (PRD-010, FR-1, FR-6)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from cursor_agent.cron.models import CronJob
from cursor_agent.cron.scheduler import CronJobNextRun
from cursor_agent.errors import ConfigError
from tests.unit.cron_scheduler_test_helpers import (
    build_scheduler,
    make_cron_root,
    single_job_yaml,
    write_jobs_yaml,
)


@pytest.mark.asyncio
async def test_start_loads_jobs_from_disk(tmp_path: Path) -> None:
    """Scheduler loads validated jobs from ``jobs.yaml`` on start."""
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        yaml_content=single_job_yaml(job_id="morning-brief"),
    )

    await scheduler.start()
    try:
        jobs = scheduler.list_jobs_with_next_run()
        assert [entry.job.id for entry in jobs] == ["morning-brief"]
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_add_job_registers_with_scheduler(tmp_path: Path) -> None:
    """Programmatic ``add_job`` exposes the job and next-run metadata."""
    scheduler, _root, _executor = build_scheduler(tmp_path)
    job = CronJob.model_validate(
        {
            "id": "added-job",
            "schedule": "0 12 * * *",
            "prompt": "Run the added job.",
        }
    )

    await scheduler.start()
    try:
        scheduler.add_job(job)
        jobs = scheduler.list_jobs_with_next_run()
        assert len(jobs) == 1
        assert jobs[0].job.id == "added-job"
        assert jobs[0].next_run is not None
        assert jobs[0].next_run.tzinfo == timezone.utc
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_registered_job_uses_explicit_overlap_policy(tmp_path: Path) -> None:
    """Registered APScheduler jobs set max_instances/coalesce/misfire explicitly."""
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        yaml_content=single_job_yaml(job_id="policy-job"),
    )

    await scheduler.start()
    try:
        aps_job = scheduler._scheduler.get_job("cron:policy-job")
        assert aps_job is not None
        assert aps_job.max_instances == 1
        assert aps_job.coalesce is True
        assert aps_job.misfire_grace_time == 60
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_remove_job_unregisters_from_scheduler(tmp_path: Path) -> None:
    """``remove_job`` drops the job from scheduler state."""
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        yaml_content=single_job_yaml(job_id="to-remove"),
    )

    await scheduler.start()
    try:
        assert len(scheduler.list_jobs_with_next_run()) == 1
        scheduler.remove_job("to-remove")
        assert scheduler.list_jobs_with_next_run() == []
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_list_jobs_with_next_run_exposes_utc_metadata(tmp_path: Path) -> None:
    """Next-run metadata is UTC and includes schedule/runtime fields."""
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        yaml_content=single_job_yaml(
            job_id="meta-job",
            schedule="0 9 * * *",
            runtime="cloud",
            chat_id="999",
        ),
    )

    await scheduler.start()
    try:
        entries = scheduler.list_jobs_with_next_run()
        assert len(entries) == 1
        entry = entries[0]
        assert isinstance(entry, CronJobNextRun)
        assert entry.job.id == "meta-job"
        assert entry.job.schedule == "0 9 * * *"
        assert entry.job.runtime == "cloud"
        assert entry.next_run is not None
        assert entry.next_run.tzinfo == timezone.utc
        assert entry.next_run > datetime.now(timezone.utc)
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_load_jobs_raises_when_no_scheduler_started_for_add(
    tmp_path: Path,
) -> None:
    """``add_job`` before ``start`` still registers jobs for listing after start."""
    scheduler, _root, _executor = build_scheduler(tmp_path)
    job = CronJob.model_validate(
        {
            "id": "prestart-job",
            "schedule": "0 7 * * *",
            "prompt": "Added before start.",
        }
    )

    scheduler.add_job(job)
    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "prestart-job"
        ]
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_start_tears_down_scheduler_when_initial_load_fails(
    tmp_path: Path,
) -> None:
    """An invalid jobs.yaml at startup leaves no running APScheduler behind."""
    cron_root = make_cron_root(tmp_path)
    write_jobs_yaml(cron_root, "jobs:\n  - id: broken\n    schedule: not-a-cron\n")
    scheduler, _root, _executor = build_scheduler(tmp_path, cron_root=cron_root)

    with pytest.raises(ConfigError):
        await scheduler.start()

    assert scheduler._scheduler.running is False
    assert scheduler.list_jobs_with_next_run() == []
