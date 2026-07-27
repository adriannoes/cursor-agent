"""IMAP fetch and RFC822 parsing for the email platform adapter."""

from __future__ import annotations

import email
import email.policy
import imaplib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from email.message import EmailMessage, Message
from html.parser import HTMLParser
from typing import Protocol, cast

from cursor_agent.platforms.email_chunking import normalize_email_address

_NOREPLY_LOCAL_PART = re.compile(
    r"^(noreply|no-reply|mailer-daemon|postmaster)$",
    re.IGNORECASE,
)
_ANGLE_ADDR = re.compile(r"<([^>]+)>")


class ImapClientProtocol(Protocol):
    """Minimal IMAP client surface used by the email adapter."""

    def login(self, user: str, password: str) -> tuple[str, list[bytes]]: ...

    def select(
        self, mailbox: str = "INBOX", readonly: bool = False
    ) -> tuple[str, object]: ...

    def uid(
        self, command: str, *args: object
    ) -> tuple[str, list[bytes | None] | None]: ...

    def logout(self) -> tuple[str, object]: ...

    def close(self) -> tuple[str, object]: ...


ImapClientFactory = Callable[[str, int], ImapClientProtocol]


@dataclass(frozen=True, slots=True)
class ParsedInboundEmail:
    """Normalized inbound email fields for gateway handling."""

    uid: str
    sender: str
    subject: str
    message_id: str
    in_reply_to: str
    body_text: str
    prompt_text: str


class _HTMLToText(HTMLParser):
    """Minimal HTML → plain text extractor for HTML-only inbound mail."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip = True
        if tag in {"br", "p", "div", "tr", "li"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = False
        if tag in {"p", "div", "tr", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def default_imap_client_factory(host: str, port: int) -> ImapClientProtocol:
    """Create an IMAP4 SSL client for the given host and port."""
    return cast(ImapClientProtocol, imaplib.IMAP4_SSL(host, port))


def extract_email_address(raw_from: str) -> str:
    """Extract and normalize the address from a From header value."""
    stripped = raw_from.strip()
    if not stripped:
        return ""
    angle = _ANGLE_ADDR.search(stripped)
    if angle is not None:
        return normalize_email_address(angle.group(1))
    return normalize_email_address(stripped)


def html_to_plain_text(html: str) -> str:
    """Convert HTML body content to a rough plain-text equivalent."""
    parser = _HTMLToText()
    parser.feed(html)
    parser.close()
    lines = [line.strip() for line in parser.text().splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _decode_part_payload(part: Message) -> str:
    """Decode a single MIME part to text."""
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    if isinstance(payload, str):
        return payload
    return ""


def extract_body_text(message: Message) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    if message.is_multipart():
        plain_parts: list[str] = []
        html_parts: list[str] = []
        for part in message.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            payload = _decode_part_payload(part)
            if not payload:
                continue
            if content_type == "text/plain":
                plain_parts.append(payload)
            elif content_type == "text/html":
                html_parts.append(payload)
        if plain_parts:
            return "\n".join(plain_parts).strip()
        if html_parts:
            return html_to_plain_text("\n".join(html_parts))
        return ""

    content_type = message.get_content_type()
    payload = _decode_part_payload(message)
    if not payload:
        return ""
    if content_type == "text/html":
        return html_to_plain_text(payload)
    return payload.strip()


def build_prompt_text(*, subject: str, body_text: str) -> str:
    """Build agent prompt text, prefixing subject for non-reply mail."""
    body = body_text.strip()
    subject_stripped = subject.strip()
    if not subject_stripped:
        return body
    if subject_stripped.lower().startswith("re:"):
        return body
    if not body:
        return f"[Subject: {subject_stripped}]"
    return f"[Subject: {subject_stripped}]\n\n{body}"


def is_bulk_or_automated(message: Message) -> bool:
    """Return True for mail that should not start an agent turn.

    ``List-Unsubscribe`` alone is not treated as bulk: AgentMail and other
    transactional providers attach that header to ordinary one-to-one mail.
    """
    auto_submitted = (message.get("Auto-Submitted") or "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    precedence = (message.get("Precedence") or "").strip().lower()
    if precedence in {"bulk", "junk", "list"}:
        return True
    return False


def is_noreply_sender(sender: str) -> bool:
    """Return True when the local part looks like an automated noreply address."""
    local = sender.split("@", maxsplit=1)[0]
    return _NOREPLY_LOCAL_PART.match(local) is not None


def parse_rfc822_bytes(uid: str, raw: bytes) -> ParsedInboundEmail | None:
    """Parse an RFC822 payload into a ``ParsedInboundEmail``, or ``None`` to skip."""
    message = email.message_from_bytes(raw, policy=email.policy.default)
    sender = extract_email_address(message.get("From") or "")
    if not sender:
        return None
    if is_noreply_sender(sender):
        return None
    if is_bulk_or_automated(message):
        return None
    body_text = extract_body_text(message)
    subject = (message.get("Subject") or "").strip()
    message_id = (message.get("Message-ID") or message.get("Message-Id") or "").strip()
    in_reply_to = (message.get("In-Reply-To") or "").strip()
    prompt_text = build_prompt_text(subject=subject, body_text=body_text)
    if not prompt_text.strip():
        return None
    return ParsedInboundEmail(
        uid=uid,
        sender=sender,
        subject=subject,
        message_id=message_id,
        in_reply_to=in_reply_to,
        body_text=body_text,
        prompt_text=prompt_text,
    )


def _decode_uid_list(payload: Sequence[bytes | None] | None) -> list[str]:
    if not payload:
        return []
    uids: list[str] = []
    for item in payload:
        if item is None:
            continue
        text = item.decode("ascii", errors="ignore").strip()
        if not text:
            continue
        uids.extend(part for part in text.split() if part)
    return uids


def fetch_all_uids(client: ImapClientProtocol) -> list[str]:
    """Return all UIDs currently in INBOX."""
    status, data = client.uid("SEARCH", None, "ALL")
    if status != "OK":
        msg = f"IMAP UID SEARCH ALL failed: status={status!r}"
        raise RuntimeError(msg)
    return _decode_uid_list(data)


def fetch_seen_uids(client: ImapClientProtocol) -> list[str]:
    """Return UIDs for SEEN messages (used to seed the local seen-set on start)."""
    status, data = client.uid("SEARCH", None, "SEEN")
    if status != "OK":
        msg = f"IMAP UID SEARCH SEEN failed: status={status!r}"
        raise RuntimeError(msg)
    return _decode_uid_list(data)


def fetch_unseen_uids(client: ImapClientProtocol) -> list[str]:
    """Return UIDs for UNSEEN messages in INBOX."""
    status, data = client.uid("SEARCH", None, "UNSEEN")
    if status != "OK":
        msg = f"IMAP UID SEARCH UNSEEN failed: status={status!r}"
        raise RuntimeError(msg)
    return _decode_uid_list(data)


def fetch_message_rfc822(client: ImapClientProtocol, uid: str) -> bytes:
    """Fetch the full RFC822 body for a message UID."""
    status, data = client.uid("FETCH", uid, "(RFC822)")
    if status != "OK" or not data:
        msg = f"IMAP UID FETCH RFC822 failed: uid={uid!r}, status={status!r}"
        raise RuntimeError(msg)
    for item in data:
        if isinstance(item, tuple) and len(item) >= 2:
            payload = item[1]
            if isinstance(payload, bytes):
                return payload
        if isinstance(item, bytes) and item.startswith(b"RFC822"):
            continue
    msg = f"IMAP UID FETCH RFC822 returned no payload: uid={uid!r}"
    raise RuntimeError(msg)


def mark_seen(client: ImapClientProtocol, uid: str) -> None:
    """Mark a message UID as \\Seen."""
    status, _data = client.uid("STORE", uid, "+FLAGS", "(\\Seen)")
    if status != "OK":
        msg = f"IMAP UID STORE +FLAGS (\\Seen) failed: uid={uid!r}, status={status!r}"
        raise RuntimeError(msg)


def open_inbox(
    *,
    host: str,
    port: int,
    address: str,
    password: str,
    client_factory: ImapClientFactory,
) -> ImapClientProtocol:
    """Connect, log in, and select INBOX."""
    client = client_factory(host, port)
    login_status, _ = client.login(address, password)
    if login_status != "OK":
        msg = f"IMAP login failed: status={login_status!r}"
        raise RuntimeError(msg)
    select_status, _ = client.select("INBOX")
    if select_status != "OK":
        with_context_close(client)
        msg = f"IMAP SELECT INBOX failed: status={select_status!r}"
        raise RuntimeError(msg)
    return client


def with_context_close(client: ImapClientProtocol) -> None:
    """Best-effort close + logout for an IMAP client."""
    try:
        client.close()
    except Exception:
        pass
    try:
        client.logout()
    except Exception:
        pass


def build_sample_rfc822(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    body: str,
    message_id: str = "<msg-1@example.com>",
    content_type: str = "plain",
) -> bytes:
    """Build a minimal RFC822 message for unit tests."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if content_type == "html":
        msg.set_content(body, subtype="html")
    else:
        msg.set_content(body)
    return msg.as_bytes()


__all__ = [
    "ImapClientFactory",
    "ImapClientProtocol",
    "ParsedInboundEmail",
    "build_prompt_text",
    "build_sample_rfc822",
    "default_imap_client_factory",
    "extract_body_text",
    "extract_email_address",
    "fetch_all_uids",
    "fetch_message_rfc822",
    "fetch_seen_uids",
    "fetch_unseen_uids",
    "html_to_plain_text",
    "is_bulk_or_automated",
    "is_noreply_sender",
    "mark_seen",
    "open_inbox",
    "parse_rfc822_bytes",
    "with_context_close",
]
