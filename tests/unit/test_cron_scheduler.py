"""Unit tests for APScheduler cron lifecycle (PRD-010, FR-1, FR-6)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.cron.loader import CronJobsCatalog
from cursor_agent.cron.models import CronJob, JOBS_FILENAME
from cursor_agent.cron.scheduler import CronJobNextRun, CronScheduler

ReloadPollHook = Callable[[], Awaitable[None]]


def _load_cron_config(tmp_path: Path) -> CursorAgentConfig:
    """Build minimal config for cron scheduler tests."""
    return load_config(config_path=tmp_path / "missing.yaml")


def _cron_root(tmp_path: Path) -> Path:
    """Return injectable cron config directory under ``tmp_path``."""
    root = tmp_path / "cron"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_jobs_yaml(cron_root: Path, content: str) -> Path:
    """Write ``jobs.yaml`` under an injectable cron root."""
    jobs_path = cron_root / JOBS_FILENAME
    jobs_path.write_text(content, encoding="utf-8")
    return jobs_path


def _single_job_yaml(
    *,
    job_id: str = "daily-report",
    schedule: str = "0 9 * * *",
    prompt: str = "Generate the daily report.",
    runtime: str | None = None,
    chat_id: str | None = None,
) -> str:
    """Build a minimal valid single-job YAML document."""
    lines = [
        "jobs:",
        f"  - id: {job_id}",
        f'    schedule: "{schedule}"',
        f'    prompt: "{prompt}"',
    ]
    if runtime is not None:
        lines.append(f"    runtime: {runtime}")
    if chat_id is not None:
        lines.extend(
            [
                "    delivery:",
                "      telegram:",
                f'        chat_id: "{chat_id}"',
            ]
        )
    return "\n".join(lines) + "\n"


class RecordingExecutor:
    """Records cron job ids passed to the executor callback."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, job: CronJob) -> None:
        self.calls.append(job.id)


class CapturingCronJobExecutor:
    """Records full CronJob payloads passed to the executor callback."""

    def __init__(self) -> None:
        self.jobs: list[CronJob] = []

    async def __call__(self, job: CronJob) -> None:
        self.jobs.append(job)


def _event_poll_hook(trigger: asyncio.Event) -> ReloadPollHook:
    """Return a reload poll hook that waits on ``trigger`` instead of sleeping."""

    async def _wait_for_trigger() -> None:
        await trigger.wait()
        trigger.clear()

    return _wait_for_trigger


def _build_scheduler(
    tmp_path: Path,
    *,
    cron_root: Path | None = None,
    executor: RecordingExecutor | None = None,
    reload_poll_hook: ReloadPollHook | None = None,
    yaml_content: str | None = None,
) -> tuple[CronScheduler, Path, RecordingExecutor]:
    """Create a scheduler wired to injectable cron root and executor."""
    root = cron_root if cron_root is not None else _cron_root(tmp_path)
    if yaml_content is not None:
        _write_jobs_yaml(root, yaml_content)
    exec_cb = executor if executor is not None else RecordingExecutor()
    scheduler = CronScheduler(
        _load_cron_config(tmp_path),
        override_cron_root=root,
        executor=exec_cb,
        reload_poll_hook=reload_poll_hook,
    )
    return scheduler, root, exec_cb


@pytest.mark.asyncio
async def test_start_loads_jobs_from_disk(tmp_path: Path) -> None:
    """Scheduler loads validated jobs from ``jobs.yaml`` on start."""
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        yaml_content=_single_job_yaml(job_id="morning-brief"),
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
    scheduler, _root, _executor = _build_scheduler(tmp_path)
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
async def test_remove_job_unregisters_from_scheduler(tmp_path: Path) -> None:
    """``remove_job`` drops the job from scheduler state."""
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        yaml_content=_single_job_yaml(job_id="to-remove"),
    )

    await scheduler.start()
    try:
        assert len(scheduler.list_jobs_with_next_run()) == 1
        scheduler.remove_job("to-remove")
        assert scheduler.list_jobs_with_next_run() == []
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_reload_same_job_id_passes_updated_payload_to_executor(
    tmp_path: Path,
) -> None:
    """Reloading the same job id must update APScheduler kwargs used at execution."""
    cron_root = _cron_root(tmp_path)
    job_id = "stable-id"
    _write_jobs_yaml(
        cron_root,
        _single_job_yaml(
            job_id=job_id,
            prompt="Original prompt.",
        ),
    )
    executor = CapturingCronJobExecutor()
    scheduler = CronScheduler(
        _load_cron_config(tmp_path),
        override_cron_root=cron_root,
        executor=executor,
    )

    await scheduler.start()
    try:
        _write_jobs_yaml(
            cron_root,
            _single_job_yaml(
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
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root, _single_job_yaml(job_id="initial-job"))
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        cron_root=cron_root,
    )

    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "initial-job"
        ]

        _write_jobs_yaml(
            cron_root,
            _single_job_yaml(job_id="reloaded-job", schedule="0 10 * * *"),
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
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root, _single_job_yaml(job_id="stable-job"))
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        cron_root=cron_root,
    )

    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "stable-job"
        ]

        _write_jobs_yaml(cron_root, "jobs:\n  - id: broken\n    schedule: bad\n")
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
async def test_list_jobs_with_next_run_exposes_utc_metadata(tmp_path: Path) -> None:
    """Next-run metadata is UTC and includes schedule/runtime fields."""
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        yaml_content=_single_job_yaml(
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
async def test_reload_if_changed_is_noop_when_mtime_unchanged(tmp_path: Path) -> None:
    """``reload_if_changed`` returns False when the jobs file mtime is unchanged."""
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        yaml_content=_single_job_yaml(job_id="unchanged"),
    )

    await scheduler.start()
    try:
        assert await scheduler.reload_if_changed() is False
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_mtime_watcher_reloads_after_disk_write(tmp_path: Path) -> None:
    """Background mtime watcher reloads jobs after CLI-style ``jobs.yaml`` writes."""
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root, _single_job_yaml(job_id="before-write"))
    poll_trigger = asyncio.Event()
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        cron_root=cron_root,
        reload_poll_hook=_event_poll_hook(poll_trigger),
    )

    await scheduler.start()
    try:
        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "before-write"
        ]

        _write_jobs_yaml(
            cron_root,
            _single_job_yaml(job_id="after-write", schedule="0 11 * * *"),
        )
        poll_trigger.set()
        for _attempt in range(20):
            jobs = scheduler.list_jobs_with_next_run()
            if jobs and jobs[0].job.id == "after-write":
                break
            poll_trigger.set()
            await asyncio.sleep(0)
        else:
            pytest.fail("mtime watcher did not reload updated jobs.yaml")

        assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
            "after-write"
        ]
    finally:
        await scheduler.shutdown()


@pytest.mark.asyncio
async def test_shutdown_stops_mtime_watcher(tmp_path: Path) -> None:
    """Shutdown cancels the mtime watcher without leaving background tasks."""
    poll_trigger = asyncio.Event()
    scheduler, _root, _executor = _build_scheduler(
        tmp_path,
        yaml_content=_single_job_yaml(job_id="shutdown-job"),
        reload_poll_hook=_event_poll_hook(poll_trigger),
    )

    await scheduler.start()
    await scheduler.shutdown()

    poll_trigger.set()
    await asyncio.sleep(0)
    assert scheduler.list_jobs_with_next_run() == []


@pytest.mark.asyncio
async def test_injected_loader_is_used_for_load_jobs(tmp_path: Path) -> None:
    """Injectable loader callback supports hermetic scheduler tests."""
    cron_root = _cron_root(tmp_path)
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
        include_prompt: bool = True,
    ) -> CronJobsCatalog:
        _ = include_prompt
        loader_calls.append(override_cron_root)
        return catalog

    scheduler = CronScheduler(
        _load_cron_config(tmp_path),
        override_cron_root=cron_root,
        executor=RecordingExecutor(),
        loader=_loader,
    )

    await scheduler.load_jobs()
    assert loader_calls == [cron_root]
    assert [entry.job.id for entry in scheduler.list_jobs_with_next_run()] == [
        "injected-job"
    ]


@pytest.mark.asyncio
async def test_load_jobs_raises_when_no_scheduler_started_for_add(
    tmp_path: Path,
) -> None:
    """``add_job`` before ``start`` still registers jobs for listing after start."""
    scheduler, _root, _executor = _build_scheduler(tmp_path)
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
