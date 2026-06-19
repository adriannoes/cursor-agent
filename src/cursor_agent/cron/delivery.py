"""Optional post-run Telegram delivery for cron jobs (PRD-010, FR-11, FR-12)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from cursor_agent.cron.executor import CronJobRunOutcome, CronRunStatus
from cursor_agent.cron.models import CronJob
from cursor_agent.platforms.base import PlatformAdapter
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.platforms.telegram_formatting import (
    prepare_telegram_assistant_reply_chunks,
)

_MODULE_LOGGER = logging.getLogger(__name__)


class CronTelegramChunkSender(Protocol):
    """Send one Telegram HTML chunk for cron delivery (injectable in tests)."""

    async def send_html_chunk(self, chat_id: str, html: str) -> None:
        """Deliver a single HTML fragment to *chat_id*."""
        ...


@dataclass(frozen=True, slots=True)
class CronDeliveryOutcome:
    """Result of an optional cron Telegram delivery attempt.

    Delivery status is independent of ``CronJobRunOutcome.status``.
    """

    attempted: bool
    delivered: bool
    chunk_count: int = 0
    error_class: str | None = None


def build_cron_telegram_chunk_sender(
    adapters: Sequence[PlatformAdapter],
) -> CronTelegramChunkSender | None:
    """Return the registered Telegram adapter for cron HTML delivery, if any.

    Example:
        >>> sender = build_cron_telegram_chunk_sender(ctx.adapters)
    """
    for adapter in adapters:
        if isinstance(adapter, TelegramAdapter):
            return adapter
    return None


async def deliver_cron_result(
    job: CronJob,
    outcome: CronJobRunOutcome,
    *,
    chunk_sender: CronTelegramChunkSender | None = None,
    logger: logging.Logger | None = None,
) -> CronDeliveryOutcome:
    """Format and deliver a finished cron result to Telegram when configured.

    Uses ``prepare_telegram_assistant_reply_chunks()`` so raw Markdown is never
    sent to the Telegram API. Delivery failures are logged with job id and
    exception class only; they do not mutate ``outcome``.
    """
    effective_logger = logger or _MODULE_LOGGER
    if (
        job.delivery is None
        or job.delivery.telegram is None
        or outcome.status is not CronRunStatus.FINISHED
        or chunk_sender is None
    ):
        return CronDeliveryOutcome(attempted=False, delivered=False)

    result_text = outcome.result_text
    if result_text is None or not result_text.strip():
        return CronDeliveryOutcome(attempted=False, delivered=False)

    chat_id = job.delivery.telegram.chat_id
    chunks = prepare_telegram_assistant_reply_chunks(
        result_text,
        logger=effective_logger,
    )
    if not chunks:
        return CronDeliveryOutcome(attempted=True, delivered=True, chunk_count=0)

    try:
        for chunk in chunks:
            await chunk_sender.send_html_chunk(chat_id, chunk)
    except Exception as exc:
        effective_logger.warning(
            "cron_telegram_delivery_failed job_id=%s run_id=%s exception_class=%s",
            job.id,
            outcome.run_id,
            exc.__class__.__name__,
        )
        return CronDeliveryOutcome(
            attempted=True,
            delivered=False,
            chunk_count=0,
            error_class=exc.__class__.__name__,
        )

    effective_logger.info(
        "cron_telegram_delivery_sent job_id=%s run_id=%s chat_id=%s chunk_count=%s",
        job.id,
        outcome.run_id,
        chat_id,
        len(chunks),
    )
    return CronDeliveryOutcome(
        attempted=True,
        delivered=True,
        chunk_count=len(chunks),
    )


__all__ = [
    "CronDeliveryOutcome",
    "CronTelegramChunkSender",
    "build_cron_telegram_chunk_sender",
    "deliver_cron_result",
]
