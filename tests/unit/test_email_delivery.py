"""Unit tests for email outbound chunking and async SMTP offload."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from cursor_agent.platforms.email_delivery import (
    EMAIL_FLUSH_THRESHOLD,
    EmailDelivery,
    split_plain_text_email,
)

from tests.unit.email_adapter_fakes import FakeSmtpClient, email_platform_config


def test_split_plain_text_email_empty() -> None:
    assert split_plain_text_email("") == []


def test_split_plain_text_email_splits_on_paragraph_boundary() -> None:
    first = "a" * 100
    second = "b" * 100
    pad = "x" * (EMAIL_FLUSH_THRESHOLD - len(first) - 2)
    text = first + pad + "\n\n" + second
    chunks = split_plain_text_email(text)
    assert len(chunks) >= 2
    assert "".join(chunks) == text


async def test_send_plain_reply_offloads_smtp_to_thread(tmp_path: Path) -> None:
    """SMTP must not block the event loop (asyncio.to_thread)."""
    _ = tmp_path
    main_ident = threading.get_ident()
    send_threads: list[int] = []

    class ThreadTrackingSmtp(FakeSmtpClient):
        def send_message(self, msg, from_addr=None, to_addrs=None):  # type: ignore[no-untyped-def]
            send_threads.append(threading.get_ident())
            return super().send_message(msg, from_addr=from_addr, to_addrs=to_addrs)

    tracking = ThreadTrackingSmtp()
    delivery = EmailDelivery(
        platform_config=email_platform_config(),
        logger=logging.getLogger("test.email.delivery"),
        smtp_client_factory=lambda _h, _p: tracking,
    )
    await delivery.send_plain_reply("you@example.com", "hello")
    assert len(tracking.sent) == 1
    assert send_threads
    assert send_threads[0] != main_ident
