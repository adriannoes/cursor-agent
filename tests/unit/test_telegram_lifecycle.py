"""Unit tests for TelegramAdapter lifecycle, inbound mapping, typing, and logging."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.telegram_chunking import telegram_session_key

from tests.unit.gateway_fakes import track_inbound
from tests.unit.telegram_adapter_fakes import (
    ALLOWED_USER_ID,
    FakeChat,
    FakeMessage,
    FakeUser,
    make_adapter,
    private_message,
    registered_handler,
    seed_inbound_session,
)


@pytest.mark.asyncio
async def test_telegram_adapter_start_registers_handler_and_polling_task(
    tmp_path: object,
) -> None:
    """start() registers handlers and begins long polling without blocking."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []

    await adapter.start(track_inbound(received))
    await asyncio.sleep(0)

    assert fake_dispatcher.message.handlers
    assert fake_dispatcher.polling_started is True
    assert fake_dispatcher.polling_bot is fake_bot
    assert fake_dispatcher.polling_kwargs.get("handle_signals") is False

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_adapter_stop_closes_dispatcher_and_bot_session(
    tmp_path: object,
) -> None:
    """stop() stops polling, cancels the polling task, and closes the bot session."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    await adapter.start(track_inbound([]))

    await adapter.stop()

    assert fake_dispatcher.polling_stopped is True
    assert fake_bot.session.closed is True


@pytest.mark.asyncio
async def test_telegram_inbound_direct_text_maps_to_inbound_message(
    tmp_path: object,
) -> None:
    """Direct private text messages call on_inbound with normalized fields."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await seed_inbound_session(adapter)
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(text="ping"))

    assert len(received) == 1
    assert received[0].platform == "telegram"
    assert received[0].text == "ping"

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_sender_id_uses_user_not_chat_id(
    tmp_path: object,
) -> None:
    """sender_id must be Telegram user ID as a decimal string, not chat ID."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await seed_inbound_session(adapter, chat_id=999888777)
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(
        private_message(chat_id=999888777, user_id=ALLOWED_USER_ID, text="hi")
    )

    assert received[0].sender_id == str(ALLOWED_USER_ID)
    assert received[0].sender_id != "999888777"

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_session_key_uses_chat_id_and_workspace_hash(
    tmp_path: object,
) -> None:
    """session_key uses telegram:{chat_id}:{workspace_hash} from resolved workspace."""
    workspace = "/tmp/gateway-workspace"
    adapter, _, fake_dispatcher = make_adapter(tmp_path, workspace=workspace)
    received: list[InboundMessage] = []
    chat_id = 444555666
    await seed_inbound_session(adapter, chat_id=chat_id, workspace=workspace)
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(chat_id=chat_id, text="workspace key"))

    expected_key = telegram_session_key(chat_id, workspace)
    assert received[0].session_key == expected_key

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_empty_text(tmp_path: object) -> None:
    """Whitespace-only text must not call on_inbound."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(text="   "))

    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_non_text_messages(tmp_path: object) -> None:
    """Messages without text must be ignored safely."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(
        FakeMessage(
            message_id=2,
            chat=FakeChat(id=1, type="private"),
            from_user=FakeUser(id=2),
            text=None,
        ),
    )

    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_group_messages(tmp_path: object) -> None:
    """Group and supergroup chats are out of scope and must be ignored."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    for chat_type in ("group", "supergroup", "channel"):
        await handler(
            FakeMessage(
                message_id=3,
                chat=FakeChat(id=100, type=chat_type),
                from_user=FakeUser(id=200),
                text="group hello",
            ),
        )

    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_topic_messages(tmp_path: object) -> None:
    """Forum topic messages must be ignored in MVP."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(
        FakeMessage(
            message_id=4,
            chat=FakeChat(id=10, type="private"),
            from_user=FakeUser(id=20),
            text="topic hello",
            message_thread_id=99,
            is_topic_message=True,
        ),
    )

    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_messages_without_user(tmp_path: object) -> None:
    """Messages with no from_user are ignored before on_inbound."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(
        FakeMessage(
            message_id=7,
            chat=FakeChat(id=10, type="private"),
            from_user=None,
            text="no user attached",
        ),
    )

    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_typing_starts_during_inbound_processing(
    tmp_path: object,
) -> None:
    """Typing action is sent while on_inbound is active."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    release = asyncio.Event()

    async def slow_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await seed_inbound_session(adapter)
    await adapter.start(slow_on_inbound)
    handler = await registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(private_message(text="typing please")))
    for _ in range(50):
        if fake_bot.chat_action_calls:
            break
        await asyncio.sleep(0.01)

    assert fake_bot.chat_action_calls
    assert fake_bot.chat_action_calls[0]["action"] == "typing"

    release.set()
    await task
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_typing_refreshes_with_injected_sleeper(
    tmp_path: object,
) -> None:
    """Typing loop refreshes near every five seconds using injected sleeper."""
    sleep_calls: list[float] = []

    async def fake_sleeper(seconds: float) -> None:
        sleep_calls.append(seconds)
        await asyncio.sleep(0)

    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path, sleeper=fake_sleeper)
    release = asyncio.Event()

    async def blocking_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await seed_inbound_session(adapter)
    await adapter.start(blocking_on_inbound)
    handler = await registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(private_message(text="refresh typing")))
    await asyncio.sleep(0.05)

    assert len(fake_bot.chat_action_calls) >= 1
    assert sleep_calls
    assert sleep_calls[0] == pytest.approx(5.0)

    release.set()
    await task
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_typing_stops_after_inbound_completion(
    tmp_path: object,
) -> None:
    """Typing tasks stop after handler completion without leaking."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await seed_inbound_session(adapter)
    await adapter.start(track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(text="done"))

    await asyncio.sleep(0)
    assert received
    assert adapter.active_typing_task_count() == 0
    assert fake_bot.chat_action_calls

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_typing_stops_on_shutdown(tmp_path: object) -> None:
    """stop() cancels in-flight typing tasks."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    release = asyncio.Event()

    async def blocking_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await seed_inbound_session(adapter)
    await adapter.start(blocking_on_inbound)
    handler = await registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(private_message(text="shutdown typing")))
    for _ in range(50):
        if fake_bot.chat_action_calls:
            break
        await asyncio.sleep(0.01)

    await adapter.stop()
    release.set()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert adapter.active_typing_task_count() == 0
    assert fake_bot.chat_action_calls


@pytest.mark.asyncio
async def test_telegram_typing_refresh_failure_logs_safe_metadata_only(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Typing refresh failures log exception class without leaking token or text."""
    secret_token = "bot555444:typing-secret-token"

    async def fast_sleeper(_seconds: float) -> None:
        await asyncio.sleep(0)

    adapter, fake_bot, fake_dispatcher = make_adapter(
        tmp_path,
        sleeper=fast_sleeper,
        bot_token=secret_token,
    )
    caplog.set_level(logging.ERROR, logger="test.telegram.adapter")
    chat_action_count = {"n": 0}

    async def flaky_chat_action(
        chat_id: int,
        action: str,
        **kwargs: object,
    ) -> object:
        chat_action_count["n"] += 1
        if chat_action_count["n"] >= 2:
            raise RuntimeError("typing api down")
        return {"ok": True}

    fake_bot.send_chat_action = flaky_chat_action  # type: ignore[method-assign]
    release = asyncio.Event()

    async def blocking_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await seed_inbound_session(adapter)
    await adapter.start(blocking_on_inbound)
    handler = await registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(private_message(text="typing failure")))

    for _ in range(50):
        if "telegram_typing_failed" in "\n".join(
            record.message for record in caplog.records
        ):
            break
        await asyncio.sleep(0.01)

    combined = "\n".join(record.message for record in caplog.records)
    assert "telegram_typing_failed" in combined
    assert "RuntimeError" in combined
    assert secret_token not in combined
    assert "typing failure" not in combined

    release.set()
    await task
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_typing_remains_adapter_owned_without_memory_progress_copy(
    tmp_path: object,
) -> None:
    """Typing feedback stays adapter-owned and does not emit memory-specific progress."""
    adapter, fake_bot, fake_dispatcher = make_adapter(tmp_path)
    release = asyncio.Event()

    async def slow_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await seed_inbound_session(adapter)
    await adapter.start(slow_on_inbound)
    handler = await registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(private_message(text="first turn after /new")))
    for _ in range(50):
        if fake_bot.chat_action_calls:
            break
        await asyncio.sleep(0.01)

    assert fake_bot.chat_action_calls
    assert fake_bot.chat_action_calls[0]["action"] == "typing"
    assert fake_bot.send_message_calls == []

    release.set()
    await task
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_logs_exclude_bot_token(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter logs must never include the configured bot token."""
    secret_token = "bot999888:super-secret-token-value"
    adapter, _, fake_dispatcher = make_adapter(tmp_path, bot_token=secret_token)
    caplog.set_level(logging.DEBUG, logger="test.telegram.adapter")

    await seed_inbound_session(adapter)
    await adapter.start(track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(text="hello"))
    await adapter.stop()

    combined = "\n".join(record.message for record in caplog.records)
    assert secret_token not in combined
    assert "super-secret-token-value" not in combined


@pytest.mark.asyncio
async def test_telegram_logs_exclude_message_text(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter logs must not include full inbound message bodies."""
    adapter, _, fake_dispatcher = make_adapter(tmp_path)
    caplog.set_level(logging.DEBUG, logger="test.telegram.adapter")
    secret_body = "super-secret-user-prompt-body-xyz"

    await seed_inbound_session(adapter)
    await adapter.start(track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(private_message(text=secret_body))
    await adapter.stop()

    combined = "\n".join(record.message for record in caplog.records)
    assert secret_body not in combined
