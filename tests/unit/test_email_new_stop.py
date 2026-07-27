"""Unit tests for email /new and /stop slash commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

from cursor_agent.platforms.base import InboundMessage
from cursor_agent.platforms.email_chunking import email_session_key
from cursor_agent.platforms.email_commands import (
    EMAIL_NEW_CONFIRMATION,
    EMAIL_STOP_NO_SESSION,
    EMAIL_STOP_SUCCESS,
    parse_email_command,
)
from cursor_agent.sessions.models import SessionCreateParams

from tests.unit.email_adapter_fakes import (
    DEFAULT_SENDER,
    FakeImapClient,
    FakeSmtpClient,
    build_email_adapter,
    email_gateway_config,
)


def test_parse_email_command_from_body_first_line() -> None:
    assert parse_email_command(subject="Hello", body="/new\nmore") == "new"
    assert parse_email_command(subject="/help", body="") == "help"
    assert parse_email_command(subject="/help", body="  \n") == "help"
    # Free-text body wins over a leftover subject command (mail clients preserve subjects).
    assert parse_email_command(subject="/help", body="ignored") is None
    assert parse_email_command(subject="Hi", body="please help") is None


async def test_email_new_creates_session_and_confirms(tmp_path: Path) -> None:
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
    workspace = str((tmp_path / "ws").resolve())
    session_key = email_session_key(DEFAULT_SENDER, workspace)

    async def on_inbound(_message: InboundMessage) -> None:
        return None

    await adapter.start(on_inbound)
    await asyncio.sleep(0.02)
    imap.add_message("10", subject="/new", body="/new", unseen=True)
    await asyncio.sleep(0.05)
    await adapter.stop()

    row = await store.resolve(session_key)
    assert row is not None
    assert row.agent_id
    assert any(EMAIL_NEW_CONFIRMATION in m.get_content() for m in smtp.sent)


async def test_email_stop_cancels_agent(tmp_path: Path) -> None:
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

    async def on_inbound(_message: InboundMessage) -> None:
        return None

    await adapter.start(on_inbound)
    await asyncio.sleep(0.02)
    imap.add_message("11", body="/stop", unseen=True)
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert any(EMAIL_STOP_SUCCESS in m.get_content() for m in smtp.sent)


async def test_email_stop_without_session_sends_hint(tmp_path: Path) -> None:
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

    async def on_inbound(_message: InboundMessage) -> None:
        return None

    await adapter.start(on_inbound)
    await asyncio.sleep(0.02)
    imap.add_message("12", body="/stop", unseen=True)
    await asyncio.sleep(0.05)
    await adapter.stop()

    assert any(EMAIL_STOP_NO_SESSION in m.get_content() for m in smtp.sent)
