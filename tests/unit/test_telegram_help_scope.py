"""Unit tests for Telegram /help, /start, and unsupported command scope (PRD-007)."""

from __future__ import annotations

import pytest

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.telegram import _parse_telegram_command
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT

from tests.unit.gateway_fakes import track_inbound
from tests.unit.telegram_adapter_fakes import registered_handler
from tests.unit.telegram_command_fakes import (
    command_message,
    make_command_adapter,
    seed_chat_session,
    start_command_adapter,
)


@pytest.mark.asyncio
async def test_telegram_help_lists_supported_commands(tmp_path: object) -> None:
    """Allowlisted /help lists /new, /stop, and /help."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await start_command_adapter(adapter, handles, track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/help"))

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
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await start_command_adapter(adapter, handles, track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/help"))

    body = str(fake_bot.send_message_calls[0]["text"]).lower()
    assert "/new" in body
    assert "start" in body or "reset" in body or "new conversation" in body
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_help_omits_unsupported_cli_commands(tmp_path: object) -> None:
    """Telegram /help must not advertise unsupported CLI-only commands."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await start_command_adapter(adapter, handles, track_inbound([]))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/help"))

    body = str(fake_bot.send_message_calls[0]["text"])
    for unsupported in (
        "/compress",
        "/model",
        "/retry",
        "/usage",
        "/memory",
        "/skills",
        "/canvas",
    ):
        assert unsupported not in body
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_memory_show_is_not_a_supported_command(
    tmp_path: object,
) -> None:
    """/memory show must not register as a Telegram slash command."""
    _ = tmp_path
    assert _parse_telegram_command("/memory show") is None
    assert _parse_telegram_command("/memory") is None


@pytest.mark.asyncio
async def test_telegram_memory_without_session_treated_as_free_text(
    tmp_path: object,
) -> None:
    """Unsupported /memory input without a session follows the free-text no-session path."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/memory show"))

    assert fake_bot.send_message_calls
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
    assert received == []
    await adapter.stop()


def test_telegram_memory_not_in_supported_command_scope() -> None:
    """Telegram command scope remains /new, /stop, /help, and /start only."""
    from cursor_agent.platforms.telegram import _SUPPORTED_TELEGRAM_COMMANDS

    assert _SUPPORTED_TELEGRAM_COMMANDS == frozenset({"new", "stop", "help", "start"})
    assert "memory" not in _SUPPORTED_TELEGRAM_COMMANDS


def test_telegram_skill_canvas_is_not_a_supported_command() -> None:
    """Skill invocations like /canvas are CLI-only — not Telegram commands."""
    assert _parse_telegram_command("/canvas") is None
    assert _parse_telegram_command("/canvas draft layout") is None
    assert _parse_telegram_command("/skills") is None


def test_telegram_skill_not_in_supported_command_scope() -> None:
    """Telegram command scope must not include skill names or /skills."""
    from cursor_agent.platforms.telegram import _SUPPORTED_TELEGRAM_COMMANDS

    assert "canvas" not in _SUPPORTED_TELEGRAM_COMMANDS
    assert "skills" not in _SUPPORTED_TELEGRAM_COMMANDS


@pytest.mark.asyncio
async def test_telegram_skill_canvas_with_session_stays_literal_free_text(
    tmp_path: object,
) -> None:
    """/canvas must not resolve as a skill on Telegram — CLI-only."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await seed_chat_session(handles)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/canvas"))

    assert received
    assert received[0].text == "/canvas"
    hint_calls = [
        call
        for call in fake_bot.send_message_calls
        if call.get("text") == TELEGRAM_NO_SESSION_HINT
    ]
    assert hint_calls == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_skill_canvas_without_session_treated_as_free_text(
    tmp_path: object,
) -> None:
    """Unsupported /canvas without a session follows the free-text no-session path."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/canvas"))

    assert fake_bot.send_message_calls
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
    assert received == []
    await adapter.stop()


@pytest.mark.asyncio
async def test_telegram_start_with_existing_session_sends_onboarding_hint(
    tmp_path: object,
) -> None:
    """Telegram's automatic /start command must not be forwarded to the agent."""
    adapter, fake_bot, fake_dispatcher, handles = make_command_adapter(tmp_path)
    await seed_chat_session(handles)
    received: list[InboundMessage] = []
    await start_command_adapter(adapter, handles, track_inbound(received))

    handler = await registered_handler(fake_dispatcher)
    await handler(command_message("/start"))

    assert received == []
    assert fake_bot.send_message_calls
    assert fake_bot.send_message_calls[0]["text"] == TELEGRAM_NO_SESSION_HINT
    await adapter.stop()
