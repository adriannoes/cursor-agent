"""Unit tests for optional cron Telegram delivery (PRD-010 FR-11, FR-12)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from unittest.mock import patch

import pytest

from cursor_agent.cron.delivery import (
    build_cron_telegram_chunk_sender,
    deliver_cron_result,
)
from cursor_agent.platforms.telegram import TelegramAdapter

from tests.unit.gateway_fakes import FakePlatformAdapter
from tests.unit.test_telegram_adapter import _make_adapter
from cursor_agent.cron.executor import CronJobRunOutcome, CronRunStatus
from cursor_agent.cron.models import CronJob
from cursor_agent.platforms.telegram_chunking import TELEGRAM_MESSAGE_LIMIT
from cursor_agent.platforms.telegram_formatting import (
    prepare_telegram_assistant_reply_chunks,
)

_SUPPORTED_TAG_PATTERN = re.compile(
    r"</?(?:b|code|pre|a)(?:\s[^>]*)?>",
    re.IGNORECASE,
)


def _assert_balanced_supported_tags(fragment: str) -> None:
    """Assert supported Telegram HTML tags are balanced in *fragment*."""
    stack: list[str] = []
    for match in _SUPPORTED_TAG_PATTERN.finditer(fragment):
        token = match.group(0)
        if token.startswith("</"):
            tag = token[2:-1].lower()
            assert stack, f"unexpected closing tag {token!r} in {fragment!r}"
            assert stack[-1] == tag, (
                f"mismatched closing tag {token!r}, expected </{stack[-1]}>"
            )
            stack.pop()
        else:
            tag = token[1:].split(maxsplit=1)[0].rstrip(">").lower()
            stack.append(tag)
    assert not stack, f"unclosed tags {stack!r} in {fragment!r}"


def _assert_telegram_html_chunk_valid(fragment: str) -> None:
    """Assert a chunk is structurally valid for Telegram parse_mode=HTML."""
    assert len(fragment) <= TELEGRAM_MESSAGE_LIMIT, (
        f"chunk length {len(fragment)!r} exceeds Telegram limit {TELEGRAM_MESSAGE_LIMIT}"
    )
    _assert_balanced_supported_tags(fragment)
    open_anchor_count = len(re.findall(r"<a\s", fragment, flags=re.IGNORECASE))
    close_anchor_count = fragment.lower().count("</a>")
    assert open_anchor_count == close_anchor_count, (
        f"anchor tag count mismatch: open={open_anchor_count!r}, "
        f"close={close_anchor_count!r} in {fragment[-120:]!r}"
    )


def _build_long_two_column_markdown_table(row_count: int) -> str:
    """Build a long two-column table fixture (shared with test_telegram_formatting)."""
    rows = [
        (
            f"| Critério {index} (install → run) | "
            f"Alta com `a|b` e [link](https://example.com/path/{index}) |"
        )
        for index in range(row_count)
    ]
    return "Critério | Nota |\n| --- | --- |\n" + "\n".join(rows)


class TelegramBadRequest(Exception):
    """Test double for aiogram Telegram API parse failures."""


@dataclass
class FakeCronTelegramChunkSender:
    """Records HTML chunk sends for cron delivery tests."""

    send_calls: list[dict[str, object]] = field(default_factory=list)
    fail_on_call: int | None = None
    failure_exception: Exception = field(
        default_factory=lambda: TelegramBadRequest("can't parse entities")
    )

    async def send_html_chunk(self, chat_id: str, html: str) -> None:
        call_index = len(self.send_calls)
        self.send_calls.append({"chat_id": chat_id, "html": html})
        if self.fail_on_call is not None and call_index == self.fail_on_call:
            raise self.failure_exception


@pytest.fixture
def telegram_cron_job() -> CronJob:
    """Cron job with Telegram delivery configured."""
    return CronJob.model_validate(
        {
            "id": "daily-report",
            "schedule": "0 9 * * *",
            "prompt": "Summarize open tasks.",
            "delivery": {"telegram": {"chat_id": "123456789"}},
        }
    )


@pytest.fixture
def finished_outcome(telegram_cron_job: CronJob) -> CronJobRunOutcome:
    """Successful cron run outcome with assistant result text."""
    return CronJobRunOutcome(
        job_id=telegram_cron_job.id,
        run_id="run-abc123",
        session_id="session-1",
        session_key="cron:daily-report:run-abc123",
        status=CronRunStatus.FINISHED,
        result_text="**Daily report**\n\nAll tasks complete.",
    )


@pytest.mark.asyncio
async def test_deliver_cron_result_calls_formatter(
    telegram_cron_job: CronJob,
    finished_outcome: CronJobRunOutcome,
) -> None:
    """Delivery must format assistant Markdown before sending HTML chunks."""
    sender = FakeCronTelegramChunkSender()
    with patch(
        "cursor_agent.cron.delivery.prepare_telegram_assistant_reply_chunks",
        wraps=prepare_telegram_assistant_reply_chunks,
    ) as formatter:
        delivery_outcome = await deliver_cron_result(
            telegram_cron_job,
            finished_outcome,
            chunk_sender=sender,
        )

    formatter.assert_called_once()
    assert formatter.call_args.args[0] == finished_outcome.result_text
    assert delivery_outcome.delivered is True
    assert delivery_outcome.chunk_count == len(sender.send_calls)


@pytest.mark.asyncio
async def test_deliver_cron_result_sends_valid_html_chunks_for_long_table(
    telegram_cron_job: CronJob,
) -> None:
    """Long table+link cron output must produce Telegram-safe HTML chunks."""
    result_text = _build_long_two_column_markdown_table(row_count=80)
    outcome = CronJobRunOutcome(
        job_id=telegram_cron_job.id,
        run_id="run-table",
        session_id="session-2",
        session_key="cron:daily-report:run-table",
        status=CronRunStatus.FINISHED,
        result_text=result_text,
    )
    sender = FakeCronTelegramChunkSender()

    delivery_outcome = await deliver_cron_result(
        telegram_cron_job,
        outcome,
        chunk_sender=sender,
    )

    assert delivery_outcome.delivered is True
    assert delivery_outcome.chunk_count >= 2
    for call in sender.send_calls:
        html = str(call["html"])
        _assert_telegram_html_chunk_valid(html)
        assert "<" in html
    combined = "".join(str(call["html"]) for call in sender.send_calls)
    assert '<a href="https://example.com/path/0">link</a>' in combined


@pytest.mark.asyncio
async def test_deliver_cron_result_telegram_bad_request_leaves_run_successful(
    telegram_cron_job: CronJob,
    finished_outcome: CronJobRunOutcome,
) -> None:
    """Telegram delivery failure must not change the cron run outcome status."""
    sender = FakeCronTelegramChunkSender(
        fail_on_call=0,
        failure_exception=TelegramBadRequest("can't parse entities"),
    )

    delivery_outcome = await deliver_cron_result(
        telegram_cron_job,
        finished_outcome,
        chunk_sender=sender,
    )

    assert finished_outcome.status is CronRunStatus.FINISHED
    assert delivery_outcome.attempted is True
    assert delivery_outcome.delivered is False
    assert delivery_outcome.error_class == "TelegramBadRequest"


@pytest.mark.asyncio
async def test_deliver_cron_result_logs_omit_prompt_and_result_body(
    telegram_cron_job: CronJob,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Delivery failure logs must not include job prompt or assistant output."""
    secret_prompt = telegram_cron_job.prompt
    secret_result = "super-secret-assistant-output-with-table-data"
    outcome = CronJobRunOutcome(
        job_id=telegram_cron_job.id,
        run_id="run-log",
        session_id="session-3",
        session_key="cron:daily-report:run-log",
        status=CronRunStatus.FINISHED,
        result_text=secret_result,
    )
    sender = FakeCronTelegramChunkSender(
        fail_on_call=0,
        failure_exception=RuntimeError("telegram api unavailable"),
    )
    caplog.set_level(logging.WARNING)

    await deliver_cron_result(
        telegram_cron_job,
        outcome,
        chunk_sender=sender,
        logger=logging.getLogger("test.cron.delivery"),
    )

    combined = "\n".join(record.message for record in caplog.records)
    assert secret_prompt not in combined
    assert secret_result not in combined
    assert telegram_cron_job.id in combined
    assert "RuntimeError" in combined


@pytest.mark.asyncio
async def test_deliver_cron_result_skips_when_telegram_not_configured(
    finished_outcome: CronJobRunOutcome,
) -> None:
    """Jobs without delivery.telegram.chat_id must not attempt Telegram sends."""
    job = CronJob.model_validate(
        {
            "id": "no-delivery",
            "schedule": "0 9 * * *",
            "prompt": "No delivery.",
        }
    )
    sender = FakeCronTelegramChunkSender()

    delivery_outcome = await deliver_cron_result(
        job,
        finished_outcome,
        chunk_sender=sender,
    )

    assert delivery_outcome.attempted is False
    assert delivery_outcome.delivered is False
    assert sender.send_calls == []


@pytest.mark.asyncio
async def test_deliver_cron_result_skips_when_run_not_finished(
    telegram_cron_job: CronJob,
) -> None:
    """Non-finished cron runs must not attempt Telegram delivery."""
    outcome = CronJobRunOutcome(
        job_id=telegram_cron_job.id,
        run_id="run-busy",
        session_id="session-4",
        session_key="cron:daily-report:run-busy",
        status=CronRunStatus.BUSY,
        error_message="agent busy",
    )
    sender = FakeCronTelegramChunkSender()

    delivery_outcome = await deliver_cron_result(
        telegram_cron_job,
        outcome,
        chunk_sender=sender,
    )

    assert delivery_outcome.attempted is False
    assert sender.send_calls == []


def test_build_cron_telegram_chunk_sender_returns_telegram_adapter(
    tmp_path: object,
) -> None:
    """Production bridge resolves the registered Telegram adapter as chunk sender."""
    adapter, _fake_bot, _fake_dispatcher = _make_adapter(tmp_path)
    sender = build_cron_telegram_chunk_sender([adapter])
    assert isinstance(sender, TelegramAdapter)
    assert sender is adapter


def test_build_cron_telegram_chunk_sender_none_without_telegram() -> None:
    """Gateway startup without Telegram adapter skips cron delivery safely."""
    sender = build_cron_telegram_chunk_sender([FakePlatformAdapter()])
    assert sender is None


@pytest.mark.asyncio
async def test_telegram_cron_chunk_sender_sends_preformatted_html(
    tmp_path: object,
) -> None:
    """Cron chunk sender must send HTML parse mode without re-formatting Markdown."""
    adapter, fake_bot, _fake_dispatcher = _make_adapter(tmp_path)
    sender = build_cron_telegram_chunk_sender([adapter])
    assert sender is not None

    await sender.send_html_chunk("444555666", "<b>preformatted</b>")

    assert len(fake_bot.send_message_calls) == 1
    call = fake_bot.send_message_calls[0]
    assert call["chat_id"] == 444555666
    assert call["parse_mode"] == "HTML"
    assert call["text"] == "<b>preformatted</b>"


@pytest.mark.asyncio
async def test_deliver_cron_result_skips_when_chunk_sender_missing(
    telegram_cron_job: CronJob,
    finished_outcome: CronJobRunOutcome,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Configured delivery without a sender must skip safely (Telegram optional)."""
    caplog.set_level(logging.INFO)

    delivery_outcome = await deliver_cron_result(
        telegram_cron_job,
        finished_outcome,
        chunk_sender=None,
        logger=logging.getLogger("test.cron.delivery"),
    )

    assert delivery_outcome.attempted is False
    assert delivery_outcome.delivered is False
