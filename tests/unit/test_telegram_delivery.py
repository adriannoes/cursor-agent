"""Unit tests for TelegramAdapter outbound delivery, chunking, and cron HTML paths."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from cursor_agent.platforms.base import OutboundMessage
from cursor_agent.platforms.telegram_chunking import (
    escape_telegram_html,
    telegram_session_key,
)
from cursor_agent.platforms.telegram_delivery import parse_delivery_chat_id
from cursor_agent.platforms.telegram_formatting import (
    TelegramFormattingError,
    prepare_telegram_assistant_reply_chunks,
)

from tests.unit.gateway_fakes import track_inbound
from tests.unit.telegram_adapter_fakes import FakeBot, make_adapter


@pytest.mark.asyncio
async def test_telegram_send_html_chunk_uses_html_parse_mode(
    tmp_path: object,
) -> None:
    """Cron delivery sends pre-rendered HTML chunks with parse_mode=HTML."""
    adapter, fake_bot, _ = make_adapter(tmp_path)

    await adapter.send_html_chunk("444555666", "<b>preformatted</b>")

    assert len(fake_bot.send_message_calls) == 1
    assert fake_bot.send_message_calls[0]["chat_id"] == 444555666
    assert fake_bot.send_message_calls[0]["parse_mode"] == "HTML"
    assert fake_bot.send_message_calls[0]["text"] == "<b>preformatted</b>"


@pytest.mark.asyncio
async def test_telegram_send_html_chunk_after_stop_raises_delivery_error(
    tmp_path: object,
) -> None:
    """Cron delivery after adapter stop reports failure to the delivery layer."""
    adapter, fake_bot, _ = make_adapter(tmp_path)
    await adapter.stop()

    with pytest.raises(RuntimeError, match="stopped"):
        await adapter.send_html_chunk("444555666", "<b>late</b>")

    assert fake_bot.send_message_calls == []


@pytest.mark.asyncio
async def test_telegram_send_message_delivers_html_chunks_in_order(
    tmp_path: object,
) -> None:
    """send_message() emits escaped HTML chunks sequentially in order."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, bot=bot, workspace=workspace)
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


@pytest.mark.asyncio
async def test_telegram_send_message_rejects_malformed_session_key(
    tmp_path: object,
) -> None:
    """Outbound delivery with a non-Telegram session_key raises an actionable error."""
    adapter, fake_bot, _ = make_adapter(tmp_path)

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
async def test_telegram_exception_logs_include_safe_metadata_only(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Send failures log exception class and routing metadata, not message text."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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


@pytest.mark.asyncio
async def test_telegram_send_message_falls_back_to_plain_text_on_html_rejection(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When Telegram rejects parse_mode=HTML, the reply is retried as plain text."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
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


@pytest.mark.asyncio
async def test_telegram_send_message_uses_shared_reply_chunking_helper(
    tmp_path: object,
) -> None:
    """Assistant replies must flow through prepare_telegram_assistant_reply_chunks()."""
    workspace = "/tmp/gateway-workspace"
    adapter, fake_bot, _ = make_adapter(tmp_path, workspace=workspace)
    session_key = telegram_session_key(1, workspace)
    reply_text = "**Summary**\n\nSee `README.md` and [docs](https://example.com/docs)."
    captured: list[str] = []

    def capture_chunks(
        text: str,
        *,
        logger: logging.Logger | None = None,
    ) -> list[str]:
        captured.append(text)
        return prepare_telegram_assistant_reply_chunks(text, logger=logger)

    with patch(
        "cursor_agent.platforms.telegram_delivery.prepare_telegram_assistant_reply_chunks",
        side_effect=capture_chunks,
    ):
        await adapter.send_message(
            OutboundMessage(
                platform="telegram",
                sender_id="1",
                session_key=session_key,
                text=reply_text,
            ),
        )

    assert captured == [reply_text]
    rendered = str(fake_bot.send_message_calls[0]["text"])
    assert "<b>Summary</b>" in rendered
    assert "<code>README.md</code>" in rendered
    assert '<a href="https://example.com/docs">docs</a>' in rendered


@pytest.mark.asyncio
async def test_telegram_send_plain_reply_logs_when_bot_unavailable(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Plain command replies log a warning instead of failing silently when bot is unset."""
    adapter, fake_bot, _ = make_adapter(tmp_path)

    with caplog.at_level(logging.WARNING):
        await adapter._delivery.send_plain_reply(1, "help text")

    assert fake_bot.send_message_calls == []
    assert any(
        "telegram_plain_reply_dropped" in record.message for record in caplog.records
    )


def test_parse_delivery_chat_id_accepts_numeric_strings() -> None:
    """Cron delivery parses numeric Telegram chat ids as integers."""
    assert parse_delivery_chat_id("444555666") == 444555666
    assert parse_delivery_chat_id("  -1001234567890  ") == -1001234567890


def test_parse_delivery_chat_id_preserves_non_numeric_channel_names() -> None:
    """Cron delivery keeps @channel usernames as strings for the Telegram API."""
    assert parse_delivery_chat_id("@my_channel") == "@my_channel"


def test_parse_delivery_chat_id_rejects_empty_string() -> None:
    """Cron delivery rejects blank chat ids with a descriptive error."""
    with pytest.raises(ValueError, match="invalid telegram chat_id"):
        parse_delivery_chat_id("   ")
