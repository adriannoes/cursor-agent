"""Telegram platform adapter (PRD-007)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import cast

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import Message

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.facade_logging import emit_gateway_auth_blocked
from cursor_agent.gateway.auth import is_allowed_sender
from cursor_agent.gateway.config import GatewayConfig, TelegramPlatformConfig
from cursor_agent.platforms.base import (
    GatewayInboundCallback,
    InboundMessage,
    OutboundMessage,
)
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.platforms.telegram_commands import (
    SUPPORTED_TELEGRAM_COMMANDS,
    TELEGRAM_HELP_TEXT,
    TelegramCommandRouter,
    parse_telegram_command,
    workspace_path,
)
from cursor_agent.platforms.telegram_delivery import (
    BotFactory,
    BotProtocol,
    Sleeper,
    TelegramDelivery,
)
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.store import SessionStore

# Re-exported for existing behavior-lock imports in unit tests.
_parse_telegram_command = parse_telegram_command
_SUPPORTED_TELEGRAM_COMMANDS = SUPPORTED_TELEGRAM_COMMANDS


class _DispatcherProtocol:
    message: object

    async def start_polling(self, bot: object, **kwargs: object) -> None: ...

    def stop_polling(self) -> Awaitable[None] | None: ...


def _default_bot_factory(token: str) -> BotProtocol:
    return cast(BotProtocol, Bot(token))


def _default_dispatcher_factory() -> _DispatcherProtocol:
    return cast(_DispatcherProtocol, Dispatcher())


DispatcherFactory = Callable[[], _DispatcherProtocol]


class TelegramAdapter:
    """Telegram ``PlatformAdapter`` using aiogram long polling.

    Example:
        >>> adapter = TelegramAdapter(
        ...     platform_config=TelegramPlatformConfig(
        ...         enabled=True,
        ...         bot_token="placeholder",
        ...     ),
        ...     gateway_config=gateway_config,
        ...     config=cursor_config,
        ...     store=store,
        ...     facade=facade,
        ...     logger=logger,
        ... )
        >>> adapter.platform
        'telegram'
    """

    def __init__(
        self,
        *,
        platform_config: TelegramPlatformConfig,
        gateway_config: GatewayConfig,
        config: CursorAgentConfig,
        store: SessionStore,
        facade: SdkFacade,
        logger: logging.Logger,
        bot_factory: BotFactory | None = None,
        dispatcher_factory: DispatcherFactory | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._platform_config = platform_config
        self._gateway_config = gateway_config
        self._config = config
        self._store = store
        self._facade = facade
        self._logger = logger
        self._bot_factory = bot_factory or _default_bot_factory
        self._dispatcher_factory = dispatcher_factory or _default_dispatcher_factory
        self._sleeper = sleeper or asyncio.sleep
        self._bot: BotProtocol | None = None
        self._dispatcher: _DispatcherProtocol | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._on_inbound: GatewayInboundCallback | None = None
        self._stopped = False
        self._delivery = TelegramDelivery(
            platform_config=platform_config,
            bot_factory=self._bot_factory,
            logger=logger,
            sleeper=self._sleeper,
            is_stopped=lambda: self._stopped,
            get_bot=lambda: self._bot,
            set_bot=self._set_bot,
        )
        self._commands = TelegramCommandRouter(
            gateway_config=gateway_config,
            config=config,
            store=store,
            facade=facade,
            logger=logger,
            send_plain_reply=self._delivery.send_plain_reply,
        )

    def _set_bot(self, bot: BotProtocol) -> None:
        self._bot = bot

    @property
    def platform(self) -> str:
        """Stable platform identifier for gateway adapter validation."""
        return "telegram"

    def active_typing_task_count(self) -> int:
        """Return the number of in-flight typing refresh tasks (test helper)."""
        return self._delivery.typing.active_task_count()

    async def start(self, on_inbound: GatewayInboundCallback) -> None:
        """Register handlers and begin aiogram long polling in a background task."""
        self._stopped = False
        self._on_inbound = on_inbound
        self._bot = self._bot_factory(self._platform_config.bot_token)
        self._dispatcher = self._dispatcher_factory()
        self._register_handlers()
        self._polling_task = asyncio.create_task(
            self._run_polling(),
            name="telegram-polling",
        )
        self._polling_task.add_done_callback(self._handle_polling_task_done)
        self._logger.info(
            "telegram_adapter_started platform=telegram polling_task=%s",
            self._polling_task.get_name(),
        )

    def _handle_polling_task_done(self, task: asyncio.Task[None]) -> None:
        """Surface unexpected polling termination so the operator is not blind.

        Long polling running in a fire-and-forget task can crash (revoked token,
        Telegram outage) and leave the gateway alive with no inbound path. A
        CRITICAL log makes that operator-visible without leaking secrets.
        """
        if task.cancelled() or self._stopped:
            return
        exc = task.exception()
        if exc is None:
            return
        self._logger.critical(
            "telegram_polling_terminated platform=telegram exception_class=%s; "
            "gateway has no inbound path until restarted",
            exc.__class__.__name__,
        )

    async def stop(self) -> None:
        """Stop polling, cancel typing tasks, and close the bot HTTP session."""
        self._stopped = True
        await self._delivery.typing.cancel_all()
        if self._polling_task is not None:
            self._polling_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._polling_task
            self._polling_task = None
        if self._dispatcher is not None:
            stop_result = self._dispatcher.stop_polling()
            if asyncio.iscoroutine(stop_result):
                with contextlib.suppress(RuntimeError):
                    await stop_result
        if self._bot is not None:
            session = self._bot.session
            close = getattr(session, "close", None)
            if callable(close):
                await close()
            self._bot = None
        self._dispatcher = None
        self._on_inbound = None
        self._logger.info("telegram_adapter_stopped platform=telegram")

    async def send_html_chunk(self, chat_id: str, html: str) -> None:
        """Deliver one pre-rendered HTML chunk for cron post-run delivery."""
        await self._delivery.send_html_chunk(chat_id, html)

    async def send_message(self, outbound: OutboundMessage) -> None:
        """Deliver escaped HTML reply chunks to the Telegram chat in session_key."""
        await self._delivery.send_message(outbound)

    def _register_handlers(self) -> None:
        if self._dispatcher is None:
            return

        async def handler(message: Message) -> None:
            await self._handle_inbound_message(message)

        self._dispatcher.message.register(  # type: ignore[attr-defined]
            handler,
            F.chat.type == ChatType.PRIVATE,
            F.text,
        )

    async def _run_polling(self) -> None:
        if self._bot is None or self._dispatcher is None:
            return
        try:
            await self._dispatcher.start_polling(
                self._bot,
                handle_signals=False,
                close_bot_session=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.exception(
                "telegram_polling_failed platform=telegram exception_class=%s",
                exc.__class__.__name__,
            )
            raise

    async def _handle_inbound_message(self, message: Message) -> None:
        if not self._is_supported_inbound(message):
            return
        if self._on_inbound is None:
            return

        inbound = self._build_inbound_message(message)
        chat_id = message.chat.id
        self._logger.info(
            "telegram_inbound_received platform=telegram chat_id=%s sender_id=%s "
            "session_key=%s",
            chat_id,
            inbound.sender_id,
            inbound.session_key,
        )

        if not is_allowed_sender(
            "telegram",
            inbound.sender_id,
            self._gateway_config,
        ):
            emit_gateway_auth_blocked(
                self._logger,
                platform="telegram",
                sender_id=inbound.sender_id,
                session_key=inbound.session_key,
            )
            return

        assert message.text is not None
        command = parse_telegram_command(message.text)
        if command is not None:
            await self._commands.dispatch(
                command,
                chat_id=chat_id,
                session_key=inbound.session_key,
            )
            return

        if await self._store.resolve(inbound.session_key) is None:
            await self._delivery.send_plain_reply(chat_id, TELEGRAM_NO_SESSION_HINT)
            return

        await self._start_typing(chat_id)
        try:
            await self._on_inbound(inbound)
        finally:
            await self._stop_typing(chat_id)

    async def _start_typing(self, chat_id: int) -> None:
        if self._bot is None:
            return
        await self._delivery.typing.start(self._bot, chat_id)

    async def _stop_typing(self, chat_id: int) -> None:
        await self._delivery.typing.stop(chat_id)

    @staticmethod
    def _normalized_chat_type(chat_type: object) -> str:
        value = getattr(chat_type, "value", chat_type)
        return str(value)

    def _is_supported_inbound(self, message: Message) -> bool:
        if self._normalized_chat_type(message.chat.type) != ChatType.PRIVATE.value:
            return False
        if message.is_topic_message or message.message_thread_id is not None:
            return False
        if message.from_user is None:
            return False
        text = message.text
        if text is None or not text.strip():
            return False
        return True

    def _build_inbound_message(self, message: Message) -> InboundMessage:
        assert message.from_user is not None
        assert message.text is not None
        workspace = workspace_path(self._gateway_config, self._config)
        return InboundMessage(
            platform="telegram",
            sender_id=str(message.from_user.id),
            session_key=telegram_session_key(message.chat.id, workspace),
            text=message.text,
        )


__all__ = [
    "TELEGRAM_HELP_TEXT",
    "TelegramAdapter",
    "_SUPPORTED_TELEGRAM_COMMANDS",
    "_parse_telegram_command",
]
