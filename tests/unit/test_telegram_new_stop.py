"""Unit tests for Telegram /new and /stop slash commands (PRD-007)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import seed_session_with_agent, track_inbound
from tests.unit.telegram_adapter_fakes import registered_handler
from tests.unit.telegram_command_fakes import (
    DEFAULT_CHAT_ID,
    DEFAULT_WORKSPACE,
    OTHER_CHAT_ID,
    CancelTrackingFacade,
    CreateAgentTrackingFacade,
    command_message,
    make_command_adapter,
    seed_chat_session,
    start_command_adapter,
)


@pytest.mark.asyncio
async def test_telegram_new_creates_session_row_and_agent(tmp_path: object) -> None:
    """Allowlisted /new creates a session row and calls facade.create_agent."""
    facade = CreateAgentTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new"))

    store = handles["store"]
    assert isinstance(store, SessionStore)
    session_key = telegram_session_key(DEFAULT_CHAT_ID, DEFAULT_WORKSPACE)
    row = await store.resolve(session_key)
    assert row is not None
    assert facade.create_agent_calls
    assert facade.create_agent_calls[0]["tool_profile"] == "messaging"
    assert facade.create_agent_calls[0]["workspace"] == str(
        Path(DEFAULT_WORKSPACE).resolve(),
    )
    assert fake_bot.send_message_calls
    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_cancels_superseded_agent(tmp_path: object) -> None:
    """A second /new cancels the prior agent to avoid leaking SDK agents."""
    facade = CancelTrackingFacade()
    adapter, _fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    _record_id, old_agent_id = await seed_chat_session(handles)
    await adapter.start(track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new"))

    assert facade.cancel_calls == [old_agent_id]
    store = handles["store"]
    assert isinstance(store, SessionStore)
    row = await store.resolve(telegram_session_key(DEFAULT_CHAT_ID, DEFAULT_WORKSPACE))
    assert row is not None
    assert row.agent_id != old_agent_id
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_without_previous_session_does_not_cancel(
    tmp_path: object,
) -> None:
    """First /new for a chat has no prior agent to cancel."""
    facade = CancelTrackingFacade()
    adapter, _fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    await start_command_adapter(adapter, handles, track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new"))

    assert facade.cancel_calls == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_sends_confirmation_copy(tmp_path: object) -> None:
    """Allowlisted /new sends concise confirmation copy to the chat."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await start_command_adapter(adapter, handles, track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new"))

    assert fake_bot.send_message_calls
    confirmation = str(fake_bot.send_message_calls[0]["text"])
    assert confirmation
    assert "session" in confirmation.lower() or "conversation" in confirmation.lower()
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_resets_chat_by_creating_latest_row(
    tmp_path: object,
) -> None:
    """A second /new on the same chat makes the newest row active without deleting old rows."""
    facade = CreateAgentTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    store = handles["store"]
    assert isinstance(store, SessionStore)
    await store.initialize()
    session_key = telegram_session_key(DEFAULT_CHAT_ID, DEFAULT_WORKSPACE)
    first_id, first_agent = await seed_session_with_agent(
        store,
        facade,
        session_key,
        workspace=DEFAULT_WORKSPACE,
    )

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new"))

    latest = await store.resolve(session_key)
    assert latest is not None
    assert latest.id != first_id
    assert len(await store.list(session_key)) == 2
    assert facade.create_agent_calls
    assert len(fake_bot.send_message_calls) >= 1
    _ = first_agent
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_reset_creates_row_eligible_for_memory_injection(
    tmp_path: object,
) -> None:
    """Second /new after memory_injected must create a fresh row eligible for injection."""
    facade = CreateAgentTrackingFacade()
    adapter, _fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    store = handles["store"]
    assert isinstance(store, SessionStore)
    await store.initialize()
    session_key = telegram_session_key(DEFAULT_CHAT_ID, DEFAULT_WORKSPACE)
    first_agent_id = await facade.create_agent(
        workspace=DEFAULT_WORKSPACE,
        tool_profile="messaging",
    )
    first_row = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=first_agent_id,
            workspace=DEFAULT_WORKSPACE,
            runtime="local",
            tool_profile="messaging",
            metadata={"memory_injected": True},
        ),
    )

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new"))

    latest = await store.resolve(session_key)
    assert latest is not None
    assert latest.id != first_row.id
    assert latest.metadata.get("memory_injected") is not True
    assert len(await store.list(session_key)) == 2
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_does_not_affect_other_chat_session_key(
    tmp_path: object,
) -> None:
    """/new on one chat must not change the active session for another chat."""
    adapter, _, fake_dispatcher, handles = make_command_adapter(tmp_path)
    store = handles["store"]
    assert isinstance(store, SessionStore)
    await store.initialize()
    other_key = telegram_session_key(OTHER_CHAT_ID, DEFAULT_WORKSPACE)
    other_id, _ = await seed_session_with_agent(
        store,
        handles["facade"],  # type: ignore[arg-type]
        other_key,
        workspace=DEFAULT_WORKSPACE,
    )

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/new", chat_id=DEFAULT_CHAT_ID))

    other_latest = await store.resolve(other_key)
    assert other_latest is not None
    assert other_latest.id == other_id
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_stop_cancels_latest_session_agent(tmp_path: object) -> None:
    """Allowlisted /stop cancels the latest session agent for the chat."""
    facade = CancelTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    _session_id, agent_id = await seed_chat_session(handles)

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/stop"))

    assert facade.cancel_calls == [agent_id]
    assert fake_bot.send_message_calls
    success = str(fake_bot.send_message_calls[0]["text"]).lower()
    assert "cancel" in success
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_stop_without_session_sends_no_session_copy(
    tmp_path: object,
) -> None:
    """Allowlisted /stop without a session row sends clear no-session copy."""
    facade = CancelTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/stop"))

    assert facade.cancel_calls == []
    assert fake_bot.send_message_calls
    body = str(fake_bot.send_message_calls[0]["text"]).lower()
    assert "no" in body and "session" in body
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_stop_does_not_cancel_other_chat_session(
    tmp_path: object,
) -> None:
    """/stop on one chat must not cancel another chat's session agent."""
    facade = CancelTrackingFacade()
    adapter, _, fake_dispatcher, handles = make_command_adapter(
        tmp_path,
        facade=facade,
    )
    store = handles["store"]
    assert isinstance(store, SessionStore)
    await store.initialize()
    other_key = telegram_session_key(OTHER_CHAT_ID, DEFAULT_WORKSPACE)
    _other_id, other_agent = await seed_session_with_agent(
        store,
        facade,
        other_key,
        workspace=DEFAULT_WORKSPACE,
    )

    await start_command_adapter(adapter, handles, track_inbound([]))
    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/stop", chat_id=DEFAULT_CHAT_ID))

    assert facade.cancel_calls == []
    await adapter.stop()
    _ = other_agent
