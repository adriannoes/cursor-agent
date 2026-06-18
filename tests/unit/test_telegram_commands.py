"""Unit tests for TelegramAdapter slash commands and first-contact UX (PRD-007 Wave 5)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import (
    gateway_config,
    seed_session_with_agent,
    track_inbound,
)
from tests.unit.test_telegram_adapter import (
    FakeBot,
    FakeChat,
    FakeDispatcher,
    FakeMessage,
    FakeUser,
    _registered_handler,
)

ALLOWED_USER_ID = 123456789
BLOCKED_USER_ID = 999888777
DEFAULT_CHAT_ID = 444555666
OTHER_CHAT_ID = 777888999
DEFAULT_WORKSPACE = "/tmp/gateway-workspace"


class CreateAgentTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records create_agent keyword arguments."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.create_agent_calls: list[dict[str, Any]] = []

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        self.create_agent_calls.append(
            {
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
                "runtime_mode": runtime_mode,
            },
        )
        return await super().create_agent(
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )


class CancelTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records cancel invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.cancel_calls: list[str] = []

    async def cancel(self, agent_id: str) -> None:
        self.cancel_calls.append(agent_id)
        await super().cancel(agent_id)


def _command_message(
    text: str,
    *,
    chat_id: int = DEFAULT_CHAT_ID,
    user_id: int = ALLOWED_USER_ID,
) -> FakeMessage:
    return FakeMessage(
        message_id=1,
        chat=FakeChat(id=chat_id, type="private"),
        from_user=FakeUser(id=user_id),
        text=text,
    )


def _runtime_handles(
    tmp_path: object,
    *,
    facade: FakeSdkFacade | None = None,
    workspace: str = DEFAULT_WORKSPACE,
    allowed_users: list[int] | None = None,
) -> dict[str, object]:
    gateway_cfg = gateway_config(
        workspace=workspace,
        allowed_users=allowed_users if allowed_users is not None else [ALLOWED_USER_ID],
    )
    cursor_cfg = CursorAgentConfig.model_validate(
        {
            "model": "composer-2.5",
            "tool_profile": "messaging",
            "runtime": {
                "mode": "local",
                "local": {"cwd": workspace, "setting_sources": ["project", "user"]},
            },
        },
    )
    sdk_facade = facade or FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")  # type: ignore[operator]

    return {
        "platform_config": gateway_cfg.platforms.telegram.model_copy(
            update={"bot_token": "bot123456:ABCdef-secret-token"},
        ),
        "gateway_config": gateway_cfg,
        "config": cursor_cfg,
        "store": store,
        "facade": sdk_facade,
        "logger": logging.getLogger("test.telegram.commands"),
    }


def _make_command_adapter(
    tmp_path: object,
    *,
    facade: FakeSdkFacade | None = None,
    workspace: str = DEFAULT_WORKSPACE,
    allowed_users: list[int] | None = None,
    bot: FakeBot | None = None,
    dispatcher: FakeDispatcher | None = None,
) -> tuple[TelegramAdapter, FakeBot, FakeDispatcher, dict[str, object]]:
    handles = _runtime_handles(
        tmp_path,
        facade=facade,
        workspace=workspace,
        allowed_users=allowed_users,
    )
    fake_bot = bot or FakeBot(token="bot123456:ABCdef-secret-token")
    fake_dispatcher = dispatcher or FakeDispatcher()

    def bot_factory(token: str) -> FakeBot:
        fake_bot.token = token
        return fake_bot

    def dispatcher_factory() -> FakeDispatcher:
        return fake_dispatcher

    adapter = TelegramAdapter(
        **handles,  # type: ignore[arg-type]
        bot_factory=bot_factory,
        dispatcher_factory=dispatcher_factory,
    )
    return adapter, fake_bot, fake_dispatcher, handles


async def _init_store(handles: dict[str, object]) -> SessionStore:
    store = handles["store"]
    assert isinstance(store, SessionStore)
    await store.initialize()
    return store


async def _start_adapter(
    adapter: TelegramAdapter,
    handles: dict[str, object],
    on_inbound: Callable[[InboundMessage], Awaitable[None]],
) -> None:
    await _init_store(handles)
    await adapter.start(on_inbound)


async def _seed_chat_session(
    handles: dict[str, object],
    *,
    chat_id: int = DEFAULT_CHAT_ID,
    workspace: str = DEFAULT_WORKSPACE,
) -> tuple[str, str]:
    store = await _init_store(handles)
    facade = handles["facade"]
    assert isinstance(facade, FakeSdkFacade)
    session_key = telegram_session_key(chat_id, workspace)
    return await seed_session_with_agent(
        store,
        facade,
        session_key,
        workspace=workspace,
        tool_profile="messaging",
    )


# --- /new (sub-tasks 4.1, 4.2) ---


@pytest.mark.asyncio
async def test_telegram_new_creates_session_row_and_agent(tmp_path: object) -> None:
    """Allowlisted /new creates a session row and calls facade.create_agent."""
    facade = CreateAgentTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(
        tmp_path,
        facade=facade,
    )
    received: list[InboundMessage] = []
    await _start_adapter(adapter, handles, track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/new"))

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
async def test_telegram_new_sends_confirmation_copy(tmp_path: object) -> None:
    """Allowlisted /new sends concise confirmation copy to the chat."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _start_adapter(adapter, handles, track_inbound([]))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/new"))

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
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(
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

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/new"))

    latest = await store.resolve(session_key)
    assert latest is not None
    assert latest.id != first_id
    assert len(await store.list(session_key)) == 2
    assert facade.create_agent_calls
    assert len(fake_bot.send_message_calls) >= 1
    _ = first_agent
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_new_does_not_affect_other_chat_session_key(
    tmp_path: object,
) -> None:
    """/new on one chat must not change the active session for another chat."""
    adapter, _, fake_dispatcher, handles = _make_command_adapter(tmp_path)
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

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/new", chat_id=DEFAULT_CHAT_ID))

    other_latest = await store.resolve(other_key)
    assert other_latest is not None
    assert other_latest.id == other_id
    await adapter.stop()


# --- /stop (sub-tasks 4.3, 4.4) ---


@pytest.mark.asyncio
async def test_telegram_stop_cancels_latest_session_agent(tmp_path: object) -> None:
    """Allowlisted /stop cancels the latest session agent for the chat."""
    facade = CancelTrackingFacade()
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(
        tmp_path,
        facade=facade,
    )
    _session_id, agent_id = await _seed_chat_session(handles)

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/stop"))

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
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(
        tmp_path,
        facade=facade,
    )

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/stop"))

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
    adapter, _, fake_dispatcher, handles = _make_command_adapter(
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

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/stop", chat_id=DEFAULT_CHAT_ID))

    assert facade.cancel_calls == []
    await adapter.stop()
    _ = other_agent


# --- /help (sub-tasks 4.5, 4.6) ---


@pytest.mark.asyncio
async def test_telegram_help_lists_supported_commands(tmp_path: object) -> None:
    """Allowlisted /help lists /new, /stop, and /help."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _start_adapter(adapter, handles, track_inbound([]))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/help"))

    assert fake_bot.send_message_calls
    body = str(fake_bot.send_message_calls[0]["text"])
    assert "/new" in body
    assert "/stop" in body
    assert "/help" in body
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_help_mentions_new_starts_or_resets_context(
    tmp_path: object,
) -> None:
    """/help explains that /new starts or resets chat context."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _start_adapter(adapter, handles, track_inbound([]))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/help"))

    body = str(fake_bot.send_message_calls[0]["text"]).lower()
    assert "/new" in body
    assert "start" in body or "reset" in body or "new conversation" in body
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_help_omits_unsupported_cli_commands(tmp_path: object) -> None:
    """Telegram /help must not advertise unsupported CLI-only commands."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _start_adapter(adapter, handles, track_inbound([]))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/help"))

    body = str(fake_bot.send_message_calls[0]["text"])
    for unsupported in ("/compress", "/model", "/retry", "/usage"):
        assert unsupported not in body
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_start_with_existing_session_sends_onboarding_hint(
    tmp_path: object,
) -> None:
    """Telegram's automatic /start command must not be forwarded to the agent."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _seed_chat_session(handles)
    received: list[InboundMessage] = []
    await _start_adapter(adapter, handles, track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/start"))

    assert received == []
    assert fake_bot.send_message_calls
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
    await adapter.stop()


# --- First-contact and allowlist (sub-tasks 4.7, 4.8) ---


@pytest.mark.asyncio
async def test_telegram_free_text_without_session_sends_hint(tmp_path: object) -> None:
    """Allowlisted free text without a session sends TELEGRAM_NO_SESSION_HINT."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    received: list[InboundMessage] = []
    await _start_adapter(adapter, handles, track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("hello there"))

    assert fake_bot.send_message_calls
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_free_text_with_session_calls_on_inbound(
    tmp_path: object,
) -> None:
    """Allowlisted free text with an existing session forwards to on_inbound."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _seed_chat_session(handles)
    received: list[InboundMessage] = []
    await _start_adapter(adapter, handles, track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("continue chatting"))

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
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    received: list[InboundMessage] = []
    await _start_adapter(adapter, handles, track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(
        _command_message("hello blocked", user_id=BLOCKED_USER_ID),
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
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(
        tmp_path,
        facade=facade,
    )
    store = handles["store"]
    assert isinstance(store, SessionStore)

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/new", user_id=BLOCKED_USER_ID))

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
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(
        tmp_path,
        facade=facade,
    )
    await _seed_chat_session(handles)

    await _start_adapter(adapter, handles, track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/stop", user_id=BLOCKED_USER_ID))

    assert facade.cancel_calls == []
    assert fake_bot.send_message_calls == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_blocked_user_help_receives_no_reply(tmp_path: object) -> None:
    """Blocked /help must not send help copy."""
    adapter, fake_bot, fake_dispatcher, handles = _make_command_adapter(tmp_path)
    await _start_adapter(adapter, handles, track_inbound([]))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_command_message("/help", user_id=BLOCKED_USER_ID))

    assert fake_bot.send_message_calls == []
    await adapter.stop()
