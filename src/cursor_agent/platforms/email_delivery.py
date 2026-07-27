"""Email outbound delivery via SMTP (plain text)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from cursor_agent.gateway.config import EmailPlatformConfig
from cursor_agent.platforms.base import OutboundMessage
from cursor_agent.platforms.email_chunking import parse_email_sender
from cursor_agent.platforms.email_smtp import (
    EmailThreadContext,
    SmtpClientFactory,
    build_reply_message,
    default_smtp_client_factory,
    domain_from_address,
    send_smtp_message,
)

# Soft limit for a single SMTP body part; split on paragraph/line boundaries.
EMAIL_MESSAGE_LIMIT = 100_000
EMAIL_FLUSH_THRESHOLD = 90_000


def split_plain_text_email(text: str) -> list[str]:
    """Split long assistant text into email-sized plain-text chunks."""
    if not text:
        return []
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= EMAIL_FLUSH_THRESHOLD:
            chunks.append(remaining)
            break
        window = remaining[:EMAIL_FLUSH_THRESHOLD]
        split_at = window.rfind("\n\n")
        if split_at == -1:
            split_at = window.rfind("\n")
        if split_at == -1:
            split_at = (
                EMAIL_MESSAGE_LIMIT
                if len(remaining) > EMAIL_MESSAGE_LIMIT
                else EMAIL_FLUSH_THRESHOLD
            )
        else:
            split_at = split_at + (
                2 if remaining[split_at : split_at + 2] == "\n\n" else 1
            )
        if split_at <= 0:
            split_at = min(EMAIL_FLUSH_THRESHOLD, len(remaining))
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks


class EmailDelivery:
    """Deliver outbound replies over SMTP using per-sender thread context."""

    def __init__(
        self,
        *,
        platform_config: EmailPlatformConfig,
        logger: logging.Logger,
        smtp_client_factory: SmtpClientFactory | None = None,
        thread_context_getter: Callable[[str], EmailThreadContext | None] | None = None,
    ) -> None:
        self._platform_config = platform_config
        self._logger = logger
        self._smtp_client_factory = smtp_client_factory or default_smtp_client_factory
        self._thread_context_getter = thread_context_getter or (lambda _sender: None)

    async def send_plain_reply(self, to_addr: str, text: str) -> None:
        """Send a plain-text reply to ``to_addr``, optionally threaded."""
        context = self._thread_context_getter(to_addr)
        subject = context.subject if context is not None else ""
        in_reply_to = context.message_id if context is not None else ""
        chunks = split_plain_text_email(text)
        for chunk in chunks:
            message = build_reply_message(
                from_addr=self._platform_config.address,
                to_addr=to_addr,
                subject=subject,
                body=chunk,
                in_reply_to=in_reply_to,
                domain=domain_from_address(self._platform_config.address),
            )
            # Keep sync smtplib off the gateway event loop (Telegram + email share it).
            await asyncio.to_thread(
                send_smtp_message,
                host=self._platform_config.smtp_host,
                port=self._platform_config.smtp_port,
                address=self._platform_config.address,
                password=self._platform_config.password,
                message=message,
                client_factory=self._smtp_client_factory,
            )
        self._logger.info(
            "email_outbound_sent platform=email to=%s chunks=%s",
            to_addr,
            len(chunks),
        )

    async def send_message(self, outbound: OutboundMessage) -> None:
        """Deliver an outbound gateway reply to the sender in ``session_key``."""
        to_addr = parse_email_sender(outbound.session_key)
        await self.send_plain_reply(to_addr, outbound.text)


__all__ = [
    "EMAIL_FLUSH_THRESHOLD",
    "EMAIL_MESSAGE_LIMIT",
    "EmailDelivery",
    "split_plain_text_email",
]
