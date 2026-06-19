"""APScheduler lifecycle wrapper for declarative cron jobs (PRD-010, FR-1, FR-6)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.cron.loader import CronJobsCatalog, cron_jobs_from_config
from cursor_agent.cron.models import CronJob, cron_trigger_for_schedule
from cursor_agent.cron.paths import DEFAULT_CRON_ROOT, resolve_cron_jobs_file
from cursor_agent.cron.runs import CronActiveRunTracker, CronRunTimeoutHandler
from cursor_agent.errors import ConfigError


_MODULE_LOGGER = logging.getLogger(__name__)

DEFAULT_CRON_SHUTDOWN_TIMEOUT_SECONDS: Final[float] = 30.0

CronJobExecutor = Callable[[CronJob], Awaitable[None]]
CronJobsLoader = Callable[..., CronJobsCatalog]
ReloadPollHook = Callable[[], Awaitable[None]]
ShuttingDownCheck = Callable[[], bool]

DEFAULT_RELOAD_POLL_INTERVAL_SECONDS: Final[float] = 1.0
_APSCHEDULER_JOB_PREFIX: Final[str] = "cron:"

# Overlap policy: never run two instances of the same job concurrently, collapse
# bursts of missed fires into one, and tolerate up to one minimum-interval of
# delay before treating a fire as missed (aligns with the >=1-minute schedule
# floor). Explicit values avoid relying on fragile APScheduler defaults.
CRON_JOB_MAX_INSTANCES: Final[int] = 1
CRON_JOB_COALESCE: Final[bool] = True
DEFAULT_CRON_MISFIRE_GRACE_SECONDS: Final[int] = 60

# Cap concurrent job executions so a burst of simultaneous fires cannot exhaust
# the shared gateway pool or SDK resources. Tunable per scheduler instance.
DEFAULT_MAX_CONCURRENT_CRON_JOBS: Final[int] = 5


@dataclass(frozen=True, slots=True)
class CronJobNextRun:
    """Cron job metadata paired with the next scheduled fire time."""

    job: CronJob
    next_run: datetime | None


class CronScheduler:
    """Manage APScheduler triggers for validated cron jobs.

    Loads ``jobs.yaml`` through an injectable loader, caches the last known-good
    catalog, and reloads when the file mtime changes. Invalid reloads keep the
    previous cache and emit a safe warning without prompt bodies.

    Example:
        >>> scheduler = CronScheduler(config, override_cron_root=tmp_path / "cron")
        >>> await scheduler.start()
        >>> scheduler.list_jobs_with_next_run()
    """

    def __init__(
        self,
        config: CursorAgentConfig,
        *,
        executor: CronJobExecutor | None = None,
        override_cron_root: Path | None = None,
        loader: CronJobsLoader | None = None,
        reload_poll_interval_seconds: float = DEFAULT_RELOAD_POLL_INTERVAL_SECONDS,
        reload_poll_hook: ReloadPollHook | None = None,
        max_concurrent_jobs: int = DEFAULT_MAX_CONCURRENT_CRON_JOBS,
        job_run_timeout_seconds: float | None = None,
        on_run_timeout: CronRunTimeoutHandler | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._override_cron_root = override_cron_root
        self._loader = loader if loader is not None else cron_jobs_from_config
        self._executor = executor
        self._reload_poll_interval_seconds = reload_poll_interval_seconds
        self._reload_poll_hook = reload_poll_hook
        self._logger = logger if logger is not None else _MODULE_LOGGER
        self._active_run_tracker = CronActiveRunTracker(
            max_concurrent_jobs=max_concurrent_jobs,
            executor=executor,
            job_run_timeout_seconds=job_run_timeout_seconds,
            on_run_timeout=on_run_timeout,
            logger=self._logger,
        )

        self._scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self._jobs: dict[str, CronJob] = {}
        self._jobs_mtime: float | None = None
        self._started = False
        self._watcher_task: asyncio.Task[None] | None = None
        self._watcher_stop = asyncio.Event()
        self._pending_jobs: list[CronJob] = []
        self._shutting_down = False
        self._shutdown_complete = False
        self._shutting_down_check: ShuttingDownCheck | None = None

    @property
    def active_run_tracker(self) -> CronActiveRunTracker:
        """Expose active-run tracking for graceful shutdown and focused tests."""
        return self._active_run_tracker

    async def start(self) -> None:
        """Start APScheduler, load jobs from disk, and begin mtime watching."""
        if self._started:
            return

        # Load and register jobs before starting APScheduler. An invalid
        # jobs.yaml then fails fast without leaving a running scheduler behind
        # (APScheduler buffers jobs added before start).
        await self.load_jobs()

        if not self._scheduler.running:
            self._scheduler.start()

        for job in self._pending_jobs:
            self._register_job(job)
        self._pending_jobs.clear()
        self._started = True
        self._watcher_stop.clear()
        self._watcher_task = asyncio.create_task(
            self._mtime_watcher_loop(),
            name="cron-mtime-watcher",
        )

    def set_shutting_down_check(self, check: ShuttingDownCheck) -> None:
        """Register a callback that reports gateway-wide shutdown state."""
        self._shutting_down_check = check

    def pause_scheduling(self) -> None:
        """Stop accepting new cron triggers without waiting for in-flight runs."""
        self._shutting_down = True
        if self._scheduler.running:
            self._scheduler.pause()

    async def shutdown(
        self,
        *,
        timeout: float | None = None,
    ) -> None:
        """Stop mtime watching, await in-flight runs, and shut down APScheduler."""
        if self._shutdown_complete:
            return

        self.pause_scheduling()
        await self._stop_mtime_watcher()
        await self._active_run_tracker.drain_or_cancel(
            timeout if timeout is not None else DEFAULT_CRON_SHUTDOWN_TIMEOUT_SECONDS,
        )

        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

        self._jobs.clear()
        self._jobs_mtime = None
        self._started = False
        self._pending_jobs.clear()
        self._shutdown_complete = True

    async def load_jobs(self) -> None:
        """Load jobs from disk and synchronize APScheduler triggers."""
        catalog = await asyncio.to_thread(
            self._loader,
            self._config,
            override_cron_root=self._override_cron_root,
        )
        jobs_path = self._jobs_file_path()
        if jobs_path is not None and jobs_path.exists():
            self._jobs_mtime = jobs_path.stat().st_mtime
        else:
            self._jobs_mtime = None
        self._replace_jobs(catalog.list_jobs())

    async def reload_if_changed(self) -> bool:
        """Reload jobs when ``jobs.yaml`` mtime changed; return whether reload ran.

        On ``ConfigError`` during reload, the last known-good cache is kept and
        ``_jobs_mtime`` is advanced to the file's current mtime so the same broken
        file is not re-parsed every poll. Touch ``jobs.yaml`` after fixing content
        so the next edit produces a newer mtime and triggers reload again.
        """
        jobs_path = self._jobs_file_path()
        if jobs_path is None or not jobs_path.exists():
            current_mtime: float | None = None
        else:
            current_mtime = jobs_path.stat().st_mtime

        if current_mtime == self._jobs_mtime:
            return False

        try:
            catalog = await asyncio.to_thread(
                self._loader,
                self._config,
                override_cron_root=self._override_cron_root,
            )
        except ConfigError as exc:
            self._logger.warning(
                "cron scheduler reload failed: keeping last known-good cache (%s)",
                exc,
            )
            if jobs_path is not None and jobs_path.exists():
                self._jobs_mtime = jobs_path.stat().st_mtime
            return False

        self._jobs_mtime = current_mtime
        self._replace_jobs(catalog.list_jobs())
        return True

    def add_job(self, job: CronJob) -> None:
        """Register a validated job with the scheduler."""
        if self._started:
            self._register_job(job)
            return
        self._pending_jobs.append(job)

    def remove_job(self, job_id: str) -> None:
        """Remove a job from the scheduler by id."""
        self._jobs.pop(job_id, None)
        aps_job_id = _apscheduler_job_id(job_id)
        if self._scheduler.get_job(aps_job_id) is not None:
            self._scheduler.remove_job(aps_job_id)

    def list_jobs_with_next_run(self) -> list[CronJobNextRun]:
        """Return cached jobs with UTC next-run metadata for ``cron list``."""
        entries: list[CronJobNextRun] = []
        for job in self._jobs.values():
            entries.append(
                CronJobNextRun(job=job, next_run=self._next_run_for_job(job))
            )
        return sorted(entries, key=lambda entry: entry.job.id)

    async def _mtime_watcher_loop(self) -> None:
        while not self._watcher_stop.is_set():
            try:
                await self._poll_for_reload()
            except asyncio.CancelledError:
                break

            if self._watcher_stop.is_set():
                break

            try:
                await self.reload_if_changed()
            except Exception:
                self._logger.warning(
                    "cron scheduler mtime watcher reload failed",
                    exc_info=True,
                )

    async def _poll_for_reload(self) -> None:
        if self._reload_poll_hook is not None:
            await self._reload_poll_hook()
            return
        try:
            await asyncio.wait_for(
                self._watcher_stop.wait(),
                timeout=self._reload_poll_interval_seconds,
            )
        except TimeoutError:
            return

    def _replace_jobs(self, jobs: list[CronJob]) -> None:
        incoming_ids = {job.id for job in jobs}
        for job_id in list(self._jobs):
            if job_id not in incoming_ids:
                self.remove_job(job_id)

        for job in jobs:
            self._register_job(job)

    def _register_job(self, job: CronJob) -> None:
        self._jobs[job.id] = job
        trigger = _trigger_for_job(job)
        aps_job_id = _apscheduler_job_id(job.id)

        if self._scheduler.get_job(aps_job_id) is not None:
            self._scheduler.reschedule_job(aps_job_id, trigger=trigger)
            self._scheduler.modify_job(aps_job_id, kwargs={"job": job})
            return

        self._scheduler.add_job(
            self._run_job,
            trigger=trigger,
            id=aps_job_id,
            kwargs={"job": job},
            replace_existing=True,
            max_instances=CRON_JOB_MAX_INSTANCES,
            coalesce=CRON_JOB_COALESCE,
            misfire_grace_time=DEFAULT_CRON_MISFIRE_GRACE_SECONDS,
        )

    async def _run_job(self, job: CronJob) -> None:
        current_job = self._jobs.get(job.id)
        if current_job is not None:
            job = current_job
        if self._should_skip_job():
            return
        if self._executor is None:
            return

        await self._active_run_tracker.run(job)

    def _should_skip_job(self) -> bool:
        if self._shutting_down:
            return True
        if self._shutting_down_check is not None and self._shutting_down_check():
            return True
        return False

    async def _stop_mtime_watcher(self) -> None:
        self._watcher_stop.set()
        if self._watcher_task is None:
            return
        self._watcher_task.cancel()
        try:
            await self._watcher_task
        except asyncio.CancelledError:
            pass
        self._watcher_task = None

    def _next_run_for_job(self, job: CronJob) -> datetime | None:
        aps_job = self._scheduler.get_job(_apscheduler_job_id(job.id))
        if aps_job is not None and self._scheduler.running:
            next_run = getattr(aps_job, "next_run_time", None)
            if isinstance(next_run, datetime):
                return next_run

        trigger = _trigger_for_job(job)
        next_fire = trigger.get_next_fire_time(None, datetime.now(timezone.utc))
        if isinstance(next_fire, datetime):
            return next_fire
        return None

    def _jobs_file_path(self) -> Path | None:
        cron_root = (
            self._override_cron_root
            if self._override_cron_root is not None
            else DEFAULT_CRON_ROOT
        )
        return resolve_cron_jobs_file(cron_root)


def _apscheduler_job_id(job_id: str) -> str:
    return f"{_APSCHEDULER_JOB_PREFIX}{job_id}"


def _trigger_for_job(job: CronJob) -> CronTrigger:
    return cron_trigger_for_schedule(job.schedule)
