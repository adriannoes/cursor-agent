"""Telegram platform adapter (PRD-007)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final, Protocol, cast

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatAction, ChatType
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
from cursor_agent.platforms.telegram_formatting import (
    prepare_telegram_assistant_reply_chunks,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

TELEGRAM_TYPING_REFRESH_SECONDS = 5.0
_SESSION_KEY_PATTERN = re.compile(r"^telegram:(?P<chat_id>-?\d+):[0-9a-f]{8}$")

TELEGRAM_NEW_CONFIRMATION: Final[str] = "Started a new conversation."
TELEGRAM_STOP_SUCCESS: Final[str] = "Run cancelled."
TELEGRAM_STOP_NO_SESSION: Final[str] = (
    "No active session. Send /new to start a conversation."
)
TELEGRAM_HELP_TEXT: Final[str] = """\
Telegram commands:

/new — Start or reset your conversation
/stop — Cancel the current run
/help — Show this message
"""

_SUPPORTED_TELEGRAM_COMMANDS: Final[frozenset[str]] = frozenset(
    {"new", "stop", "help", "start"},
)

Sleeper = Callable[[float], Awaitable[None]]


class _BotProtocol(Protocol):
    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        *,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> object: ...

    async def send_chat_action(
        self,
        chat_id: int | str,
        action: str,
        **kwargs: object,
    ) -> object: ...

    @property
    def session(self) -> object: ...


class _DispatcherProtocol(Protocol):
    message: object

    async def start_polling(self, bot: object, **kwargs: object) -> None: ...

    def stop_polling(self) -> Awaitable[None] | None: ...


BotFactory = Callable[[str], _BotProtocol]
DispatcherFactory = Callable[[], _DispatcherProtocol]


def _default_bot_factory(token: str) -> _BotProtocol:
    return cast(_BotProtocol, Bot(token))


def _default_dispatcher_factory() -> _DispatcherProtocol:
    return cast(_DispatcherProtocol, Dispatcher())


def _parse_telegram_chat_id(session_key: str) -> int:
    """Extract Telegram chat ID from an adapter-owned session key."""
    match = _SESSION_KEY_PATTERN.match(session_key)
    if match is None:
        msg = (
            "invalid telegram session_key for outbound delivery: "
            f"received {session_key!r}, expected "
            "'telegram:<chat_id>:<8-char-hex-workspace-hash>'"
        )
        raise ValueError(msg)
    return int(match.group("chat_id"))


def _workspace_path(
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
) -> str:
    """Return the canonical workspace path used for Telegram session keys."""
    return config.runtime.local.cwd or gateway_config.workspace


def _resolved_workspace(
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
) -> str:
    """Return the absolute workspace path used for SDK agent creation."""
    return str(Path(_workspace_path(gateway_config, config)).resolve())


def _parse_telegram_command(text: str) -> str | None:
    """Return a supported Telegram slash command name, or ``None`` for free text."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command_token = stripped.split(maxsplit=1)[0]
    command_name = command_token.split("@", maxsplit=1)[0].lstrip("/").lower()
    if command_name in _SUPPORTED_TELEGRAM_COMMANDS:
        return command_name
    return None


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
        ...     pool=pool,
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
        pool: SessionAgentPool,
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
        self._pool = pool
        self._logger = logger
        self._bot_factory = bot_factory or _default_bot_factory
        self._dispatcher_factory = dispatcher_factory or _default_dispatcher_factory
        self._sleeper = sleeper or asyncio.sleep
        self._bot: _BotProtocol | None = None
        self._dispatcher: _DispatcherProtocol | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._on_inbound: GatewayInboundCallback | None = None
        self._typing_tasks: dict[int, asyncio.Task[None]] = {}
        self._stopped = False

    @property
    def platform(self) -> str:
        """Stable platform identifier for gateway adapter validation."""
        return "telegram"

    def active_typing_task_count(self) -> int:
        """Return the number of in-flight typing refresh tasks (test helper)."""
        return sum(1 for task in self._typing_tasks.values() if not task.done())

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
        self._logger.info(
            "telegram_adapter_started platform=telegram polling_task=%s",
            self._polling_task.get_name(),
        )

    async def stop(self) -> None:
        """Stop polling, cancel typing tasks, and close the bot HTTP session."""
        self._stopped = True
        await self._cancel_all_typing_tasks()
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

    async def send_message(self, outbound: OutboundMessage) -> None:
        """Deliver escaped HTML reply chunks to the Telegram chat in session_key."""
        if not outbound.text or not outbound.text.strip():
            return
        bot = self._bot
        if bot is None:
            if self._stopped:
                self._logger.info(
                    "telegram_outbound_skipped_after_stop platform=telegram "
                    "session_key=%s",
                    outbound.session_key,
                )
                return
            bot = self._bot_factory(self._platform_config.bot_token)
            self._bot = bot
        assert bot is not None

        chat_id = _parse_telegram_chat_id(outbound.session_key)
        chunks = prepare_telegram_assistant_reply_chunks(
            outbound.text,
            logger=self._logger,
        )
        self._logger.info(
            "telegram_outbound_send platform=telegram chat_id=%s session_key=%s "
            "chunk_count=%s",
            chat_id,
            outbound.session_key,
            len(chunks),
        )
        try:
            for chunk in chunks:
                await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="HTML",
                )
        except Exception as exc:
            self._logger.exception(
                "telegram_outbound_failed platform=telegram chat_id=%s "
                "session_key=%s exception_class=%s",
                chat_id,
                outbound.session_key,
                exc.__class__.__name__,
            )
            raise

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
        command = _parse_telegram_command(message.text)
        if command is not None:
            await self._dispatch_telegram_command(
                command,
                chat_id=chat_id,
                session_key=inbound.session_key,
            )
            return

        if await self._store.resolve(inbound.session_key) is None:
            await self._send_plain_reply(chat_id, TELEGRAM_NO_SESSION_HINT)
            return

        await self._start_typing(chat_id)
        try:
            await self._on_inbound(inbound)
        finally:
            await self._stop_typing(chat_id)

    async def _dispatch_telegram_command(
        self,
        command: str,
        *,
        chat_id: int,
        session_key: str,
    ) -> None:
        if command == "new":
            await self._handle_new_command(chat_id=chat_id, session_key=session_key)
            return
        if command == "stop":
            await self._handle_stop_command(chat_id=chat_id, session_key=session_key)
            return
        if command == "help":
            await self._send_plain_reply(chat_id, TELEGRAM_HELP_TEXT.strip())
            return
        if command == "start":
            await self._send_plain_reply(chat_id, TELEGRAM_NO_SESSION_HINT)
            return
        msg = (
            "unsupported telegram command dispatch: "
            f"received {command!r}, expected one of {sorted(_SUPPORTED_TELEGRAM_COMMANDS)!r}"
        )
        raise ValueError(msg)

    async def _handle_new_command(self, *, chat_id: int, session_key: str) -> None:
        workspace = _resolved_workspace(self._gateway_config, self._config)
        agent_id = await self._facade.create_agent(
            workspace=workspace,
            model=self._config.model,
            tool_profile=self._config.tool_profile,
            runtime_mode=self._config.runtime.mode,
        )
        await self._store.create(
            SessionCreateParams(
                session_key=session_key,
                agent_id=agent_id,
                workspace=workspace,
                runtime=self._config.runtime.mode,
                tool_profile=self._config.tool_profile,
                title=None,
            ),
        )
        self._logger.info(
            "telegram_command_new platform=telegram chat_id=%s session_key=%s",
            chat_id,
            session_key,
        )
        await self._send_plain_reply(chat_id, TELEGRAM_NEW_CONFIRMATION)

    async def _handle_stop_command(self, *, chat_id: int, session_key: str) -> None:
        row = await self._store.resolve(session_key)
        if row is None:
            await self._send_plain_reply(chat_id, TELEGRAM_STOP_NO_SESSION)
            return
        await self._facade.cancel(row.agent_id)
        self._logger.info(
            "telegram_command_stop platform=telegram chat_id=%s session_key=%s",
            chat_id,
            session_key,
        )
        await self._send_plain_reply(chat_id, TELEGRAM_STOP_SUCCESS)

    async def _send_plain_reply(self, chat_id: int, text: str) -> None:
        if self._bot is None:
            return
        await self._bot.send_message(chat_id=chat_id, text=text)

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
        workspace = _workspace_path(self._gateway_config, self._config)
        return InboundMessage(
            platform="telegram",
            sender_id=str(message.from_user.id),
            session_key=telegram_session_key(message.chat.id, workspace),
            text=message.text,
        )

    async def _start_typing(self, chat_id: int) -> None:
        await self._stop_typing(chat_id)
        if self._bot is None:
            return
        await self._bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.TYPING.value,
        )
        task = asyncio.create_task(
            self._typing_refresh_loop(chat_id),
            name=f"telegram-typing-{chat_id}",
        )
        self._typing_tasks[chat_id] = task

    async def _stop_typing(self, chat_id: int) -> None:
        task = self._typing_tasks.pop(chat_id, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _cancel_all_typing_tasks(self) -> None:
        chat_ids = list(self._typing_tasks)
        for chat_id in chat_ids:
            await self._stop_typing(chat_id)

    async def _typing_refresh_loop(self, chat_id: int) -> None:
        if self._bot is None:
            return
        try:
            while True:
                await self._sleeper(TELEGRAM_TYPING_REFRESH_SECONDS)
                await self._bot.send_chat_action(
                    chat_id=chat_id,
                    action=ChatAction.TYPING.value,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.exception(
                "telegram_typing_failed platform=telegram chat_id=%s "
                "exception_class=%s",
                chat_id,
                exc.__class__.__name__,
            )


__all__ = ["TelegramAdapter"]
