"""Unit tests for gateway dispatch and run_gateway during shutdown (ADR-021)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.gateway.context import GatewayContext
from cursor_agent.gateway.runner import gateway_runtime, run_gateway
from cursor_agent.platforms.base import InboundMessage
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    NoopCronScheduler,
    SendSpyPool,
    gateway_config,
    seed_session,
    write_gateway_yaml,
)


@pytest.fixture(autouse=True)
def _isolate_gateway_cron_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep gateway shutdown dispatch tests hermetic after cron startup wiring."""
    monkeypatch.setattr("cursor_agent.gateway.runner.CronScheduler", NoopCronScheduler)


async def test_dispatch_rejects_inbound_when_shutting_down(tmp_path: Path) -> None:
    """Inbound messages are ignored after the shutdown flag is set."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="should not send")
    session_key = "telegram:123456789:shutdown"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        ctx.shutting_down = True
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="late message",
            )
        )

        assert ctx.pool.send_calls == []
        assert adapter.outbound_messages == []


async def test_run_gateway_returns_zero_after_shutdown(tmp_path: Path) -> None:
    """run_gateway blocks until shutdown_complete and returns exit code 0."""
    import cursor_agent.gateway.runner as runner_module

    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file)
    entered = asyncio.Event()
    contexts: list[GatewayContext] = []
    original_runtime = runner_module.gateway_runtime

    @asynccontextmanager
    async def tracing_runtime(*args: object, **kwargs: object):
        kwargs.setdefault("adapters", [FakePlatformAdapter(platform="telegram")])
        kwargs.setdefault("facade", FakeSdkFacade())
        kwargs.setdefault("store_path", tmp_path / "run-gateway-sessions.db")
        async with original_runtime(*args, **kwargs) as ctx:
            contexts.append(ctx)
            entered.set()
            yield ctx

    with (
        patch.object(runner_module, "gateway_runtime", tracing_runtime),
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
    ):
        task = asyncio.create_task(run_gateway(config_path=config_file))
        await entered.wait()
        ctx = contexts[0]
        await ctx.shutdown_coordinator.shutdown(ctx)
        exit_code = await task

    assert exit_code == 0
    assert ctx.shutting_down is True
