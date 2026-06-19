"""Shared helpers for cron scheduler unit tests (PRD-010)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.cron.models import CronJob, JOBS_FILENAME
from cursor_agent.cron.scheduler import CronScheduler

ReloadPollHook = Callable[[], Awaitable[None]]


def load_cron_config(tmp_path: Path) -> CursorAgentConfig:
    """Build minimal config for cron scheduler tests."""
    return load_config(config_path=tmp_path / "missing.yaml")


def make_cron_root(tmp_path: Path) -> Path:
    """Return injectable cron config directory under ``tmp_path``."""
    root = tmp_path / "cron"
    root.mkdir(parents=True, exist_ok=True)
    return root


def symlinked_cron_root(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(cron_root_symlink, symlink_target)`` for path containment tests."""
    target = tmp_path / "cron-target"
    target.mkdir(parents=True, exist_ok=True)
    cron_root_link = tmp_path / "cron"
    cron_root_link.symlink_to(target)
    return cron_root_link, target


def write_jobs_yaml(cron_root: Path, content: str) -> Path:
    """Write ``jobs.yaml`` under an injectable cron root.

    Rewrites force a strictly newer mtime than the previous file so the
    scheduler's mtime-based reload is deterministic on filesystems with coarse
    mtime granularity (observed flaky on CI when two writes shared one tick).
    """
    jobs_path = cron_root / JOBS_FILENAME
    previous_mtime = jobs_path.stat().st_mtime if jobs_path.exists() else None
    jobs_path.write_text(content, encoding="utf-8")
    if previous_mtime is not None:
        bumped = max(jobs_path.stat().st_mtime, previous_mtime) + 1
        os.utime(jobs_path, (bumped, bumped))
    return jobs_path


def single_job_yaml(
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


def event_poll_hook(trigger: asyncio.Event) -> ReloadPollHook:
    """Return a reload poll hook that waits on ``trigger`` instead of sleeping."""

    async def _wait_for_trigger() -> None:
        await trigger.wait()
        trigger.clear()

    return _wait_for_trigger


def build_scheduler(
    tmp_path: Path,
    *,
    cron_root: Path | None = None,
    executor: RecordingExecutor | None = None,
    reload_poll_hook: ReloadPollHook | None = None,
    yaml_content: str | None = None,
) -> tuple[CronScheduler, Path, RecordingExecutor]:
    """Create a scheduler wired to injectable cron root and executor."""
    root = cron_root if cron_root is not None else make_cron_root(tmp_path)
    if yaml_content is not None:
        write_jobs_yaml(root, yaml_content)
    exec_cb = executor if executor is not None else RecordingExecutor()
    scheduler = CronScheduler(
        load_cron_config(tmp_path),
        override_cron_root=root,
        executor=exec_cb,
        reload_poll_hook=reload_poll_hook,
    )
    return scheduler, root, exec_cb
