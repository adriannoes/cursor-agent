"""Unit tests for email free-text and no-session hint behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.email_chunking import email_session_key
from cursor_agent.product_copy import EMAIL_NO_SESSION_HINT
from cursor_agent.sessions.models import SessionCreateParams

from tests.unit.email_adapter_fakes import (
    DEFAULT_SENDER,
    FakeImapClient,
    FakeSmtpClient,
    build_email_adapter,
    email_gateway_config,
)


async def test_email_free_text_without_session_sends_hint(
    tmp_path: Path,
) -> None:
    imap = FakeImapClient()
    smtp = FakeSmtpClient()
    gateway_cfg = email_gateway_config(workspace=str(tmp_path / "ws"))
    adapter, store, _facade, _cfg = build_email_adapter(
        tmp_path,
        gateway_cfg=gateway_cfg,
        imap_client=imap,
        smtp_client=smtp,
    )
    await store.initialize()
    received: list[InboundMessage] = []

    async def on_inbound(message: InboundMessage) -> None:
        received.append(message)

    await adapter.start(on_inbound)
    await asyncio.sleep(0.02)
    imap.add_message("3", body="hello without session", unseen=True)
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert received == []
    assert len(smtp.sent) == 1
    assert EMAIL_NO_SESSION_HINT in smtp.sent[0].get_content()


async def test_email_free_text_with_session_invokes_inbound(
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
    await asyncio.sleep(0.02)
    imap.add_message("4", subject="Re: x", body="continue", unseen=True)
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert len(received) == 1
    assert received[0].text == "continue"
