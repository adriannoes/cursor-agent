"""Unit tests for Telegram free-text routing and blocked-user handling (PRD-007)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import memory_enabled_pool_factory, track_inbound
from tests.unit.test_memory_injection import _write_memory_files
from tests.unit.telegram_adapter_fakes import (
    INTEGRATION_CHAT_ID,
    private_message,
    registered_handler,
    telegram_gateway_runtime,
)
from tests.unit.telegram_command_fakes import (
    BLOCKED_USER_ID,
    DEFAULT_CHAT_ID,
    DEFAULT_WORKSPACE,
    CancelTrackingFacade,
    CreateAgentTrackingFacade,
    command_message,
    make_command_adapter,
    seed_chat_session,
    start_command_adapter,
)


@pytest.mark.asyncio
async def test_telegram_free_text_without_session_sends_hint(tmp_path: object) -> None:
    """Allowlisted free text without a session sends TELEGRAM_NO_SESSION_HINT."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("hello there"))

    assert fake_bot.send_message_calls
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_no_session_free_text_with_memory_files_skips_pool(
    tmp_path: Path,
) -> None:
    """Free text without a session must not reach dispatch or pool when memory exists."""
    memory_root = tmp_path / "memory"
    _write_memory_files(
        memory_root,
        user_text="prefer concise answers",
        memory_text="project uses uv",
    )

    async with telegram_gateway_runtime(
        tmp_path,
        pool_factory=memory_enabled_pool_factory(memory_root),
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, _config):
        handler = await registered_handler(fake_dispatcher)
        await handler(private_message(chat_id=INTEGRATION_CHAT_ID, text="hello there"))
        await asyncio.sleep(0.05)

        assert ctx.pool.send_calls == []
        assert fake_bot.send_message_calls
        assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT


@pytest.mark.asyncio
async def test_telegram_free_text_with_session_calls_on_inbound(
    tmp_path: object,
) -> None:
    """Allowlisted free text with an existing session forwards to on_inbound."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await seed_chat_session(handles)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("continue chatting"))

    assert received
    assert received[0].text == "continue chatting"
    hint_calls = [
        call
        for call in fake_bot.send_message_calls
        if call.get("text") == TELEGRAM_NO_SESSION_HINT
    ]
    assert hint_calls == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_blocked_user_receives_no_reply_for_free_text(
    tmp_path: object,
) -> None:
    """Blocked users must not receive outbound replies for free text."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(
        command_message("hello blocked", user_id=BLOCKED_USER_ID),
    )

    assert fake_bot.send_message_calls == []
    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_blocked_user_new_does_not_create_session(
    tmp_path: object,
) -> None:
    """Blocked /new must not create sessions or call facade.create_agent."""
    facade = CreateAgentTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    store = handles["store"]
    assert isinstance(store, SessionStore)

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new", user_id=BLOCKED_USER_ID))

    session_key = telegram_session_key(DEFAULT_CHAT_ID, DEFAULT_WORKSPACE)
    assert await store.resolve(session_key) is None
    assert facade.create_agent_calls == []
    assert fake_bot.send_message_calls == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_blocked_user_stop_does_not_call_facade(
    tmp_path: object,
) -> None:
    """Blocked /stop must not call facade.cancel or send outbound copy."""
    facade = CancelTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    await seed_chat_session(handles)

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/stop", user_id=BLOCKED_USER_ID))

    assert facade.cancel_calls == []
    assert fake_bot.send_message_calls == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_blocked_user_help_receives_no_reply(tmp_path: object) -> None:
    """Blocked /help must not send help copy."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await start_command_adapter(adapter, handles, track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/help", user_id=BLOCKED_USER_ID))

    assert fake_bot.send_message_calls == []
    await adapter.stop()
