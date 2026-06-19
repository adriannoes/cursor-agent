"""Unit tests for cron scheduler concurrency, timeouts, and shutdown drain."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cursor_agent.cron.models import CronJob
from cursor_agent.cron.scheduler import CronScheduler
from tests.unit.cron_scheduler_test_helpers import (
    build_scheduler,
    event_poll_hook,
    load_cron_config,
    make_cron_root,
    single_job_yaml,
)


@pytest.mark.asyncio
async def test_per_job_run_timeout_returns_without_hanging(tmp_path: Path) -> None:
    """A job exceeding job_run_timeout_seconds is cancelled and _run_job returns."""
    started = asyncio.Event()

    async def slow_executor(job: CronJob) -> None:
        started.set()
        await asyncio.sleep(5)

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=slow_executor,
        override_cron_root=make_cron_root(tmp_path),
        job_run_timeout_seconds=0.02,
    )
    job = CronJob.model_validate({"id": "slow", "schedule": "0 9 * * *", "prompt": "x"})

    await asyncio.wait_for(scheduler._run_job(job), timeout=1.0)
    assert started.is_set()


@pytest.mark.asyncio
async def test_concurrent_jobs_respect_max_cap(tmp_path: Path) -> None:
    """No more than max_concurrent_jobs run the executor body at once."""
    active = 0
    peak = 0
    release = asyncio.Event()

    async def gated_executor(job: CronJob) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await release.wait()
        active -= 1

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=gated_executor,
        override_cron_root=make_cron_root(tmp_path),
        max_concurrent_jobs=2,
    )
    jobs = [
        CronJob.model_validate(
            {"id": f"job-{index}", "schedule": "0 9 * * *", "prompt": "x"}
        )
        for index in range(5)
    ]

    tasks = [asyncio.create_task(scheduler._run_job(job)) for job in jobs]
    await asyncio.sleep(0.05)
    assert peak <= 2
    release.set()
    await asyncio.gather(*tasks)
    assert peak == 2


def test_invalid_max_concurrent_jobs_is_rejected(tmp_path: Path) -> None:
    """A non-positive concurrency cap raises a clear ValueError."""
    with pytest.raises(ValueError, match="max_concurrent_jobs"):
        CronScheduler(
            load_cron_config(tmp_path),
            override_cron_root=make_cron_root(tmp_path),
            max_concurrent_jobs=0,
        )


@pytest.mark.asyncio
async def test_shutdown_stops_mtime_watcher(tmp_path: Path) -> None:
    """Shutdown cancels the mtime watcher without leaving background tasks."""
    poll_trigger = asyncio.Event()
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        yaml_content=single_job_yaml(job_id="shutdown-job"),
        reload_poll_hook=event_poll_hook(poll_trigger),
    )

    await scheduler.start()
    await scheduler.shutdown()

    poll_trigger.set()
    await asyncio.sleep(0)
    assert scheduler.list_jobs_with_next_run() == []


@pytest.mark.asyncio
async def test_job_run_timeout_invokes_on_run_timeout_handler(
    tmp_path: Path,
) -> None:
    """Per-job timeout invokes the configured timeout handler for observability."""
    started = asyncio.Event()
    timed_out_job_ids: list[str] = []

    async def slow_executor(job: CronJob) -> None:
        started.set()
        await asyncio.sleep(5)

    async def on_run_timeout(job: CronJob) -> None:
        timed_out_job_ids.append(job.id)

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=slow_executor,
        override_cron_root=make_cron_root(tmp_path),
        job_run_timeout_seconds=0.02,
        on_run_timeout=on_run_timeout,
    )
    job = CronJob.model_validate(
        {"id": "slow-timeout", "schedule": "0 9 * * *", "prompt": "secret"}
    )

    await asyncio.wait_for(scheduler._run_job(job), timeout=1.0)

    assert started.is_set()
    assert timed_out_job_ids == ["slow-timeout"]


@pytest.mark.asyncio
async def test_job_run_timeout_logs_safe_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Per-job timeout emits metadata-only warning without prompt or assistant body."""
    started = asyncio.Event()

    async def slow_executor(job: CronJob) -> None:
        started.set()
        await asyncio.sleep(5)

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=slow_executor,
        override_cron_root=make_cron_root(tmp_path),
        job_run_timeout_seconds=0.02,
    )
    job = CronJob.model_validate(
        {"id": "slow-timeout", "schedule": "0 9 * * *", "prompt": "secret"}
    )

    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(scheduler._run_job(job), timeout=1.0)

    assert started.is_set()
    timeout_records = [
        record for record in caplog.records if "timeout" in record.getMessage().lower()
    ]
    assert len(timeout_records) == 1
    message = timeout_records[0].getMessage()
    assert "slow-timeout" in message
    assert "secret" not in message


@pytest.mark.asyncio
async def test_concurrency_active_run_tracker_reports_in_flight_count(
    tmp_path: Path,
) -> None:
    """The active-run tracker seam exposes how many job tasks are in flight."""
    release = asyncio.Event()

    async def gated_executor(job: CronJob) -> None:
        await release.wait()

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=gated_executor,
        override_cron_root=make_cron_root(tmp_path),
        max_concurrent_jobs=2,
    )
    jobs = [
        CronJob.model_validate(
            {"id": f"tracked-{index}", "schedule": "0 9 * * *", "prompt": "x"}
        )
        for index in range(3)
    ]
    tracker = scheduler.active_run_tracker

    tasks = [asyncio.create_task(scheduler._run_job(job)) for job in jobs]
    await asyncio.sleep(0.05)
    assert tracker.active_task_count == 3

    release.set()
    await asyncio.gather(*tasks)
    assert tracker.active_task_count == 0


@pytest.mark.asyncio
async def test_shutdown_drains_active_runs_within_timeout(tmp_path: Path) -> None:
    """Shutdown awaits in-flight cron runs that finish within the drain timeout."""
    started = asyncio.Event()
    finished = asyncio.Event()
    release = asyncio.Event()

    async def finishing_executor(job: CronJob) -> None:
        started.set()
        await release.wait()
        finished.set()

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=finishing_executor,
        override_cron_root=make_cron_root(tmp_path),
        reload_poll_hook=lambda: asyncio.sleep(3600),
    )
    job = CronJob.model_validate(
        {"id": "drain-ok", "schedule": "0 9 * * *", "prompt": "x"}
    )

    await scheduler.start()
    run_task = asyncio.create_task(scheduler._run_job(job))
    await started.wait()
    assert scheduler.active_run_tracker.active_task_count == 1

    release.set()
    await scheduler.shutdown(timeout=1.0)
    await run_task

    assert finished.is_set()
    assert scheduler.active_run_tracker.active_task_count == 0


@pytest.mark.asyncio
async def test_shutdown_active_run_tracker_cancels_stuck_runs_on_drain_timeout(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Drain cancels stuck runs after timeout and logs a safe shutdown warning."""
    started = asyncio.Event()
    release = asyncio.Event()

    async def stuck_executor(job: CronJob) -> None:
        started.set()
        await release.wait()

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        executor=stuck_executor,
        override_cron_root=make_cron_root(tmp_path),
    )
    job = CronJob.model_validate(
        {"id": "stuck-drain", "schedule": "0 9 * * *", "prompt": "x"}
    )
    tracker = scheduler.active_run_tracker

    run_task = asyncio.create_task(scheduler._run_job(job))
    await started.wait()
    assert tracker.active_task_count == 1

    with caplog.at_level(logging.WARNING):
        await tracker.drain_or_cancel(timeout=0.02)

    assert run_task.done()
    assert tracker.active_task_count == 0
    drain_records = [
        record
        for record in caplog.records
        if "shutdown" in record.getMessage().lower()
        and "did not finish" in record.getMessage().lower()
    ]
    assert len(drain_records) == 1

    release.set()
