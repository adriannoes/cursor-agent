"""Unit tests for cron scheduler reload, mtime watching, and path containment."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.cron.loader import CronJobsCatalog
from cursor_agent.cron.models import CronJob, JOBS_FILENAME
from cursor_agent.cron.scheduler import CronScheduler
from cursor_agent.errors import ConfigError
from tests.unit.cron_scheduler_test_helpers import (
    CapturingCronJobExecutor,
    RecordingExecutor,
    build_scheduler,
    event_poll_hook,
    load_cron_config,
    make_cron_root,
    single_job_yaml,
    symlinked_cron_root,
    write_jobs_yaml,
)


@pytest.mark.asyncio
async def test_reload_same_job_id_passes_updated_payload_to_executor(
    tmp_path: Path,
) -> None:
    """Reloading the same job id must update APScheduler kwargs used at execution."""
    cron_root = make_cron_root(tmp_path)
    job_id = "stable-id"
    write_jobs_yaml(
        cron_root,
        single_job_yaml(
            job_id=job_id,
            prompt="Original prompt.",
        ),
    )
    executor = CapturingCronJobExecutor()
    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        override_cron_root=cron_root,
        executor=executor,
    )

    await scheduler.start()
    try:
        write_jobs_yaml(
            cron_root,
            single_job_yaml(
                job_id=job_id,
                prompt="Updated prompt.",
                runtime="cloud",
                chat_id="12345",
            ),
        )
        assert await scheduler.reload_if_changed() is True

        cached = scheduler.list_jobs_with_next_run()[0].job
        assert cached.prompt == "Updated prompt."
        assert cached.runtime == "cloud"

        aps_job = scheduler._scheduler.get_job(f"cron:{job_id}")
        assert aps_job is not None
        assert aps_job.kwargs["job"].prompt == "Updated prompt."
        assert aps_job.kwargs["job"].runtime == "cloud"
        await aps_job.func(**aps_job.kwargs)

        assert len(executor.jobs) == 1
        executed = executor.jobs[0]
        assert executed.prompt == "Updated prompt."
        assert executed.runtime == "cloud"
        assert executed.delivery is not None
        assert executed.delivery.telegram is not None
        assert executed.delivery.telegram.chat_id == "12345"
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_reload_if_changed_applies_disk_updates(tmp_path: Path) -> None:
    """``reload_if_changed`` picks up ``jobs.yaml`` edits after mtime changes."""
    cron_root = make_cron_root(tmp_path)
    write_jobs_yaml(cron_root, single_job_yaml(job_id="initial-job"))
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        cron_root=cron_root,
    )

    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "initial-job"
        ]

        write_jobs_yaml(
            cron_root,
            single_job_yaml(job_id="reloaded-job", schedule="0 10 * * *"),
        )
        reloaded = await scheduler.reload_if_changed()
        assert reloaded is True
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "reloaded-job"
        ]
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_reload_if_changed_keeps_last_known_good_on_invalid_yaml(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid reload keeps the previous job cache and logs a safe warning."""
    cron_root = make_cron_root(tmp_path)
    write_jobs_yaml(cron_root, single_job_yaml(job_id="stable-job"))
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        cron_root=cron_root,
    )

    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "stable-job"
        ]

        write_jobs_yaml(cron_root, "jobs:\n  - id: broken\n    schedule: bad\n")
        with caplog.at_level(logging.WARNING):
            reloaded = await scheduler.reload_if_changed()

        assert reloaded is False
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "stable-job"
        ]
        assert any("stable-job" not in record.getMessage() for record in caplog.records)
        assert any(
            "reload" in record.getMessage().lower()
            or "invalid" in record.getMessage().lower()
            for record in caplog.records
        )
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_reload_if_changed_is_noop_when_mtime_unchanged(tmp_path: Path) -> None:
    """``reload_if_changed`` returns False when the jobs file mtime is unchanged."""
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        yaml_content=single_job_yaml(job_id="unchanged"),
    )

    await scheduler.start()
    try:
        assert await scheduler.reload_if_changed() is False
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_mtime_watcher_reloads_after_disk_write(tmp_path: Path) -> None:
    """Background mtime watcher reloads jobs after CLI-style ``jobs.yaml`` writes."""
    cron_root = make_cron_root(tmp_path)
    write_jobs_yaml(cron_root, single_job_yaml(job_id="before-write"))
    poll_trigger = asyncio.Event()
    scheduler, _root, _executor = build_scheduler(
        tmp_path,
        cron_root=cron_root,
        reload_poll_hook=event_poll_hook(poll_trigger),
    )

    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "before-write"
        ]

        write_jobs_yaml(
            cron_root,
            single_job_yaml(job_id="after-write", schedule="0 11 * * *"),
        )
        # The watcher reload parses jobs.yaml via asyncio.to_thread, so the poll
        # loop must yield real wall-clock time for the worker thread to finish.
        # A bare sleep(0) spin completed too fast on CI and missed the reload.
        for _attempt in range(100):
            poll_trigger.set()
            await asyncio.sleep(0.02)
            jobs = scheduler.list_jobs_with_next_run()
            if jobs and jobs[0].job.id == "after-write":
                break
        else:
            pytest.fail("mtime watcher did not reload updated jobs.yaml")

        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "after-write"
        ]
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_start_rejects_symlinked_cron_root_without_mtime_watcher(
    tmp_path: Path,
) -> None:
    """Startup rejects a symlinked cron root before APScheduler or mtime watching."""
    cron_root, target = symlinked_cron_root(tmp_path)
    (target / JOBS_FILENAME).write_text(
        single_job_yaml(job_id="unsafe-root"),
        encoding="utf-8",
    )
    scheduler, _root, _executor = build_scheduler(tmp_path, cron_root=cron_root)

    with pytest.raises(ConfigError, match="symlink|root|contained"):
        await scheduler.start()

    assert scheduler._started is False
    assert scheduler._watcher_task is None
    assert scheduler._scheduler.running is False
    assert not (target / "jobs.yaml.lock").exists()


@pytest.mark.asyncio
async def test_reload_if_changed_rejects_symlinked_cron_root(tmp_path: Path) -> None:
    """Reload path resolution rejects symlinked cron roots before stat/mtime checks."""
    cron_root, target = symlinked_cron_root(tmp_path)
    (target / JOBS_FILENAME).write_text(
        single_job_yaml(job_id="unsafe-root"),
        encoding="utf-8",
    )
    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        override_cron_root=cron_root,
        executor=RecordingExecutor(),
    )

    with pytest.raises(ConfigError, match="symlink|root|contained"):
        await scheduler.reload_if_changed()


@pytest.mark.asyncio
async def test_load_jobs_rejects_symlinked_cron_root_without_recording_mtime(
    tmp_path: Path,
) -> None:
    """``load_jobs`` fails fast on symlinked roots without caching escaped mtimes."""
    cron_root, target = symlinked_cron_root(tmp_path)
    (target / JOBS_FILENAME).write_text(
        single_job_yaml(job_id="unsafe-root"),
        encoding="utf-8",
    )
    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        override_cron_root=cron_root,
        executor=RecordingExecutor(),
    )

    with pytest.raises(ConfigError, match="symlink|root|contained"):
        await scheduler.load_jobs()

    assert scheduler._jobs_mtime is None
    assert scheduler.list_jobs_with_next_run() == []


@pytest.mark.asyncio
async def test_injected_loader_is_used_for_load_jobs(tmp_path: Path) -> None:
    """Injectable loader callback supports hermetic scheduler tests."""
    cron_root = make_cron_root(tmp_path)
    catalog = CronJobsCatalog(
        (
            CronJob.model_validate(
                {
                    "id": "injected-job",
                    "schedule": "0 8 * * *",
                    "prompt": "From injected loader.",
                }
            ),
        )
    )
    loader_calls: list[Path | None] = []

    def _loader(
        _config: CursorAgentConfig,
        *,
        override_cron_root: Path | None = None,
    ) -> CronJobsCatalog:
        loader_calls.append(override_cron_root)
        return catalog

    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        override_cron_root=cron_root,
        executor=RecordingExecutor(),
        loader=_loader,
    )

    await scheduler.load_jobs()
    assert loader_calls == [cron_root]
    assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
        "injected-job"
    ]
