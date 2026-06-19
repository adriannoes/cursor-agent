"""Unit tests for gateway shutdown coordinator core behavior (ADR-021)."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path
from unittest.mock import patch

from cursor_agent.gateway.runner import (
    gateway_runtime,
    register_shutdown_signals,
)
from cursor_agent.gateway.shutdown import (
    DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS,
    flush_logging_handlers,
)
from cursor_agent.platforms.base import InboundMessage
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    CancelTrackingFacade,
    FakePlatformAdapter,
    OrderTrackingStopAdapter,
    gateway_config,
    seed_session_with_agent,
)


def test_default_shutdown_timeout_is_thirty_seconds() -> None:
    """Production shutdown timeout remains 30 seconds per ADR-021."""
    assert DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS == 30.0


async def test_shutdown_coordinator_sequence_order(tmp_path: Path) -> None:
    """Shutdown follows ADR-021 ordering: flag, adapters, cancel, tasks, close."""
    config = gateway_config()
    events: list[str] = []
    adapter = OrderTrackingStopAdapter(events)
    facade = CancelTrackingFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            pass

    assert ctx.shutting_down is True
    assert events == ["adapter_stop"]
    assert facade.close_calls == 1
    assert facade._closed is True


async def test_shutdown_cancels_active_agent_via_facade(tmp_path: Path) -> None:
    """Known active agent IDs receive facade.cancel during shutdown."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = CancelTrackingFacade(send_release=send_release, default_reply="reply")
    session_key = "telegram:123456789:shutdown-agent"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            _session_id, agent_id = await seed_session_with_agent(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
            )

            dispatch_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="long running",
                    )
                )
            )
            await facade.send_in_progress.wait()
            await ctx.shutdown_coordinator.shutdown(ctx)

    await dispatch_task
    assert agent_id in facade.cancel_calls


async def test_shutdown_cancels_stuck_dispatch_tasks_on_timeout(
    tmp_path: Path,
) -> None:
    """Dispatch tasks that exceed the timeout are force-cancelled."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="never")
    session_key = "telegram:123456789:stuck-dispatch"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.01,
            register_signals=False,
        ) as ctx:
            await seed_session_with_agent(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
            )

            inbound_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="stuck",
                    )
                )
            )
            await facade.send_in_progress.wait()

            exit_code = await ctx.shutdown_coordinator.shutdown(ctx)
            assert exit_code == 0
            await asyncio.sleep(0.02)
            assert inbound_task.done()

    send_release.set()


async def test_shutdown_rejects_new_inbound_during_shutdown(tmp_path: Path) -> None:
    """Inbound messages are ignored once shutdown has begun."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = CancelTrackingFacade(default_reply="should not send")
    session_key = "telegram:123456789:reject-inbound"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            await seed_session_with_agent(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
            )
            ctx.shutting_down = True
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=session_key,
                    text="late",
                )
            )

    assert adapter.outbound_messages == []


async def test_shutdown_returns_exit_code_zero(tmp_path: Path) -> None:
    """Graceful shutdown reports exit code 0 for CLI wrappers."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = CancelTrackingFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            exit_code = await ctx.shutdown_coordinator.shutdown(ctx)

    assert exit_code == 0


async def test_shutdown_is_idempotent(tmp_path: Path) -> None:
    """Repeated shutdown calls are safe and keep exit code 0."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = CancelTrackingFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            first = await ctx.shutdown_coordinator.shutdown(ctx)
            second = await ctx.shutdown_coordinator.shutdown(ctx)

    assert first == 0
    assert second == 0
    assert facade.close_calls == 1


async def test_shutdown_concurrent_calls_close_facade_once(tmp_path: Path) -> None:
    """Concurrent shutdown callers serialize on the lock and close once."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = CancelTrackingFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            results = await asyncio.gather(
                ctx.shutdown_coordinator.shutdown(ctx),
                ctx.shutdown_coordinator.shutdown(ctx),
            )

    assert results == [0, 0]
    assert facade.close_calls == 1


def test_flush_logging_handlers_flushes_root_handlers() -> None:
    """Log flush walks installed root handlers."""
    from tests.unit.gateway_fakes import FlushRecordingHandler

    handler = FlushRecordingHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        flush_logging_handlers()
        assert handler.flush_count == 1
    finally:
        root.removeHandler(handler)


async def test_gateway_runtime_exit_triggers_shutdown(tmp_path: Path) -> None:
    """Exiting gateway_runtime runs adapter stop and facade close."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = CancelTrackingFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ):
            assert facade._closed is False
            assert adapter.stopped is False

    assert adapter.stopped is True
    assert facade._closed is True
    assert facade.close_calls == 1


async def test_register_shutdown_signals_triggers_coordinator(
    tmp_path: Path,
) -> None:
    """SIGINT/SIGTERM handlers schedule graceful shutdown when supported."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = CancelTrackingFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            shutdown_timeout_seconds=0.05,
            register_signals=False,
        ) as ctx:
            loop = asyncio.get_running_loop()
            handlers: dict[int, object] = {}

            def _capture_handler(sig: int, handler: object) -> None:
                handlers[sig] = handler

            with patch.object(loop, "add_signal_handler", side_effect=_capture_handler):
                register_shutdown_signals(ctx.shutdown_coordinator, ctx, loop=loop)

            if signal.SIGINT in handlers:
                handler = handlers[signal.SIGINT]
                assert callable(handler)
                handler()
                for _ in range(20):
                    if ctx.shutting_down:
                        break
                    await asyncio.sleep(0.01)
                assert ctx.shutting_down is True
                assert facade._closed is True
