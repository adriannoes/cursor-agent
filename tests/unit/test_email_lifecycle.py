"""Unit tests for EmailAdapter lifecycle and inbound mapping."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.email_chunking import email_session_key
from cursor_agent.sessions.models import SessionCreateParams

from tests.unit.email_adapter_fakes import (
    DEFAULT_SENDER,
    FakeImapClient,
    FakeSmtpClient,
    build_email_adapter,
    email_gateway_config,
)


async def test_email_adapter_start_seeds_seen_only_and_processes_pending_unseen(
    tmp_path: Path,
) -> None:
    """SEEN mail is skipped; UNSEEN that arrived while down is handled after restart."""
    imap = FakeImapClient()
    imap.add_message("1", body="already read", unseen=False)
    imap.add_message("2", body="pending while down", unseen=True)
    smtp = FakeSmtpClient()
    adapter, store, _facade, _cfg = build_email_adapter(
        tmp_path,
        imap_client=imap,
        smtp_client=smtp,
    )
    await store.initialize()
    received: list[InboundMessage] = []

    async def on_inbound(message: InboundMessage) -> None:
        received.append(message)

    await adapter.start(on_inbound)
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert received == []
    assert "1" in adapter._seen_uids  # noqa: SLF001
    # Pending UNSEEN is processed (no session → hint reply), not silently dropped.
    assert "2" in imap.seen or "2" in adapter._seen_uids  # noqa: SLF001
    assert len(smtp.sent) == 1


async def test_email_adapter_poll_delivers_new_unseen(
    tmp_path: Path,
) -> None:
    imap = FakeImapClient()
    smtp = FakeSmtpClient()
    gateway_cfg = email_gateway_config(workspace=str(tmp_path / "ws"))
    adapter, store, facade, cursor_cfg = build_email_adapter(
        tmp_path,
        gateway_cfg=gateway_cfg,
        imap_client=imap,
        smtp_client=smtp,
    )
    await store.initialize()
    workspace = str((tmp_path / "ws").resolve())
    session_key = email_session_key(DEFAULT_SENDER, workspace)
    agent_id = await facade.create_agent(
        workspace=workspace,
        model=cursor_cfg.model,
        tool_profile=cursor_cfg.tool_profile,
        runtime_mode=cursor_cfg.runtime.mode,
    )
    await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=cursor_cfg.runtime.mode,
            tool_profile=cursor_cfg.tool_profile,
            title=None,
        ),
    )

    received: list[InboundMessage] = []

    async def on_inbound(message: InboundMessage) -> None:
        received.append(message)

    await adapter.start(on_inbound)
    await asyncio.sleep(0.03)
    imap.add_message(
        "2",
        subject="Re: prior",
        body="new question",
        message_id="<new@example.com>",
        unseen=True,
    )
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert len(received) == 1
    assert received[0].platform == "email"
    assert received[0].sender_id == DEFAULT_SENDER
    assert received[0].session_key == session_key
    assert received[0].text == "new question"
    assert adapter.thread_context_for(DEFAULT_SENDER) is not None
    assert adapter.thread_context_for(DEFAULT_SENDER).message_id == "<new@example.com>"


async def test_email_adapter_stop_cancels_poll_task(tmp_path: Path) -> None:
    adapter, _store, _facade, _cfg = build_email_adapter(tmp_path)

    async def on_inbound(_message: InboundMessage) -> None:
        return None

    await adapter.start(on_inbound)
    assert adapter._poll_task is not None  # noqa: SLF001
    await adapter.stop()
    assert adapter._poll_task is None  # noqa: SLF001


async def test_email_adapter_ignores_blocked_sender(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    imap = FakeImapClient()
    smtp = FakeSmtpClient()
    gateway_cfg = email_gateway_config(
        workspace=str(tmp_path / "ws"),
        allowed_users=["other@example.com"],
    )
    adapter, _store, _facade, _cfg = build_email_adapter(
        tmp_path,
        gateway_cfg=gateway_cfg,
        imap_client=imap,
        smtp_client=smtp,
        logger_name="test.email.auth",
    )
    received: list[InboundMessage] = []

    async def on_inbound(message: InboundMessage) -> None:
        received.append(message)

    await adapter.start(on_inbound)
    await asyncio.sleep(0.02)
    imap.add_message("9", body="blocked", unseen=True)
    with caplog.at_level(logging.INFO, logger="test.email.auth"):
        await asyncio.sleep(0.05)
    await adapter.stop()

    assert received == []
    assert any("gateway_auth_blocked" in r.message for r in caplog.records)
