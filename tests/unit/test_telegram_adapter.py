"""Unit tests for TelegramAdapter lifecycle, inbound, outbound, typing, and logging."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import GatewayConfig
from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.base import (
    GATEWAY_BUSY_MESSAGE,
    InboundMessage,
    OutboundMessage,
)
from cursor_agent.platforms.telegram import TelegramAdapter, _parse_telegram_command
from cursor_agent.platforms.telegram_chunking import (
    escape_telegram_html,
    telegram_session_key,
)
from cursor_agent.platforms.telegram_formatting import TelegramFormattingError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import (
    SendSpyPool,
    gateway_config,
    seed_session,
    track_inbound,
)

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


def _runtime_handles(
    tmp_path: object,
    *,
    workspace: str = "/tmp/gateway-workspace",
    bot_token: str = "bot123456:ABCdef-secret-token",
) -> dict[str, object]:
    gateway_cfg = gateway_config(workspace=workspace)
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
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")  # type: ignore[operator]
    logger = logging.getLogger("test.telegram.adapter")
    return {
        "platform_config": gateway_cfg.platforms.telegram.model_copy(
            update={"bot_token": bot_token},
        ),
        "gateway_config": gateway_cfg,
        "config": cursor_cfg,
        "store": store,
        "facade": facade,
        "logger": logger,
    }


def _make_adapter(
    tmp_path: object,
    *,
    bot: FakeBot | None = None,
    dispatcher: FakeDispatcher | None = None,
    sleeper: Sleeper | None = None,
    workspace: str = "/tmp/gateway-workspace",
    bot_token: str = "bot123456:ABCdef-secret-token",
) -> tuple[TelegramAdapter, FakeBot, FakeDispatcher]:
    handles = _runtime_handles(
        tmp_path,
        workspace=workspace,
        bot_token=bot_token,
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


async def _registered_handler(dispatcher: FakeDispatcher) -> Callable[..., Any]:
    assert dispatcher.message.handlers, "expected a registered message handler"
    handler, _filters = dispatcher.message.handlers[0]
    return handler


def _private_message(
    *,
    chat_id: int = 444555666,
    user_id: int = ALLOWED_USER_ID,
    text: str = "hello from telegram",
) -> FakeMessage:
    return FakeMessage(
        message_id=1,
        chat=FakeChat(id=chat_id, type="private"),
        from_user=FakeUser(id=user_id),
        text=text,
    )


async def _seed_inbound_session(
    adapter: TelegramAdapter,
    *,
    chat_id: int = 444555666,
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


# --- Lifecycle (sub-task 3.1) ---


def test_telegram_adapter_platform_returns_telegram(tmp_path: object) -> None:
    """TelegramAdapter.platform must be exactly 'telegram'."""
    adapter, _, _ = _make_adapter(tmp_path)
    assert adapter.platform == "telegram"


@pytest.mark.asyncio
async def test_telegram_adapter_start_registers_handler_and_polling_task(
    tmp_path: object,
) -> None:
    """start() registers handlers and begins long polling without blocking."""
    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path)
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
    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path)
    await adapter.start(track_inbound([]))

    await adapter.stop()

    assert fake_dispatcher.polling_stopped is True
    assert fake_bot.session.closed is True


# --- Inbound mapping (sub-task 3.3) ---


@pytest.mark.asyncio
async def test_telegram_inbound_direct_text_maps_to_inbound_message(
    tmp_path: object,
) -> None:
    """Direct private text messages call on_inbound with normalized fields."""
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await _seed_inbound_session(adapter)
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(text="ping"))

    assert len(received) == 1
    assert received[0].platform == "telegram"
    assert received[0].text == "ping"

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_sender_id_uses_user_not_chat_id(
    tmp_path: object,
) -> None:
    """sender_id must be Telegram user ID as a decimal string, not chat ID."""
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await _seed_inbound_session(adapter, chat_id=999888777)
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(
        _private_message(chat_id=999888777, user_id=ALLOWED_USER_ID, text="hi")
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
    adapter, _, fake_dispatcher = _make_adapter(tmp_path, workspace=workspace)
    received: list[InboundMessage] = []
    chat_id = 444555666
    await _seed_inbound_session(adapter, chat_id=chat_id, workspace=workspace)
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(chat_id=chat_id, text="workspace key"))

    expected_key = telegram_session_key(chat_id, workspace)
    assert received[0].session_key == expected_key

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_empty_text(tmp_path: object) -> None:
    """Whitespace-only text must not call on_inbound."""
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(text="   "))

    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_inbound_ignores_non_text_messages(tmp_path: object) -> None:
    """Messages without text must be ignored safely."""
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
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
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
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
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
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


# --- Outbound delivery (sub-task 3.5) ---


@pytest.mark.asyncio
async def test_telegram_send_message_delivers_html_chunks_in_order(
    tmp_path: object,
) -> None:
    """send_message() emits escaped HTML chunks sequentially in order."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    chat_id = 444555666
    session_key = telegram_session_key(chat_id, workspace)
    long_text = "line\n\n" + ("x" * 3900)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="111",
            session_key=session_key,
            text=long_text,
        ),
    )

    assert len(fake_bot.send_message_calls) >= 2
    assert fake_bot.send_message_calls[0]["parse_mode"] == "HTML"
    assert all(call["chat_id"] == chat_id for call in fake_bot.send_message_calls)
    combined = "".join(str(call["text"]) for call in fake_bot.send_message_calls)
    assert "xxxx" in combined


@pytest.mark.asyncio
async def test_telegram_send_message_escapes_html(tmp_path: object) -> None:
    """Outbound text is HTML-escaped for parse_mode=HTML."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="<b>bold</b> & more",
        ),
    )

    assert (
        fake_bot.send_message_calls[0]["text"] == "&lt;b&gt;bold&lt;/b&gt; &amp; more"
    )


@pytest.mark.asyncio
async def test_telegram_send_message_renders_markdown_bold(tmp_path: object) -> None:
    """Assistant Markdown bold renders as Telegram <b> tags."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="**Summary**",
        ),
    )

    assert fake_bot.send_message_calls[0]["text"] == "<b>Summary</b>"


@pytest.mark.asyncio
async def test_telegram_send_message_renders_markdown_code_and_link(
    tmp_path: object,
) -> None:
    """Assistant Markdown code and links render to Telegram HTML."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="Use `main.py` and [docs](https://example.com/docs).",
        ),
    )

    rendered = str(fake_bot.send_message_calls[0]["text"])
    assert "<code>main.py</code>" in rendered
    assert '<a href="https://example.com/docs">docs</a>' in rendered


@pytest.mark.asyncio
async def test_telegram_send_message_falls_back_when_formatting_fails(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Formatting failures fall back to escaped plain text without logging bodies."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)
    secret_body = "token=SUPER_SECRET_PROMPT <script>"
    caplog.set_level(logging.WARNING)

    with patch(
        "cursor_agent.platforms.telegram_formatting.render_cursor_markdown_for_telegram",
        side_effect=TelegramFormattingError("renderer exploded"),
    ):
        await adapter.send_message(
            OutboundMessage(
                platform="telegram",
                sender_id="1",
                session_key=session_key,
                text=secret_body,
            ),
        )

    assert fake_bot.send_message_calls[0]["text"] == escape_telegram_html(secret_body)
    assert "telegram_formatting_fallback" in caplog.text
    assert secret_body not in caplog.text
    assert "SUPER_SECRET_PROMPT" not in caplog.text


@pytest.mark.asyncio
async def test_telegram_send_message_never_calls_edit_message_text(
    tmp_path: object,
) -> None:
    """Adapter must not use edit_message_text for delivery."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(42, workspace)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="plain reply",
        ),
    )

    assert fake_bot.edit_message_text_calls == []


@pytest.mark.asyncio
async def test_telegram_send_message_parses_chat_id_from_session_key(
    tmp_path: object,
) -> None:
    """Outbound delivery targets chat ID embedded in adapter-owned session key."""
    workspace = "/tmp/another-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    chat_id = 987654321
    session_key = telegram_session_key(chat_id, workspace)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="55",
            session_key=session_key,
            text="target chat",
        ),
    )

    assert fake_bot.send_message_calls[0]["chat_id"] == chat_id


@pytest.mark.asyncio
async def test_telegram_send_message_ignores_empty_text(tmp_path: object) -> None:
    """Empty assistant text must not call Telegram send_message."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="",
        ),
    )
    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="   ",
        ),
    )

    assert fake_bot.send_message_calls == []


@pytest.mark.asyncio
async def test_telegram_send_message_after_stop_does_not_recreate_bot(
    tmp_path: object,
) -> None:
    """Outbound completion after shutdown must not reopen the Telegram HTTP session."""
    workspace = "/tmp/gateway-workspace"
    bot = FakeBot(token="bot123456:ABCdef-secret-token")
    adapter, fake_bot, _ = _make_adapter(tmp_path, bot=bot, workspace=workspace)
    session_key = telegram_session_key(1, workspace)

    await adapter.start(track_inbound([]))
    await adapter.stop()
    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text="late reply after shutdown",
        ),
    )

    assert fake_bot.session.closed is True
    assert fake_bot.send_message_calls == []


# --- Typing indicator (sub-task 3.7) ---


@pytest.mark.asyncio
async def test_telegram_typing_starts_during_inbound_processing(
    tmp_path: object,
) -> None:
    """Typing action is sent while on_inbound is active."""
    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path)
    release = asyncio.Event()

    async def slow_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await _seed_inbound_session(adapter)
    await adapter.start(slow_on_inbound)
    handler = await _registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(_private_message(text="typing please")))
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

    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path, sleeper=fake_sleeper)
    release = asyncio.Event()

    async def blocking_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await _seed_inbound_session(adapter)
    await adapter.start(blocking_on_inbound)
    handler = await _registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(_private_message(text="refresh typing")))
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
    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await _seed_inbound_session(adapter)
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(text="done"))

    await asyncio.sleep(0)
    assert received
    assert adapter.active_typing_task_count() == 0
    assert fake_bot.chat_action_calls

    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_typing_stops_on_shutdown(tmp_path: object) -> None:
    """stop() cancels in-flight typing tasks."""
    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path)
    release = asyncio.Event()

    async def blocking_on_inbound(_message: InboundMessage) -> None:
        await release.wait()

    await _seed_inbound_session(adapter)
    await adapter.start(blocking_on_inbound)
    handler = await _registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(_private_message(text="shutdown typing")))
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


# --- Log safety (sub-task 3.9) ---


@pytest.mark.asyncio
async def test_telegram_logs_exclude_bot_token(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter logs must never include the configured bot token."""
    secret_token = "bot999888:super-secret-token-value"
    adapter, _, fake_dispatcher = _make_adapter(tmp_path, bot_token=secret_token)
    caplog.set_level(logging.DEBUG, logger="test.telegram.adapter")

    await _seed_inbound_session(adapter)
    await adapter.start(track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(text="hello"))
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
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    caplog.set_level(logging.DEBUG, logger="test.telegram.adapter")
    secret_body = "super-secret-user-prompt-body-xyz"

    await _seed_inbound_session(adapter)
    await adapter.start(track_inbound([]))
    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(text=secret_body))
    await adapter.stop()

    combined = "\n".join(record.message for record in caplog.records)
    assert secret_body not in combined


@pytest.mark.asyncio
async def test_telegram_exception_logs_include_safe_metadata_only(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Send failures log exception class and routing metadata, not message text."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    caplog.set_level(logging.ERROR, logger="test.telegram.adapter")
    session_key = telegram_session_key(5, workspace)
    secret_body = "secret-outbound-body-should-not-log"

    async def failing_send_message(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("telegram api unavailable")

    fake_bot.send_message = failing_send_message  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="telegram api unavailable"):
        await adapter.send_message(
            OutboundMessage(
                platform="telegram",
                sender_id="9",
                session_key=session_key,
                text=secret_body,
            ),
        )

    combined = "\n".join(record.message for record in caplog.records)
    assert secret_body not in combined
    assert "RuntimeError" in combined or any(
        record.exc_info is not None for record in caplog.records
    )
    assert session_key in combined or "session_key" in combined


# --- Integrated gateway behavior (PRD-007 Wave 6A) ---


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


def _telegram_adapter_factory(
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
async def _telegram_gateway_runtime(
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
    factory = _telegram_adapter_factory(fake_bot, fake_dispatcher)

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


async def _wait_for_condition(
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


@pytest.mark.asyncio
async def test_allowlisted_telegram_flow_reaches_pool_and_delivers_reply(
    tmp_path: Path,
) -> None:
    """Allowlisted inbound with a session reaches pool.send(blocking=False) and replies."""
    reply_text = "hello from integrated agent"
    facade = FakeSdkFacade(default_reply=reply_text)

    async with _telegram_gateway_runtime(
        tmp_path,
        facade=facade,
        pool_factory=SendSpyPool,
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, config):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )

        handler = await _registered_handler(fake_dispatcher)
        await handler(
            _private_message(
                chat_id=INTEGRATION_CHAT_ID,
                text="integrated ping",
            ),
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1,
            description="pool send for allowlisted telegram flow",
        )
        await _wait_for_condition(
            lambda: any(
                str(call.get("text")) == reply_text
                for call in fake_bot.send_message_calls
            ),
            description="telegram outbound assistant reply",
        )

    assert len(ctx.pool.send_calls) == 1
    assert ctx.pool.send_calls[0]["blocking"] is False
    assert ctx.pool.send_calls[0]["message"] == "integrated ping"
    assert ctx.pool.send_calls[0]["session_key"] == session_key
    reply_calls = [
        call for call in fake_bot.send_message_calls if call.get("text") == reply_text
    ]
    assert len(reply_calls) == 1


@pytest.mark.asyncio
async def test_blocked_telegram_sender_integration_no_reply_or_side_effects(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Blocked Telegram sender creates no sessions, pool sends, facade calls, or replies."""
    facade = SideEffectTrackingFacade()
    caplog.set_level(logging.INFO, logger="cursor_agent.gateway.runner")

    async with _telegram_gateway_runtime(
        tmp_path,
        facade=facade,
        pool_factory=SendSpyPool,
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, config):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)

        handler = await _registered_handler(fake_dispatcher)
        await handler(
            _private_message(
                chat_id=INTEGRATION_CHAT_ID,
                user_id=BLOCKED_USER_ID,
                text="blocked integration attempt",
            ),
        )
        await asyncio.sleep(0.05)

        assert await ctx.store.resolve(session_key) is None
        assert ctx.pool.send_calls == []
        assert facade.create_agent_calls == []
        assert facade.send_calls == []
        assert fake_bot.send_message_calls == []

    combined_logs = "\n".join(record.message for record in caplog.records)
    assert '"event":"gateway_auth_blocked"' in combined_logs
    assert str(BLOCKED_USER_ID) in combined_logs
    assert session_key in combined_logs
    assert "blocked integration attempt" not in combined_logs


@pytest.mark.asyncio
async def test_telegram_busy_path_delivers_gateway_busy_message(
    tmp_path: Path,
) -> None:
    """AgentBusyError from the pool delivers canonical GATEWAY_BUSY_MESSAGE via Telegram."""
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="agent finished")

    async with _telegram_gateway_runtime(tmp_path, facade=facade) as (
        ctx,
        _adapter,
        fake_bot,
        fake_dispatcher,
        config,
    ):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )

        handler = await _registered_handler(fake_dispatcher)
        first_task = asyncio.create_task(
            handler(
                _private_message(
                    chat_id=INTEGRATION_CHAT_ID,
                    text="first in-flight message",
                ),
            ),
        )
        await facade.send_in_progress.wait()

        await handler(
            _private_message(
                chat_id=INTEGRATION_CHAT_ID,
                text="second busy message",
            ),
        )
        await _wait_for_condition(
            lambda: any(
                call.get("text") == GATEWAY_BUSY_MESSAGE
                for call in fake_bot.send_message_calls
            ),
            description="telegram busy outbound message",
        )

        send_release.set()
        await first_task
        await _wait_for_condition(
            lambda: any(
                str(call.get("text")) == "agent finished"
                for call in fake_bot.send_message_calls
            ),
            description="telegram assistant reply after busy path",
        )

    busy_calls = [
        call
        for call in fake_bot.send_message_calls
        if call.get("text") == GATEWAY_BUSY_MESSAGE
    ]
    assert len(busy_calls) == 1


# --- Error paths and edge cases (coverage hardening) ---


@pytest.mark.asyncio
async def test_telegram_send_message_rejects_malformed_session_key(
    tmp_path: object,
) -> None:
    """Outbound delivery with a non-Telegram session_key raises an actionable error."""
    adapter, fake_bot, _ = _make_adapter(tmp_path)

    with pytest.raises(ValueError, match="invalid telegram session_key"):
        await adapter.send_message(
            OutboundMessage(
                platform="telegram",
                sender_id="1",
                session_key="cli:messaging:deadbeef",
                text="should not be delivered",
            ),
        )

    assert fake_bot.send_message_calls == []


@pytest.mark.asyncio
async def test_telegram_polling_failure_logs_safe_metadata_and_reraises(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Polling crashes log exception class only and never leak the bot token."""
    secret_token = "bot777666:polling-secret-token"

    class RaisingDispatcher(FakeDispatcher):
        async def start_polling(self, bot: FakeBot, **kwargs: object) -> None:
            raise RuntimeError("polling boot failure")

    adapter, _fake_bot, _ = _make_adapter(
        tmp_path,
        dispatcher=RaisingDispatcher(),
        bot_token=secret_token,
    )
    caplog.set_level(logging.ERROR, logger="test.telegram.adapter")

    await adapter.start(track_inbound([]))
    assert adapter._polling_task is not None
    with pytest.raises(RuntimeError, match="polling boot failure"):
        await adapter._polling_task

    combined = "\n".join(record.message for record in caplog.records)
    assert "telegram_polling_failed" in combined
    assert "RuntimeError" in combined
    assert secret_token not in combined
    assert "polling-secret-token" not in combined


@pytest.mark.asyncio
async def test_telegram_typing_refresh_failure_logs_safe_metadata_only(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Typing refresh failures log exception class without leaking token or text."""
    secret_token = "bot555444:typing-secret-token"

    async def fast_sleeper(_seconds: float) -> None:
        await asyncio.sleep(0)

    adapter, fake_bot, fake_dispatcher = _make_adapter(
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

    await _seed_inbound_session(adapter)
    await adapter.start(blocking_on_inbound)
    handler = await _registered_handler(fake_dispatcher)
    task = asyncio.create_task(handler(_private_message(text="typing failure")))

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
async def test_telegram_inbound_ignores_messages_without_user(tmp_path: object) -> None:
    """Messages with no from_user are ignored before on_inbound."""
    adapter, _, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
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
async def test_telegram_unsupported_command_is_treated_as_free_text(
    tmp_path: object,
) -> None:
    """An unknown slash command falls through to the free-text no-session hint."""
    adapter, fake_bot, fake_dispatcher = _make_adapter(tmp_path)
    received: list[InboundMessage] = []
    await adapter._store.initialize()
    await adapter.start(track_inbound(received))

    handler = await _registered_handler(fake_dispatcher)
    await handler(_private_message(text="/unknowncommand please"))

    assert received == []
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/new", "new"),
        ("/stop@MyBot extra args", "stop"),
        ("/HELP", "help"),
        ("  /start  ", "start"),
        ("/unknown", None),
        ("/unknown@MyBot", None),
        ("plain text without slash", None),
        ("", None),
    ],
)
def test_parse_telegram_command_classification(
    text: str,
    expected: str | None,
) -> None:
    """_parse_telegram_command maps supported commands and rejects the rest."""
    assert _parse_telegram_command(text) == expected


@pytest.mark.asyncio
async def test_telegram_polling_termination_logs_critical(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected polling termination surfaces a CRITICAL operator signal."""
    secret_token = "bot111000:supervision-secret-token"

    class RaisingDispatcher(FakeDispatcher):
        async def start_polling(self, bot: FakeBot, **kwargs: object) -> None:
            raise RuntimeError("telegram outage")

    adapter, _fake_bot, _ = _make_adapter(
        tmp_path,
        dispatcher=RaisingDispatcher(),
        bot_token=secret_token,
    )
    caplog.set_level(logging.CRITICAL, logger="test.telegram.adapter")

    await adapter.start(track_inbound([]))
    assert adapter._polling_task is not None
    with contextlib.suppress(RuntimeError):
        await adapter._polling_task
    await asyncio.sleep(0)

    combined = "\n".join(record.message for record in caplog.records)
    assert "telegram_polling_terminated" in combined
    assert secret_token not in combined


@pytest.mark.asyncio
async def test_telegram_polling_termination_silent_on_normal_stop(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A clean stop() must not emit the CRITICAL termination signal."""
    adapter, _fake_bot, _ = _make_adapter(tmp_path)
    caplog.set_level(logging.CRITICAL, logger="test.telegram.adapter")

    await adapter.start(track_inbound([]))
    await adapter.stop()
    await asyncio.sleep(0)

    combined = "\n".join(record.message for record in caplog.records)
    assert "telegram_polling_terminated" not in combined


@pytest.mark.asyncio
async def test_telegram_send_message_falls_back_to_plain_text_on_html_rejection(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When Telegram rejects parse_mode=HTML, the reply is retried as plain text."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)
    caplog.set_level(logging.WARNING, logger="test.telegram.adapter")
    raw_text = "**bold** and <x>"
    attempts: list[dict[str, object]] = []

    async def html_rejecting_send(
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> object:
        attempts.append({"text": text, "parse_mode": parse_mode})
        if parse_mode == "HTML":
            raise RuntimeError("Bad Request: can't parse entities")
        return {"ok": True}

    fake_bot.send_message = html_rejecting_send  # type: ignore[method-assign]

    await adapter.send_message(
        OutboundMessage(
            platform="telegram",
            sender_id="1",
            session_key=session_key,
            text=raw_text,
        ),
    )

    html_attempts = [a for a in attempts if a["parse_mode"] == "HTML"]
    plain_attempts = [a for a in attempts if a["parse_mode"] is None]
    assert len(html_attempts) == 1
    assert plain_attempts
    assert plain_attempts[0]["text"] == raw_text
    assert "telegram_outbound_html_fallback" in caplog.text


@pytest.mark.asyncio
async def test_telegram_send_message_reraises_when_failure_after_first_chunk(
    tmp_path: object,
) -> None:
    """A failure after the first chunk re-raises instead of duplicating delivery."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = _make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)
    long_text = "line\n\n" + ("x" * 3900)
    attempts: list[str | None] = []

    async def fail_after_first(
        chat_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> object:
        attempts.append(parse_mode)
        if len(attempts) >= 2:
            raise RuntimeError("api down mid-stream")
        return {"ok": True}

    fake_bot.send_message = fail_after_first  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="api down mid-stream"):
        await adapter.send_message(
            OutboundMessage(
                platform="telegram",
                sender_id="1",
                session_key=session_key,
                text=long_text,
            ),
        )

    assert attempts.count(None) == 0
