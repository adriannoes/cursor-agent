"""Shared fakes and helpers for Telegram slash-command unit tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import seed_session_with_agent
from tests.unit.telegram_adapter_fakes import (
    FakeBot,
    FakeChat,
    FakeDispatcher,
    FakeMessage,
    FakeUser,
    runtime_handles,
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
    """FakeSdkFacade that records cancel invocations for command tests."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.cancel_calls: list[str] = []

    async def cancel(self, agent_id: str) -> None:
        self.cancel_calls.append(agent_id)
        await super().cancel(agent_id)


class CancelRaisingFacade(CancelTrackingFacade):
    """CancelTrackingFacade whose cancel raises for supersede failure tests."""

    async def cancel(self, agent_id: str) -> None:
        self.cancel_calls.append(agent_id)
        _ = agent_id
        raise RuntimeError("sdk cancel unavailable")


def command_message(
    text: str,
    *,
    chat_id: int = DEFAULT_CHAT_ID,
    user_id: int = ALLOWED_USER_ID,
) -> FakeMessage:
    """Build a private Telegram message for slash-command handler tests."""
    return FakeMessage(
        message_id=1,
        chat=FakeChat(id=chat_id, type="private"),
        from_user=FakeUser(id=user_id),
        text=text,
    )


def make_command_adapter(
    tmp_path: object,
    *,
    facade: FakeSdkFacade | None = None,
    workspace: str = DEFAULT_WORKSPACE,
    allowed_users: list[int] | None = None,
    bot: FakeBot | None = None,
    dispatcher: FakeDispatcher | None = None,
) -> tuple[TelegramAdapter, FakeBot, FakeDispatcher, dict[str, object]]:
    """Wire a TelegramAdapter with injectable bot/dispatcher fakes."""
    handles = runtime_handles(
        tmp_path,
        facade=facade,
        workspace=workspace,
        allowed_users=allowed_users,
        logger_name="test.telegram.commands",
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


async def init_store(handles: dict[str, object]) -> SessionStore:
    """Initialize the session store from gateway runtime handles."""
    store = handles["store"]
    assert isinstance(store, SessionStore)
    await store.initialize()
    return store


async def start_command_adapter(
    adapter: TelegramAdapter,
    handles: dict[str, object],
    on_inbound: Callable[[InboundMessage], Awaitable[None]],
) -> None:
    """Initialize store and start the adapter with an inbound callback."""
    await init_store(handles)
    await adapter.start(on_inbound)


async def seed_chat_session(
    handles: dict[str, object],
    *,
    chat_id: int = DEFAULT_CHAT_ID,
    workspace: str = DEFAULT_WORKSPACE,
) -> tuple[str, str]:
    """Seed a messaging session row for the given chat."""
    store = await init_store(handles)
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
