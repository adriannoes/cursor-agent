"""Narrow shell tests for TelegramAdapter identity and presentation boundaries."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from pathlib import Path

import pytest

from cursor_agent.platforms.telegram import (
    TELEGRAM_HELP_TEXT,
    _parse_telegram_command,
)

from tests.unit.gateway_fakes import track_inbound
from tests.unit.telegram_adapter_fakes import FakeDispatcher, make_adapter

_TELEGRAM_ADAPTER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "cursor_agent"
    / "platforms"
    / "telegram.py"
)
_ADAPTER_MEMORY_BOUNDARY_PATTERN = re.compile(
    r"LocalMemoryStore|memory_injected|USER\.md|MEMORY\.md|/memory\b|memory_",
)


def test_telegram_adapter_platform_returns_telegram(tmp_path: object) -> None:
    """TelegramAdapter.platform must be exactly 'telegram'."""
    adapter, _, _ = make_adapter(tmp_path)
    assert adapter.platform == "telegram"


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


def test_telegram_adapter_source_has_no_memory_implementation() -> None:
    """Telegram adapter must not embed Memory v1 loader or injection logic."""
    source = _TELEGRAM_ADAPTER_SOURCE.read_text(encoding="utf-8")
    matches = _ADAPTER_MEMORY_BOUNDARY_PATTERN.findall(source)
    assert matches == [], (
        "telegram.py must stay presentation-agnostic; found forbidden memory symbols: "
        f"{matches!r}"
    )


def test_telegram_adapter_help_text_has_no_memory_command_copy() -> None:
    """Telegram help copy must not advertise memory-specific slash commands."""
    lowered = TELEGRAM_HELP_TEXT.lower()
    assert "/memory" not in lowered
    assert "user.md" not in lowered
    assert "memory.md" not in lowered
    assert "memory_injected" not in lowered


@pytest.mark.asyncio
async def test_telegram_polling_failure_logs_safe_metadata_and_reraises(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Polling crashes log exception class only and never leak the bot token."""
    secret_token = "bot777666:polling-secret-token"

    class RaisingDispatcher(FakeDispatcher):
        async def start_polling(self, bot: object, **kwargs: object) -> None:
            raise RuntimeError("polling boot failure")

    adapter, _fake_bot, _ = make_adapter(
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
async def test_telegram_polling_termination_logs_critical(
    tmp_path: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected polling termination surfaces a CRITICAL operator signal."""
    secret_token = "bot111000:supervision-secret-token"

    class RaisingDispatcher(FakeDispatcher):
        async def start_polling(self, bot: object, **kwargs: object) -> None:
            raise RuntimeError("telegram outage")

    adapter, _fake_bot, _ = make_adapter(
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
    adapter, _fake_bot, _ = make_adapter(tmp_path)
    caplog.set_level(logging.CRITICAL, logger="test.telegram.adapter")

    await adapter.start(track_inbound([]))
    await adapter.stop()
    await asyncio.sleep(0)

    combined = "\n".join(record.message for record in caplog.records)
    assert "telegram_polling_terminated" not in combined
