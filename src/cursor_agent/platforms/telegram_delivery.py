"""Telegram outbound delivery, HTML fallback, and typing indicators (PRD-012)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

from aiogram.enums import ChatAction

from cursor_agent.gateway.config import TelegramPlatformConfig
from cursor_agent.platforms.base import OutboundMessage
from cursor_agent.platforms.telegram_chunking import split_plain_text_reply
from cursor_agent.platforms.telegram_formatting import (
    prepare_telegram_assistant_reply_chunks,
)

TELEGRAM_TYPING_REFRESH_SECONDS: Final[float] = 5.0
_SESSION_KEY_PATTERN = re.compile(r"^telegram:(?P<chat_id>-?\d+):[0-9a-f]{8}$")

Sleeper = Callable[[float], Awaitable[None]]


class BotProtocol(Protocol):
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


BotFactory = Callable[[str], BotProtocol]


def parse_delivery_chat_id(chat_id: str) -> int | str:
    """Parse cron-configured Telegram chat id for bot.send_message."""
    stripped = chat_id.strip()
    if not stripped:
        raise ValueError(
            f"invalid telegram chat_id: received {chat_id!r}, expected non-empty string"
        )
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


def parse_telegram_chat_id(session_key: str) -> int:
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


class TelegramTypingController:
    """Refresh Telegram typing indicators until inbound handling completes."""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        sleeper: Sleeper,
    ) -> None:
        self._logger = logger
        self._sleeper = sleeper
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def active_task_count(self) -> int:
        """Return the number of in-flight typing refresh tasks."""
        return sum(1 for task in self._tasks.values() if not task.done())

    async def start(self, bot: BotProtocol, chat_id: int) -> None:
        """Begin typing indicator refresh for ``chat_id``."""
        await self.stop(chat_id)
        await bot.send_chat_action(
            chat_id=chat_id,
            action=ChatAction.TYPING.value,
        )
        task = asyncio.create_task(
            self._refresh_loop(bot, chat_id),
            name=f"telegram-typing-{chat_id}",
        )
        self._tasks[chat_id] = task

    async def stop(self, chat_id: int) -> None:
        """Cancel typing refresh for ``chat_id`` if active."""
        task = self._tasks.pop(chat_id, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def cancel_all(self) -> None:
        """Cancel every active typing refresh task."""
        chat_ids = list(self._tasks)
        for chat_id in chat_ids:
            await self.stop(chat_id)

    async def _refresh_loop(self, bot: BotProtocol, chat_id: int) -> None:
        try:
            while True:
                await self._sleeper(TELEGRAM_TYPING_REFRESH_SECONDS)
                await bot.send_chat_action(
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


class TelegramDelivery:
    """Send assistant replies, cron HTML chunks, and plain command replies.

    Example:
        >>> delivery = TelegramDelivery(
        ...     platform_config=platform_config,
        ...     bot_factory=bot_factory,
        ...     logger=logger,
        ...     is_stopped=lambda: adapter._stopped,
        ...     get_bot=lambda: adapter._bot,
        ...     set_bot=lambda bot: setattr(adapter, "_bot", bot),
        ... )
        >>> await delivery.send_message(outbound)
    """

    def __init__(
        self,
        *,
        platform_config: TelegramPlatformConfig,
        bot_factory: BotFactory,
        logger: logging.Logger,
        sleeper: Sleeper,
        is_stopped: Callable[[], bool],
        get_bot: Callable[[], BotProtocol | None],
        set_bot: Callable[[BotProtocol], None],
    ) -> None:
        self._platform_config = platform_config
        self._bot_factory = bot_factory
        self._logger = logger
        self._is_stopped = is_stopped
        self._get_bot = get_bot
        self._set_bot = set_bot
        self.typing = TelegramTypingController(logger=logger, sleeper=sleeper)

    async def send_html_chunk(self, chat_id: str, html: str) -> None:
        """Deliver one pre-rendered HTML chunk for cron post-run delivery."""
        if not html or not html.strip():
            return
        bot = await self._resolve_bot_for_cron(chat_id)
        parsed_chat_id = parse_delivery_chat_id(chat_id)
        await bot.send_message(
            chat_id=parsed_chat_id,
            text=html,
            parse_mode="HTML",
        )

    async def send_message(self, outbound: OutboundMessage) -> None:
        """Deliver escaped HTML reply chunks to the Telegram chat in session_key."""
        if not outbound.text or not outbound.text.strip():
            return
        bot = self._get_bot()
        if bot is None:
            if self._is_stopped():
                self._logger.info(
                    "telegram_outbound_skipped_after_stop platform=telegram "
                    "session_key=%s",
                    outbound.session_key,
                )
                return
            bot = self._bot_factory(self._platform_config.bot_token)
            self._set_bot(bot)
        chat_id = parse_telegram_chat_id(outbound.session_key)
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
        sent_chunks = 0
        try:
            for chunk in chunks:
                await bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="HTML",
                )
                sent_chunks += 1
        except Exception as exc:
            if sent_chunks == 0:
                self._logger.warning(
                    "telegram_outbound_html_fallback platform=telegram chat_id=%s "
                    "session_key=%s exception_class=%s",
                    chat_id,
                    outbound.session_key,
                    exc.__class__.__name__,
                )
                await self._deliver_plain_text_fallback(bot, chat_id, outbound)
                return
            self._logger.exception(
                "telegram_outbound_failed platform=telegram chat_id=%s "
                "session_key=%s exception_class=%s",
                chat_id,
                outbound.session_key,
                exc.__class__.__name__,
            )
            raise

    async def send_plain_reply(self, chat_id: int, text: str) -> None:
        """Send a plain-text reply without HTML parse mode."""
        bot = self._get_bot()
        if bot is None:
            self._logger.warning(
                "telegram_plain_reply_dropped platform=telegram chat_id=%s "
                "reason=bot_unavailable",
                chat_id,
            )
            return
        await bot.send_message(chat_id=chat_id, text=text)

    async def _resolve_bot_for_cron(self, chat_id: str) -> BotProtocol:
        bot = self._get_bot()
        if bot is not None:
            return bot
        if self._is_stopped():
            raise RuntimeError(
                "telegram cron delivery failed: adapter stopped before HTML chunk "
                f"delivery for chat_id={chat_id!r}"
            )
        bot = self._bot_factory(self._platform_config.bot_token)
        self._set_bot(bot)
        return bot

    async def _deliver_plain_text_fallback(
        self,
        bot: BotProtocol,
        chat_id: int,
        outbound: OutboundMessage,
    ) -> None:
        """Send the plain-text fallback, keeping the safe-log guarantee on failure."""
        try:
            await self._send_plain_text_fallback(bot, chat_id, outbound.text)
        except Exception as exc:
            self._logger.exception(
                "telegram_outbound_failed platform=telegram chat_id=%s "
                "session_key=%s exception_class=%s",
                chat_id,
                outbound.session_key,
                exc.__class__.__name__,
            )
            raise

    async def _send_plain_text_fallback(
        self,
        bot: BotProtocol,
        chat_id: int,
        text: str,
    ) -> None:
        """Deliver the reply as plain text when Telegram rejects parse_mode=HTML."""
        for chunk in split_plain_text_reply(text):
            await bot.send_message(chat_id=chat_id, text=chunk)


__all__ = [
    "BotFactory",
    "BotProtocol",
    "Sleeper",
    "TELEGRAM_TYPING_REFRESH_SECONDS",
    "TelegramDelivery",
    "TelegramTypingController",
    "parse_delivery_chat_id",
    "parse_telegram_chat_id",
]
