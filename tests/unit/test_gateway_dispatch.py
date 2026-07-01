"""Unit tests for gateway inbound dispatch."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.base import InboundMessage, OutboundMessage
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    NoopCronScheduler,
    NullTextPool,
    SendSpyPool,
    _expected_injected_message,
    _wait_for_condition,
    _wait_for_memory_injected_metadata,
    gateway_config,
    memory_enabled_pool_factory,
    seed_session,
)
from tests.unit.test_memory_injection import SendCapturingFacade, _write_memory_files
from tests.unit.telegram_adapter_fakes import (
    INTEGRATION_CHAT_ID,
    private_message,
    registered_handler,
    telegram_gateway_runtime,
)


@pytest.fixture(autouse=True)
def _isolate_gateway_cron_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep gateway dispatch tests hermetic after cron startup wiring."""
    monkeypatch.setattr("cursor_agent.gateway.runner.CronScheduler", NoopCronScheduler)


async def test_dispatch_allowed_inbound_sends_assistant_reply(
    tmp_path: Path,
) -> None:
    """Allowed inbound dispatches through the pool and returns assistant text."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="hello from agent")
    session_key = "telegram:123456789:deadbeef"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="ping",
            )
        )
        await _wait_for_condition(
            lambda: len(adapter.outbound_messages) == 1,
            description="assistant reply outbound",
        )

    assert len(adapter.outbound_messages) == 1
    outbound = adapter.outbound_messages[0]
    assert outbound == OutboundMessage(
        platform="telegram",
        sender_id="123456789",
        session_key=session_key,
        text="hello from agent",
    )


async def test_dispatch_missing_session_does_not_auto_create_or_call_pool(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing session rows do not auto-create sessions or invoke the pool."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade()
    session_key = "telegram:123456789:missing"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        with (
            patch.object(ctx.store, "create", autospec=True) as mock_create,
            caplog.at_level(logging.WARNING, logger="cursor_agent.gateway.runner"),
        ):
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=session_key,
                    text="hello",
                )
            )
            await _wait_for_condition(
                lambda: any(
                    "no session row" in record.message and session_key in record.message
                    for record in caplog.records
                ),
                description="missing session warning log",
            )
            mock_create.assert_not_called()

        assert ctx.pool.send_calls == []
        assert adapter.outbound_messages == []


@pytest.mark.asyncio
async def test_dispatch_injects_memory_through_blocking_false_pool_send(
    tmp_path: Path,
) -> None:
    """Gateway dispatch injects memory through pool.send(..., blocking=False)."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv and pytest"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = SendCapturingFacade(default_reply="ok")
    session_key = "telegram:123456789:mem00001"
    db_path = tmp_path / "sessions.db"
    user_message = "what is the test command?"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=memory_enabled_pool_factory(memory_root),
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text=user_message,
            )
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1 and len(facade.send_calls) == 1,
            description="memory-injected pool send",
        )

    assert len(ctx.pool.send_calls) == 1
    assert ctx.pool.send_calls[0]["blocking"] is False
    assert ctx.pool.send_calls[0]["session_key"] == session_key
    assert ctx.pool.send_calls[0]["message"] == user_message
    expected = _expected_injected_message(
        user_text=user_text,
        memory_text=memory_text,
        user_message=user_message,
    )
    assert facade.send_calls[0]["message"] == expected


async def test_dispatch_uses_blocking_false_pool_send(tmp_path: Path) -> None:
    """Inbound dispatch calls pool.send with blocking=False."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="ok")
    session_key = "telegram:123456789:abc12345"
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
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="status",
            )
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1,
            description="pool send call",
        )

        assert len(ctx.pool.send_calls) == 1
        assert ctx.pool.send_calls[0]["blocking"] is False
        assert ctx.pool.send_calls[0]["session_key"] == session_key
        assert ctx.pool.send_calls[0]["message"] == "status"


@pytest.mark.asyncio
async def test_telegram_first_message_memory_injected_through_shared_send_path(
    tmp_path: Path,
) -> None:
    """Telegram /new followed by first free text injects memory once via pool.send."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv and pytest"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    user_message = "first question after /new"
    facade = SendCapturingFacade(default_reply="hello after first turn")

    async with telegram_gateway_runtime(
        tmp_path,
        facade=facade,
        pool_factory=memory_enabled_pool_factory(memory_root),
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, config):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)
        handler = await registered_handler(fake_dispatcher)
        await handler(private_message(chat_id=INTEGRATION_CHAT_ID, text="/new"))
        await handler(
            private_message(
                chat_id=INTEGRATION_CHAT_ID,
                text=user_message,
            ),
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1 and len(facade.send_calls) == 1,
            description="telegram first-message memory injection",
            attempts=50,
        )
        await _wait_for_memory_injected_metadata(ctx.store, session_key)

        expected = _expected_injected_message(
            user_text=user_text,
            memory_text=memory_text,
            user_message=user_message,
        )
        assert ctx.pool.send_calls[0]["blocking"] is False
        assert ctx.pool.send_calls[0]["session_key"] == session_key
        assert ctx.pool.send_calls[0]["message"] == user_message
        assert facade.send_calls[0]["message"] == expected

        row = await ctx.store.resolve(session_key)
        assert row is not None
        assert row.metadata.get("memory_injected") is True

    reply_calls = [
        call
        for call in fake_bot.send_message_calls
        if call.get("text") == "hello after first turn"
    ]
    assert len(reply_calls) == 1


async def test_dispatch_skips_outbound_when_pool_returns_none_text(
    tmp_path: Path,
) -> None:
    """Successful pool runs without assistant text must not send an empty reply."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade()
    session_key = "telegram:123456789:nulltext"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=NullTextPool,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        pool = ctx.pool
        assert isinstance(pool, NullTextPool)
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="ping",
            )
        )
        await _wait_for_condition(
            lambda: pool.send_completed.is_set(),
            description="null-text pool send completed",
        )

    assert adapter.outbound_messages == []
