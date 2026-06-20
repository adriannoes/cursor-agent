"""Unit tests for Telegram adapter shutdown ordering in the gateway (ADR-021)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.telegram import TelegramAdapter

from tests.unit.gateway_fakes import CancelTrackingFacade, gateway_config
from tests.unit.telegram_adapter_fakes import (
    FakeBot,
    FakeBotSession,
    FakeDispatcher,
    telegram_adapter_factory,
)


class ShutdownTrackingBotSession(FakeBotSession):
    """Fake bot session that records close ordering for Telegram shutdown tests."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def close(self) -> None:
        self._events.append("bot_session_closed")
        await super().close()


class ShutdownTrackingDispatcher(FakeDispatcher):
    """Fake dispatcher that records polling stop ordering."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    def stop_polling(self) -> None:
        self._events.append("polling_stopped")
        super().stop_polling()


class ShutdownTrackingFacade(CancelTrackingFacade):
    """Fake facade that records close ordering for Telegram shutdown tests."""

    def __init__(self, events: list[str], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._events = events

    async def close(self) -> None:
        self._events.append("facade_close")
        await super().close()


async def test_telegram_shutdown_stops_polling_before_facade_close(
    tmp_path: Path,
) -> None:
    """TelegramAdapter stops polling and closes the bot session before facade.close()."""
    shutdown_events: list[str] = []
    config = gateway_config()
    facade = ShutdownTrackingFacade(shutdown_events)
    fake_bot = FakeBot(token=config.platforms.telegram.bot_token)
    fake_bot.session = ShutdownTrackingBotSession(shutdown_events)
    fake_dispatcher = ShutdownTrackingDispatcher(shutdown_events)
    factory = telegram_adapter_factory(fake_bot, fake_dispatcher)
    db_path = tmp_path / "telegram-shutdown-sessions.db"

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.build_platform_adapters",
            side_effect=factory,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            facade=facade,
            store_path=db_path,
            register_signals=False,
            shutdown_timeout_seconds=0.05,
        ) as ctx:
            adapter = ctx.adapters[0]
            assert isinstance(adapter, TelegramAdapter)
            await asyncio.sleep(0)
            assert fake_dispatcher.polling_started is True

    assert "polling_stopped" in shutdown_events
    assert "bot_session_closed" in shutdown_events
    assert "facade_close" in shutdown_events
    assert shutdown_events.index("polling_stopped") < shutdown_events.index(
        "facade_close",
    )
    assert shutdown_events.index("bot_session_closed") < shutdown_events.index(
        "facade_close",
    )
    assert facade._closed is True
