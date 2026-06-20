"""Unit tests for cron scheduler behavior during gateway shutdown (ADR-021)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from cursor_agent.cron.executor import run_cron_job
from cursor_agent.cron.models import CronJob
from cursor_agent.cron.scheduler import CronScheduler
from cursor_agent.gateway.runner import gateway_runtime, resolve_gateway_startup_config
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    CancelTrackingFacade,
    FakePlatformAdapter,
    OrderTrackingCronScheduler,
    OrderTrackingStopAdapter,
    cron_root_for_tests,
    gateway_config,
    write_shutdown_cron_jobs_yaml,
)


async def test_shutdown_drains_cron_before_stopping_adapters(tmp_path: Path) -> None:
    """Cron drain (and its delivery) must complete before adapters are stopped."""
    config = gateway_config()
    events: list[str] = []
    adapter = OrderTrackingStopAdapter(events)
    facade = CancelTrackingFacade()
    scheduler = OrderTrackingCronScheduler(events)
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,  # type: ignore[arg-type]
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ):
            pass

    assert events == ["cron_drain", "adapter_stop"]


async def test_shutdown_cancels_cron_agent_when_job_force_cancelled(
    tmp_path: Path,
) -> None:
    """A force-cancelled cron job cancels its per-run SDK agent."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    send_release = asyncio.Event()
    facade = CancelTrackingFacade(send_release=send_release, default_reply="never")
    cron_root = cron_root_for_tests(tmp_path)
    write_shutdown_cron_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    handles: dict[str, object] = {}

    async def cron_executor(job: CronJob) -> None:
        await run_cron_job(
            job,
            pool=handles["pool"],  # type: ignore[arg-type]
            store=handles["store"],  # type: ignore[arg-type]
            facade=handles["facade"],  # type: ignore[arg-type]
            config=handles["config"],  # type: ignore[arg-type]
        )

    scheduler = CronScheduler(
        cursor_config,
        executor=cron_executor,
        override_cron_root=cron_root,
        reload_poll_hook=lambda: asyncio.sleep(3600),
    )
    db_path = tmp_path / "cancel-cron-sessions.db"
    cron_job = CronJob.model_validate(
        {
            "id": "shutdown-job",
            "schedule": "0 9 * * *",
            "prompt": "Shutdown cron job.",
        }
    )

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
            shutdown_timeout_seconds=0.01,
            register_signals=False,
        ) as ctx:
            handles.update(
                {
                    "pool": ctx.pool,
                    "store": ctx.store,
                    "facade": facade,
                    "config": ctx.config,
                }
            )
            cron_task = asyncio.create_task(scheduler._run_job(cron_job))
            await facade.send_in_progress.wait()
            await ctx.shutdown_coordinator.shutdown(ctx)
            await asyncio.sleep(0.02)
            assert cron_task.done()

    assert facade.cancel_calls, "expected the cron SDK agent to be cancelled"


async def test_shutdown_cancels_stuck_cron_job_on_timeout(tmp_path: Path) -> None:
    """In-flight cron jobs that exceed the shutdown timeout are force-cancelled."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="never finishes")
    cron_root = cron_root_for_tests(tmp_path)
    write_shutdown_cron_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    handles: dict[str, object] = {}

    async def cron_executor(job: CronJob) -> None:
        await run_cron_job(
            job,
            pool=handles["pool"],  # type: ignore[arg-type]
            store=handles["store"],  # type: ignore[arg-type]
            facade=handles["facade"],  # type: ignore[arg-type]
            config=handles["config"],  # type: ignore[arg-type]
        )

    scheduler = CronScheduler(
        cursor_config,
        executor=cron_executor,
        override_cron_root=cron_root,
        reload_poll_hook=lambda: asyncio.sleep(3600),
    )
    db_path = tmp_path / "shutdown-cron-sessions.db"
    cron_job = CronJob.model_validate(
        {
            "id": "shutdown-job",
            "schedule": "0 9 * * *",
            "prompt": "Shutdown cron job.",
        }
    )

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
            shutdown_timeout_seconds=0.01,
            register_signals=False,
        ) as ctx:
            handles.update(
                {
                    "pool": ctx.pool,
                    "store": ctx.store,
                    "facade": facade,
                    "config": ctx.config,
                }
            )
            cron_task = asyncio.create_task(scheduler._run_job(cron_job))
            await facade.send_in_progress.wait()
            exit_code = await ctx.shutdown_coordinator.shutdown(ctx)
            assert exit_code == 0
            await asyncio.sleep(0.02)
            assert cron_task.done()

    send_release.set()
