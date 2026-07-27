"""SMTP outbound helpers for the email platform adapter."""

from __future__ import annotations

import smtplib
import ssl
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol, cast


class SmtpClientProtocol(Protocol):
    """Minimal SMTP client surface used by the email adapter."""

    def ehlo(self) -> object: ...

    def starttls(self, *, context: ssl.SSLContext | None = None) -> object: ...

    def login(self, user: str, password: str) -> tuple[int, bytes]: ...

    def send_message(
        self,
        msg: EmailMessage,
        from_addr: str | None = None,
        to_addrs: list[str] | None = None,
    ) -> dict[str, tuple[int, bytes]]: ...

    def quit(self) -> object: ...


SmtpClientFactory = Callable[[str, int], SmtpClientProtocol]


@dataclass(frozen=True, slots=True)
class EmailThreadContext:
    """Last inbound headers used to keep SMTP replies threaded."""

    subject: str
    message_id: str


def default_smtp_client_factory(host: str, port: int) -> SmtpClientProtocol:
    """Create an SMTP client; port 465 uses implicit SSL, others use plain SMTP."""
    if port == 465:
        return cast(
            SmtpClientProtocol,
            smtplib.SMTP_SSL(host, port, context=ssl.create_default_context()),
        )
    return cast(SmtpClientProtocol, smtplib.SMTP(host, port, timeout=60))


def reply_subject(subject: str) -> str:
    """Ensure a single ``Re:`` prefix on the reply subject."""
    stripped = subject.strip()
    if not stripped:
        return "Re: "
    if stripped.lower().startswith("re:"):
        return stripped
    return f"Re: {stripped}"


def build_reply_message(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    in_reply_to: str,
    domain: str,
) -> EmailMessage:
    """Build a plain-text SMTP reply with threading headers."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = reply_subject(subject)
    new_message_id = f"<cursor-agent-{uuid.uuid4().hex}@{domain}>"
    msg["Message-ID"] = new_message_id
    if in_reply_to.strip():
        msg["In-Reply-To"] = in_reply_to.strip()
        msg["References"] = in_reply_to.strip()
    msg.set_content(body)
    return msg


def domain_from_address(address: str) -> str:
    """Extract the domain portion of an email address for Message-ID generation."""
    if "@" not in address:
        return "localhost"
    return address.rsplit("@", maxsplit=1)[1].strip().lower() or "localhost"


def send_smtp_message(
    *,
    host: str,
    port: int,
    address: str,
    password: str,
    message: EmailMessage,
    client_factory: SmtpClientFactory,
) -> None:
    """Authenticate and send one outbound email via SMTP."""
    client = client_factory(host, port)
    try:
        if port != 465:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        client.login(address, password)
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:
            pass


__all__ = [
    "EmailThreadContext",
    "SmtpClientFactory",
    "SmtpClientProtocol",
    "build_reply_message",
    "default_smtp_client_factory",
    "domain_from_address",
    "reply_subject",
    "send_smtp_message",
]
