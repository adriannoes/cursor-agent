"""Active cron job run tracking (concurrency cap, timeout, drain)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from cursor_agent.cron.models import CronJob

_MODULE_LOGGER = logging.getLogger(__name__)

CronJobExecutor = Callable[[CronJob], Awaitable[None]]
CronRunTimeoutHandler = Callable[[CronJob], Awaitable[None]]


class CronActiveRunTracker:
    """Track in-flight cron executions with concurrency cap, timeout, and drain.

    Independent of APScheduler; used by ``CronScheduler`` during job execution
    and graceful shutdown (ADR-021).

    Example:
        >>> tracker = CronActiveRunTracker(max_concurrent_jobs=3, executor=run_job)
        >>> await tracker.run(job)
    """

    def __init__(
        self,
        *,
        max_concurrent_jobs: int,
        executor: CronJobExecutor | None = None,
        job_run_timeout_seconds: float | None = None,
        on_run_timeout: CronRunTimeoutHandler | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_concurrent_jobs < 1:
            raise ValueError(
                f"invalid max_concurrent_jobs: received {max_concurrent_jobs!r}, "
                "expected a positive integer"
            )
        self._executor = executor
        self._job_run_timeout_seconds = job_run_timeout_seconds
        self._on_run_timeout = on_run_timeout
        self._logger = logger if logger is not None else _MODULE_LOGGER
        self._concurrency_semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self._active_tasks: set[asyncio.Task[None]] = set()

    @property
    def active_task_count(self) -> int:
        """Return how many in-flight asyncio tasks are registered with this tracker."""
        return len(self._active_tasks)

    async def run(self, job: CronJob) -> None:
        """Acquire concurrency, register the current task, and run the executor."""
        current_task = asyncio.current_task()
        if current_task is not None:
            self._active_tasks.add(current_task)
        try:
            async with self._concurrency_semaphore:
                await self._execute_with_optional_timeout(job)
        finally:
            if current_task is not None:
                self._active_tasks.discard(current_task)

    async def drain_or_cancel(self, timeout: float) -> None:
        """Await in-flight runs, then cancel any that exceed ``timeout``."""
        pending = list(self._active_tasks)
        if not pending:
            return

        _done, still_pending = await asyncio.wait(
            pending,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED,
        )
        if not still_pending:
            return

        self._logger.warning(
            "cron scheduler shutdown: %d job task(s) did not finish within %.3fs",
            len(still_pending),
            timeout,
        )
        for task in still_pending:
            task.cancel()
        await asyncio.gather(*still_pending, return_exceptions=True)

    async def _execute_with_optional_timeout(self, job: CronJob) -> None:
        """Run the executor, enforcing a per-job timeout when configured."""
        if self._executor is None:
            return
        if self._job_run_timeout_seconds is None:
            await self._executor(job)
            return
        try:
            await asyncio.wait_for(
                self._executor(job),
                timeout=self._job_run_timeout_seconds,
            )
        except TimeoutError:
            # Metadata only: never log prompt or assistant body (PRD-009 boundary).
            self._logger.warning(
                "cron job exceeded run timeout: job_id=%s timeout_seconds=%.3f",
                job.id,
                self._job_run_timeout_seconds,
            )
            if self._on_run_timeout is not None:
                await self._on_run_timeout(job)
