"""Unit tests for Telegram allowlist enforcement and integrated gateway auth flows."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cursor_agent.platforms.base import GATEWAY_BUSY_MESSAGE, InboundMessage
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import SendSpyPool, seed_session, track_inbound
from tests.unit.telegram_adapter_fakes import (
    BLOCKED_USER_ID,
    INTEGRATION_CHAT_ID,
    SideEffectTrackingFacade,
    make_adapter,
    private_message,
    registered_handler,
    telegram_gateway_runtime,
    wait_for_condition,
)


@pytest.mark.asyncio
async def test_allowlisted_telegram_flow_reaches_pool_and_delivers_reply(
    tmp_path: Path,
) -> None:
    """Allowlisted inbound with a session reaches pool.send(blocking=False) and replies."""
    reply_text = "hello from integrated agent"
    facade = FakeSdkFacade(default_reply=reply_text)

    async with telegram_gateway_runtime(
        tmp_path,
        facade=facade,
        pool_factory=SendSpyPool,
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, config):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )

        handler = await registered_handler(fake_dispatcher)
        await handler(
            private_message(
                chat_id=INTEGRATION_CHAT_ID,
                text="integrated ping",
            ),
        )
        await wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1,
            description="pool send for allowlisted telegram flow",
        )
        await wait_for_condition(
            lambda: any(
                str(call.get("text")) == reply_text
                for call in fake_bot.send_message_calls
            ),
            description="telegram outbound assistant reply",
        )

    assert len(ctx.pool.send_calls) == 1
    assert ctx.pool.send_calls[0]["blocking"] is False
    assert ctx.pool.send_calls[0]["message"] == "integrated ping"
    assert ctx.pool.send_calls[0]["session_key"] == session_key
    reply_calls = [
        call for call in fake_bot.send_message_calls if call.get("text") == reply_text
    ]
    assert len(reply_calls) == 1


@pytest.mark.asyncio
async def test_blocked_telegram_sender_integration_no_reply_or_side_effects(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Blocked Telegram sender creates no sessions, pool sends, facade calls, or replies."""
    facade = SideEffectTrackingFacade()
    caplog.set_level(logging.INFO, logger="cursor_agent.gateway.runner")

    async with telegram_gateway_runtime(
        tmp_path,
        facade=facade,
        pool_factory=SendSpyPool,
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, config):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)

        handler = await registered_handler(fake_dispatcher)
        await handler(
            private_message(
                chat_id=INTEGRATION_CHAT_ID,
                user_id=BLOCKED_USER_ID,
                text="blocked integration attempt",
            ),
        )
        await asyncio.sleep(0.05)

        assert await ctx.store.resolve(session_key) is None
        assert ctx.pool.send_calls == []
        assert facade.create_agent_calls == []
        assert facade.send_calls == []
        assert fake_bot.send_message_calls == []

    combined_logs = "\n".join(record.message for record in caplog.records)
    assert '"event":"gateway_auth_blocked"' in combined_logs
    assert str(BLOCKED_USER_ID) in combined_logs
    assert session_key in combined_logs
    assert "blocked integration attempt" not in combined_logs


@pytest.mark.asyncio
async def test_telegram_busy_path_delivers_gateway_busy_message(
    tmp_path: Path,
) -> None:
    """AgentBusyError from the pool delivers canonical GATEWAY_BUSY_MESSAGE via Telegram."""
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="agent finished")

    async with telegram_gateway_runtime(tmp_path, facade=facade) as (
        ctx,
        _adapter,
        fake_bot,
        fake_dispatcher,
        config,
    ):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )

        handler = await registered_handler(fake_dispatcher)
        first_task = asyncio.create_task(
            handler(
                private_message(
                    chat_id=INTEGRATION_CHAT_ID,
                    text="first in-flight message",
                ),
            ),
        )
        await facade.send_in_progress.wait()

        await handler(
            private_message(
                chat_id=INTEGRATION_CHAT_ID,
                text="second busy message",
            ),
        )
        await wait_for_condition(
            lambda: any(
                call.get("text") == GATEWAY_BUSY_MESSAGE
                for call in fake_bot.send_message_calls
            ),
            description="telegram busy outbound message",
        )

        send_release.set()
        await first_task
        await wait_for_condition(
            lambda: any(
                str(call.get("text")) == "agent finished"
                for call in fake_bot.send_message_calls
            ),
            description="telegram assistant reply after busy path",
        )

    busy_calls = [
        call
        for call in fake_bot.send_message_calls
        if call.get("text") == GATEWAY_BUSY_MESSAGE
    ]
    assert len(busy_calls) == 1


@pytest.mark.asyncio
async def test_telegram_unsupported_command_is_treated_as_free_text(
    tmp_path: object,
) -> None:
    """An unknown slash command falls through to the free-text no-session hint."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter._store.initialize()
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(text="/unknowncommand please"))

    assert received == []
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
