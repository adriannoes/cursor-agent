"""Shared Telegram adapter fakes and setup helpers for unit tests."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import GatewayConfig
from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import SendSpyPool, gateway_config, seed_session

Sleeper = Callable[[float], Awaitable[None]]

ALLOWED_USER_ID = 123456789
BLOCKED_USER_ID = 999888777
INTEGRATION_CHAT_ID = 444555666


@dataclass
class FakeChat:
    id: int
    type: str


@dataclass
class FakeUser:
    id: int


@dataclass
class FakeMessage:
    message_id: int
    chat: FakeChat
    from_user: FakeUser | None = None
    text: str | None = None
    message_thread_id: int | None = None
    is_topic_message: bool = False


@dataclass
class FakeBotSession:
    closed: bool = False

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeBot:
    token: str
    send_message_calls: list[dict[str, object]] = field(default_factory=list)
    chat_action_calls: list[dict[str, object]] = field(default_factory=list)
    session: FakeBotSession = field(default_factory=FakeBotSession)
    edit_message_text_calls: list[dict[str, object]] = field(default_factory=list)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> object:
        self.send_message_calls.append(
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                **kwargs,
            },
        )
        return {"ok": True}

    async def send_chat_action(
        self,
        chat_id: int,
        action: str,
        **kwargs: object,
    ) -> object:
        self.chat_action_calls.append(
            {"chat_id": chat_id, "action": action, **kwargs},
        )
        return {"ok": True}

    async def edit_message_text(self, *args: object, **kwargs: object) -> object:
        self.edit_message_text_calls.append({"args": args, "kwargs": kwargs})
        return {"ok": True}


class FakeMessageRegistration:
    """Captures aiogram-style message handler registrations."""

    def __init__(self, dispatcher: FakeDispatcher) -> None:
        self._dispatcher = dispatcher
        self.handlers: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []

    def register(
        self,
        handler: Callable[..., Any],
        *filters: object,
    ) -> None:
        self.handlers.append((handler, filters))

    def __call__(
        self, *filters: object
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.register(handler, *filters)
            return handler

        return decorator


@dataclass
class FakeDispatcher:
    polling_started: bool = False
    polling_stopped: bool = False
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    message: FakeMessageRegistration = field(init=False)
    polling_bot: FakeBot | None = None
    polling_kwargs: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.message = FakeMessageRegistration(self)

    async def start_polling(self, bot: FakeBot, **kwargs: object) -> None:
        self.polling_started = True
        self.polling_bot = bot
        self.polling_kwargs = dict(kwargs)
        await self._stop_event.wait()

    def stop_polling(self) -> None:
        self.polling_stopped = True
        self._stop_event.set()


def runtime_handles(
    tmp_path: object,
    *,
    workspace: str = "/tmp/gateway-workspace",
    bot_token: str = "bot123456:ABCdef-secret-token",
    facade: FakeSdkFacade | None = None,
    allowed_users: list[int] | None = None,
    logger_name: str = "test.telegram.adapter",
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
    logger = logging.getLogger(logger_name)
    return {
        "platform_config": gateway_cfg.platforms.telegram.model_copy(
            update={"bot_token": bot_token},
        ),
        "gateway_config": gateway_cfg,
        "config": cursor_cfg,
        "store": store,
        "facade": sdk_facade,
        "logger": logger,
    }


def make_adapter(
    tmp_path: object,
    *,
    bot: FakeBot | None = None,
    dispatcher: FakeDispatcher | None = None,
    sleeper: Sleeper | None = None,
    workspace: str = "/tmp/gateway-workspace",
    bot_token: str = "bot123456:ABCdef-secret-token",
    facade: FakeSdkFacade | None = None,
    allowed_users: list[int] | None = None,
    logger_name: str = "test.telegram.adapter",
) -> tuple[TelegramAdapter, FakeBot, FakeDispatcher]:
    handles = runtime_handles(
        tmp_path,
        workspace=workspace,
        bot_token=bot_token,
        facade=facade,
        allowed_users=allowed_users,
        logger_name=logger_name,
    )
    fake_bot = bot or FakeBot(token=bot_token)
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
        sleeper=sleeper,
    )
    return adapter, fake_bot, fake_dispatcher


async def registered_handler(dispatcher: FakeDispatcher) -> Callable[..., Any]:
    assert dispatcher.message.handlers, "expected a registered message handler"
    handler, _filters = dispatcher.message.handlers[0]
    return handler


def private_message(
    *,
    chat_id: int = INTEGRATION_CHAT_ID,
    user_id: int = ALLOWED_USER_ID,
    text: str = "hello from telegram",
) -> FakeMessage:
    return FakeMessage(
        message_id=1,
        chat=FakeChat(id=chat_id, type="private"),
        from_user=FakeUser(id=user_id),
        text=text,
    )


async def seed_inbound_session(
    adapter: TelegramAdapter,
    *,
    chat_id: int = INTEGRATION_CHAT_ID,
    workspace: str = "/tmp/gateway-workspace",
) -> None:
    await adapter._store.initialize()
    session_key = telegram_session_key(chat_id, workspace)
    await seed_session(
        adapter._store,
        adapter._facade,
        session_key,
        workspace=workspace,
        tool_profile="messaging",
    )


class SideEffectTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records create_agent and send invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.create_agent_calls: list[dict[str, object]] = []
        self.send_calls: list[str] = []

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

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: object = None,
        log_context: object = None,
    ) -> object:
        self.send_calls.append(message)
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,  # type: ignore[arg-type]
            log_context=log_context,  # type: ignore[arg-type]
        )


def telegram_adapter_factory(
    fake_bot: FakeBot,
    fake_dispatcher: FakeDispatcher,
) -> Callable[..., list[TelegramAdapter]]:
    """Build a factory that wires TelegramAdapter with shared gateway runtime handles."""

    def factory(**kwargs: object) -> list[TelegramAdapter]:
        gateway_cfg = kwargs["gateway_config"]
        cursor_cfg = kwargs["config"]
        store = kwargs["store"]
        facade = kwargs["facade"]
        pool = kwargs["pool"]
        logger = kwargs["logger"]
        assert isinstance(gateway_cfg, GatewayConfig)
        assert isinstance(cursor_cfg, CursorAgentConfig)
        assert isinstance(store, SessionStore)
        assert isinstance(facade, FakeSdkFacade)
        assert isinstance(pool, SessionAgentPool)
        assert isinstance(logger, logging.Logger)

        def bot_factory(token: str) -> FakeBot:
            fake_bot.token = token
            return fake_bot

        def dispatcher_factory() -> FakeDispatcher:
            return fake_dispatcher

        return [
            TelegramAdapter(
                platform_config=gateway_cfg.platforms.telegram,
                gateway_config=gateway_cfg,
                config=cursor_cfg,
                store=store,
                facade=facade,
                logger=logger,
                bot_factory=bot_factory,
                dispatcher_factory=dispatcher_factory,
            ),
        ]

    return factory


@asynccontextmanager
async def telegram_gateway_runtime(
    tmp_path: Path,
    *,
    facade: FakeSdkFacade | None = None,
    pool_factory: type[SendSpyPool] | None = SendSpyPool,
    workspace: str = "/tmp/gateway-workspace",
    allowed_users: list[int] | None = None,
) -> AsyncIterator[
    tuple[object, TelegramAdapter, FakeBot, FakeDispatcher, GatewayConfig]
]:
    """Yield gateway context with a factory-built TelegramAdapter and fakes."""
    config = gateway_config(
        workspace=workspace,
        allowed_users=allowed_users if allowed_users is not None else [ALLOWED_USER_ID],
    )
    active_facade = facade or FakeSdkFacade()
    fake_bot = FakeBot(token=config.platforms.telegram.bot_token)
    fake_dispatcher = FakeDispatcher()
    db_path = tmp_path / "telegram-gateway-sessions.db"
    factory = telegram_adapter_factory(fake_bot, fake_dispatcher)

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.build_platform_adapters",
            side_effect=factory,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            facade=active_facade,
            store_path=db_path,
            pool_factory=pool_factory,
            register_signals=False,
            shutdown_timeout_seconds=0.05,
        ) as ctx:
            adapter = ctx.adapters[0]
            assert isinstance(adapter, TelegramAdapter)
            yield ctx, adapter, fake_bot, fake_dispatcher, config


async def wait_for_condition(
    condition: Callable[[], bool],
    *,
    description: str,
) -> None:
    """Wait for a background gateway dispatch assertion to become true."""
    for _attempt in range(50):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"condition did not become true: {description}")
