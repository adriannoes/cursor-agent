"""Unit tests for gateway cron scheduler wiring at startup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cursor_agent.cron.executor import CronJobRunOutcome, CronRunStatus
from cursor_agent.cron.models import CronJob
from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import FakePlatformAdapter, gateway_config
from tests.unit.telegram_adapter_fakes import make_adapter


async def test_gateway_runtime_starts_and_stops_cron_scheduler(
    tmp_path: Path,
) -> None:
    """Gateway starts cron scheduler after pool is ready and stops on shutdown."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"
    lifecycle: list[str] = []

    class RecordingCronScheduler:
        """Records cron scheduler lifecycle for gateway wiring assertions."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            lifecycle.append("cron_init")

        def set_shutting_down_check(self, _check: object) -> None:
            return None

        def pause_scheduling(self) -> None:
            return None

        async def start(self) -> None:
            lifecycle.append("cron_start")

        async def shutdown(self, *, timeout: float | None = None) -> None:
            _ = timeout
            lifecycle.append("cron_shutdown")

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.CronScheduler",
            RecordingCronScheduler,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ):
            assert lifecycle == ["cron_init", "cron_start"]
            assert adapter.started is True

    assert lifecycle == ["cron_init", "cron_start", "cron_shutdown"]


async def test_gateway_runtime_wires_cron_timeout_handler(
    tmp_path: Path,
) -> None:
    """Gateway startup passes a timeout handler to CronScheduler for observability."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"
    captured: dict[str, object] = {}

    class CapturingCronScheduler:
        """Captures cron scheduler kwargs passed by gateway startup."""

        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured["on_run_timeout"] = kwargs.get("on_run_timeout")

        def set_shutting_down_check(self, _check: object) -> None:
            return None

        def pause_scheduling(self) -> None:
            return None

        async def start(self) -> None:
            return None

        async def shutdown(self, *, timeout: float | None = None) -> None:
            _ = timeout
            return None

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.CronScheduler",
            CapturingCronScheduler,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ):
            assert callable(captured.get("on_run_timeout"))


async def test_gateway_runtime_cron_executor_calls_run_cron_job(
    tmp_path: Path,
) -> None:
    """Cron scheduler executor delegates to run_cron_job with shared handles."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"
    captured_executor: dict[str, object] = {"callback": None}

    class CapturingCronScheduler:
        """Captures the executor callback passed by gateway startup."""

        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured_executor["callback"] = kwargs.get("executor")

        def set_shutting_down_check(self, _check: object) -> None:
            return None

        def pause_scheduling(self) -> None:
            return None

        async def start(self) -> None:
            return None

        async def shutdown(self, *, timeout: float | None = None) -> None:
            _ = timeout
            return None

    job = CronJob.model_validate(
        {
            "id": "gateway-wired-job",
            "schedule": "0 9 * * *",
            "prompt": "Run from gateway cron wiring.",
        }
    )

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.CronScheduler",
            CapturingCronScheduler,
        ),
        patch("cursor_agent.gateway.runner.run_cron_job") as mock_run_cron_job,
    ):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ) as ctx:
            executor = captured_executor["callback"]
            assert callable(executor)
            await executor(job)  # type: ignore[misc]

    mock_run_cron_job.assert_called_once_with(
        job,
        pool=ctx.pool,
        store=ctx.store,
        facade=ctx.facade,
        config=ctx.config,
    )


async def test_gateway_cron_executor_calls_deliver_cron_result_after_run(
    tmp_path: Path,
) -> None:
    """Gateway cron executor delivers finished outcomes when Telegram is configured."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"
    captured_executor: dict[str, object] = {"callback": None}

    class CapturingCronScheduler:
        """Captures the executor callback passed by gateway startup."""

        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured_executor["callback"] = kwargs.get("executor")

        def set_shutting_down_check(self, _check: object) -> None:
            return None

        def pause_scheduling(self) -> None:
            return None

        async def start(self) -> None:
            return None

        async def shutdown(self, *, timeout: float | None = None) -> None:
            _ = timeout
            return None

    job = CronJob.model_validate(
        {
            "id": "telegram-delivery-job",
            "schedule": "0 9 * * *",
            "prompt": "Report status.",
            "delivery": {"telegram": {"chat_id": "123456789"}},
        }
    )
    finished_outcome = CronJobRunOutcome(
        job_id=job.id,
        run_id="run-delivery",
        session_id="session-1",
        session_key="cron:telegram-delivery-job:run-delivery",
        status=CronRunStatus.FINISHED,
        result_text="**Done**",
    )

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.CronScheduler",
            CapturingCronScheduler,
        ),
        patch(
            "cursor_agent.gateway.runner.run_cron_job",
            return_value=finished_outcome,
        ) as mock_run_cron_job,
        patch(
            "cursor_agent.gateway.runner.deliver_cron_result",
        ) as mock_deliver_cron_result,
    ):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ):
            executor = captured_executor["callback"]
            assert callable(executor)
            await executor(job)  # type: ignore[misc]

    mock_run_cron_job.assert_called_once()
    mock_deliver_cron_result.assert_called_once_with(
        job,
        finished_outcome,
        chunk_sender=None,
        logger=mock_deliver_cron_result.call_args.kwargs["logger"],
    )


async def test_gateway_cron_executor_end_to_end_telegram_html_delivery(
    tmp_path: Path,
) -> None:
    """Finished cron jobs with Telegram delivery send HTML chunks via the gateway."""
    config = gateway_config()
    telegram_adapter, fake_bot, _fake_dispatcher = make_adapter(tmp_path)
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"
    captured_executor: dict[str, object] = {"callback": None}

    class CapturingCronScheduler:
        """Captures the executor callback passed by gateway startup."""

        def __init__(self, *_args: object, **kwargs: object) -> None:
            captured_executor["callback"] = kwargs.get("executor")

        def set_shutting_down_check(self, _check: object) -> None:
            return None

        def pause_scheduling(self) -> None:
            return None

        async def start(self) -> None:
            return None

        async def shutdown(self, *, timeout: float | None = None) -> None:
            _ = timeout
            return None

    job = CronJob.model_validate(
        {
            "id": "gateway-telegram-delivery",
            "schedule": "0 9 * * *",
            "prompt": "Summarize status.",
            "delivery": {"telegram": {"chat_id": "444555666"}},
        }
    )
    finished_outcome = CronJobRunOutcome(
        job_id=job.id,
        run_id="run-html",
        session_id="session-2",
        session_key="cron:gateway-telegram-delivery:run-html",
        status=CronRunStatus.FINISHED,
        result_text="**Daily report** complete.",
    )

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.CronScheduler",
            CapturingCronScheduler,
        ),
        patch(
            "cursor_agent.gateway.runner.run_cron_job",
            return_value=finished_outcome,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[telegram_adapter],
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ):
            executor = captured_executor["callback"]
            assert callable(executor)
            await executor(job)  # type: ignore[misc]

    assert len(fake_bot.send_message_calls) == 1
    sent = fake_bot.send_message_calls[0]
    assert sent["chat_id"] == 444555666
    assert sent["parse_mode"] == "HTML"
    assert sent["text"] == "<b>Daily report</b> complete."
    assert "**Daily report**" not in str(sent["text"])
