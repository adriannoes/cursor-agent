"""Shared fakes for email IMAP/SMTP adapter unit tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import (
    EmailPlatformConfig,
    GatewayConfig,
    PlatformsConfig,
    TelegramPlatformConfig,
    resolve_gateway_startup_config,
)
from cursor_agent.platforms.email import EmailAdapter
from cursor_agent.platforms.email_imap import build_sample_rfc822
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

DEFAULT_SENDER = "you@example.com"
DEFAULT_BOT_ADDRESS = "bot@agentmail.to"
DEFAULT_WORKSPACE = "/tmp/gateway-workspace"


@dataclass
class FakeImapClient:
    """In-memory IMAP client for unit tests."""

    uids: dict[str, bytes] = field(default_factory=dict)
    unseen: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    logged_in: bool = False
    selected: bool = False
    closed: bool = False
    logged_out: bool = False

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]:
        _ = (user, password)
        self.logged_in = True
        return ("OK", [b"LOGIN completed"])

    def select(
        self, mailbox: str = "INBOX", readonly: bool = False
    ) -> tuple[str, list[bytes]]:
        _ = (mailbox, readonly)
        self.selected = True
        return ("OK", [b"1"])

    def uid(self, command: str, *args: object) -> tuple[str, list[Any]]:
        cmd = command.upper()
        if cmd == "SEARCH":
            criteria = " ".join(str(a) for a in args if a is not None).upper()
            if "UNSEEN" in criteria:
                matched = sorted(self.unseen)
            elif "SEEN" in criteria:
                matched = sorted(self.seen)
            else:
                matched = sorted(self.uids)
            return ("OK", [" ".join(matched).encode("ascii") if matched else None])
        if cmd == "FETCH":
            uid = str(args[0])
            raw = self.uids.get(uid)
            if raw is None:
                return ("NO", [])
            return ("OK", [(f"{uid} (RFC822)".encode("ascii"), raw)])
        if cmd == "STORE":
            uid = str(args[0])
            self.unseen.discard(uid)
            self.seen.add(uid)
            return ("OK", [])
        return ("NO", [])

    def close(self) -> tuple[str, list[bytes]]:
        self.closed = True
        return ("OK", [])

    def logout(self) -> tuple[str, list[bytes]]:
        self.logged_out = True
        return ("OK", [b"BYE"])

    def add_message(
        self,
        uid: str,
        *,
        from_addr: str = DEFAULT_SENDER,
        subject: str = "Hello",
        body: str = "Hi there",
        message_id: str = "<msg-1@example.com>",
        unseen: bool = True,
        content_type: str = "plain",
    ) -> None:
        self.uids[uid] = build_sample_rfc822(
            from_addr=from_addr,
            to_addr=DEFAULT_BOT_ADDRESS,
            subject=subject,
            body=body,
            message_id=message_id,
            content_type=content_type,
        )
        if unseen:
            self.unseen.add(uid)
        else:
            self.seen.add(uid)


@dataclass
class FakeSmtpClient:
    """In-memory SMTP client that records sent messages."""

    sent: list[EmailMessage] = field(default_factory=list)
    logged_in: bool = False
    started_tls: bool = False
    quit_called: bool = False

    def ehlo(self) -> object:
        return (250, b"ok")

    def starttls(self, *, context: object = None) -> object:
        _ = context
        self.started_tls = True
        return (220, b"ready")

    def login(self, user: str, password: str) -> tuple[int, bytes]:
        _ = (user, password)
        self.logged_in = True
        return (235, b"ok")

    def send_message(
        self,
        msg: EmailMessage,
        from_addr: str | None = None,
        to_addrs: list[str] | None = None,
    ) -> dict[str, tuple[int, bytes]]:
        _ = (from_addr, to_addrs)
        self.sent.append(msg)
        return {}

    def quit(self) -> object:
        self.quit_called = True
        return (221, b"bye")


def email_platform_config(
    *,
    enabled: bool = True,
    address: str = DEFAULT_BOT_ADDRESS,
    password: str = "am_test_password",
    allowed_users: list[str] | None = None,
    poll_interval_seconds: float = 0.01,
    smtp_port: int = 465,
) -> EmailPlatformConfig:
    users = allowed_users if allowed_users is not None else [DEFAULT_SENDER]
    return EmailPlatformConfig(
        enabled=enabled,
        address=address,
        password=password,
        imap_host="imap.agentmail.to",
        imap_port=993,
        smtp_host="smtp.agentmail.to",
        smtp_port=smtp_port,
        poll_interval_seconds=poll_interval_seconds,
        allowed_users=users,
    )


def email_gateway_config(
    *,
    workspace: str = DEFAULT_WORKSPACE,
    allowed_users: list[str] | None = None,
    email_enabled: bool = True,
    telegram_enabled: bool = False,
) -> GatewayConfig:
    return GatewayConfig(
        workspace=workspace,
        tool_profile="messaging",
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(
                enabled=telegram_enabled,
                bot_token="bot-token" if telegram_enabled else "",
                allowed_users=[123456789] if telegram_enabled else [],
            ),
            email=email_platform_config(
                enabled=email_enabled,
                allowed_users=allowed_users,
            ),
        ),
    )


def build_email_adapter(
    tmp_path: Path,
    *,
    gateway_cfg: GatewayConfig | None = None,
    imap_client: FakeImapClient | None = None,
    smtp_client: FakeSmtpClient | None = None,
    logger_name: str = "test.email.adapter",
) -> tuple[EmailAdapter, SessionStore, FakeSdkFacade, CursorAgentConfig]:
    """Construct an EmailAdapter with injectable IMAP/SMTP fakes."""
    cfg = gateway_cfg or email_gateway_config(workspace=str(tmp_path / "ws"))
    cursor_cfg = resolve_gateway_startup_config(cfg)
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    imap = imap_client or FakeImapClient()
    smtp = smtp_client or FakeSmtpClient()

    def imap_factory(host: str, port: int) -> FakeImapClient:
        _ = (host, port)
        return imap

    def smtp_factory(host: str, port: int) -> FakeSmtpClient:
        _ = (host, port)
        return smtp

    adapter = EmailAdapter(
        platform_config=cfg.platforms.email,
        gateway_config=cfg,
        config=cursor_cfg,
        store=store,
        facade=facade,
        logger=logging.getLogger(logger_name),
        imap_client_factory=imap_factory,
        smtp_client_factory=smtp_factory,
    )
    return adapter, store, facade, cursor_cfg
