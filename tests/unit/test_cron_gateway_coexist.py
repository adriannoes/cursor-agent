"""Gateway and cron coexistence tests (PRD-010 FR-9)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.cron.executor import CronRunStatus, run_cron_job
from cursor_agent.cron.models import JOBS_FILENAME, CronJob
from cursor_agent.cron.scheduler import CronScheduler
from cursor_agent.gateway.runner import gateway_runtime, resolve_gateway_startup_config
from cursor_agent.platforms.base import (
    GATEWAY_BUSY_MESSAGE,
    InboundMessage,
    OutboundMessage,
)
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    gateway_config,
    seed_session,
)


def _cron_root(tmp_path: Path) -> Path:
    root = tmp_path / "cron"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_jobs_yaml(cron_root: Path) -> None:
    (cron_root / JOBS_FILENAME).write_text(
        (
            "jobs:\n"
            "  - id: coexist-job\n"
            '    schedule: "0 9 * * *"\n'
            '    prompt: "Run coexistence cron job."\n'
        ),
        encoding="utf-8",
    )


def _coexist_cron_job() -> CronJob:
    return CronJob.model_validate(
        {
            "id": "coexist-job",
            "schedule": "0 9 * * *",
            "prompt": "Run coexistence cron job.",
        }
    )


async def _wait_for_condition(
    condition: object,
    *,
    description: str,
    attempts: int = 50,
) -> None:
    for _attempt in range(attempts):
        if callable(condition) and condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"condition did not become true: {description}")


@pytest.fixture
def cron_job() -> CronJob:
    return _coexist_cron_job()


async def test_gateway_context_exposes_cron_scheduler(tmp_path: Path) -> None:
    """GatewayContext carries the embedded cron scheduler for coordinated shutdown."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    scheduler = CronScheduler(
        cursor_config,
        override_cron_root=cron_root,
        reload_poll_hook=lambda: asyncio.sleep(3600),
    )
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
            register_signals=False,
        ) as ctx:
            assert ctx.cron_scheduler is scheduler


async def test_concurrent_gateway_dispatch_and_cron_job_complete_without_hang(
    tmp_path: Path,
    cron_job: CronJob,
) -> None:
    """Gateway inbound and cron execution on the shared pool both finish without deadlock."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="gateway reply")
    session_key = "telegram:123456789:coexist"
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    handles: dict[str, object] = {"cron_outcome": None}

    async def cron_executor(job: CronJob) -> None:
        handles["cron_outcome"] = await run_cron_job(
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
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
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
            await seed_session(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
                tool_profile="messaging",
            )

            dispatch_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="gateway message",
                    )
                )
            )
            await facade.send_in_progress.wait()

            cron_task = asyncio.create_task(scheduler._run_job(cron_job))
            await _wait_for_condition(
                lambda: facade.send_in_progress.is_set(),
                description="cron job reached facade send",
            )

            send_release.set()
            await asyncio.wait_for(
                asyncio.gather(dispatch_task, cron_task),
                timeout=1.0,
            )

    outcome = handles["cron_outcome"]
    assert outcome is not None
    assert outcome.status == CronRunStatus.FINISHED  # type: ignore[attr-defined]
    assert adapter.outbound_messages[-1].text == "gateway reply"


async def test_gateway_busy_and_cron_job_both_complete_on_shared_pool(
    tmp_path: Path,
    cron_job: CronJob,
) -> None:
    """ADR-008 busy rejection on gateway does not block a concurrent cron job."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="first reply")
    session_key = "telegram:123456789:busy-coexist"
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    handles: dict[str, object] = {"cron_outcome": None}

    async def cron_executor(job: CronJob) -> None:
        handles["cron_outcome"] = await run_cron_job(
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
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
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
            await seed_session(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
                tool_profile="messaging",
            )

            first_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="first message",
                    )
                )
            )
            await facade.send_in_progress.wait()

            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=session_key,
                    text="second message",
                )
            )
            await _wait_for_condition(
                lambda: len(adapter.outbound_messages) >= 1,
                description="busy outbound published",
            )

            cron_task = asyncio.create_task(scheduler._run_job(cron_job))
            send_release.set()
            await asyncio.wait_for(
                asyncio.gather(first_task, cron_task),
                timeout=1.0,
            )
            await _wait_for_condition(
                lambda: len(adapter.outbound_messages) >= 2,
                description="gateway reply published",
            )

    assert adapter.outbound_messages[0] == OutboundMessage(
        platform="telegram",
        sender_id="123456789",
        session_key=session_key,
        text=GATEWAY_BUSY_MESSAGE,
    )
    outcome = handles["cron_outcome"]
    assert outcome is not None
    assert outcome.status == CronRunStatus.FINISHED  # type: ignore[attr-defined]


async def test_shutdown_waits_for_in_flight_cron_job(tmp_path: Path) -> None:
    """Graceful shutdown awaits an in-flight cron job before closing the facade."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="cron reply")
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    handles: dict[str, object] = {
        "cron_finished": asyncio.Event(),
        "shutdown_started": asyncio.Event(),
    }

    async def cron_executor(job: CronJob) -> None:
        await run_cron_job(
            job,
            pool=handles["pool"],  # type: ignore[arg-type]
            store=handles["store"],  # type: ignore[arg-type]
            facade=handles["facade"],  # type: ignore[arg-type]
            config=handles["config"],  # type: ignore[arg-type]
        )
        handles["cron_finished"].set()  # type: ignore[union-attr]

    scheduler = CronScheduler(
        cursor_config,
        executor=cron_executor,
        override_cron_root=cron_root,
        reload_poll_hook=lambda: asyncio.sleep(3600),
    )
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
            shutdown_timeout_seconds=0.5,
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
            cron_task = asyncio.create_task(scheduler._run_job(_coexist_cron_job()))
            await facade.send_in_progress.wait()
            assert not handles["cron_finished"].is_set()  # type: ignore[union-attr]

            shutdown_task = asyncio.create_task(ctx.shutdown_coordinator.shutdown(ctx))
            handles["shutdown_started"].set()
            await asyncio.sleep(0.02)
            assert not facade._closed

            send_release.set()
            exit_code = await asyncio.wait_for(shutdown_task, timeout=1.0)
            await asyncio.wait_for(cron_task, timeout=1.0)

    assert exit_code == 0
    assert handles["cron_finished"].is_set()  # type: ignore[union-attr]
    assert facade._closed is True


async def test_shutdown_rejects_new_cron_triggers_while_shutting_down(
    tmp_path: Path,
) -> None:
    """Cron scheduler stops accepting new triggers once gateway shutdown begins."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade(default_reply="unused")
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root)
    cursor_config = resolve_gateway_startup_config(config)
    executor_calls: list[str] = []

    async def cron_executor(job: CronJob) -> None:
        executor_calls.append(job.id)

    scheduler = CronScheduler(
        cursor_config,
        executor=cron_executor,
        override_cron_root=cron_root,
        reload_poll_hook=lambda: asyncio.sleep(3600),
    )
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            cron_scheduler=scheduler,
            register_signals=False,
        ) as ctx:
            ctx.shutting_down = True
            await scheduler._run_job(_coexist_cron_job())

    assert executor_calls == []
