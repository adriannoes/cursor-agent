"""Unit tests for SMTP reply builders and threading headers."""

from __future__ import annotations

from cursor_agent.platforms.email_smtp import (
    build_reply_message,
    domain_from_address,
    reply_subject,
)


def test_reply_subject_adds_single_re_prefix() -> None:
    assert reply_subject("Hello") == "Re: Hello"
    assert reply_subject("Re: Hello") == "Re: Hello"
    assert reply_subject("RE: Hello") == "RE: Hello"


def test_domain_from_address() -> None:
    assert domain_from_address("bot@agentmail.to") == "agentmail.to"
    assert domain_from_address("nodomain") == "localhost"


def test_build_reply_message_sets_threading_headers() -> None:
    msg = build_reply_message(
        from_addr="bot@agentmail.to",
        to_addr="you@example.com",
        subject="Hello",
        body="Reply body",
        in_reply_to="<orig@example.com>",
        domain="agentmail.to",
    )
    assert msg["From"] == "bot@agentmail.to"
    assert msg["To"] == "you@example.com"
    assert msg["Subject"] == "Re: Hello"
    assert msg["In-Reply-To"] == "<orig@example.com>"
    assert msg["References"] == "<orig@example.com>"
    assert msg["Message-ID"] is not None
    assert "@agentmail.to>" in str(msg["Message-ID"])
    assert msg.get_content().strip() == "Reply body"


def test_build_reply_message_without_in_reply_to_omits_thread_headers() -> None:
    msg = build_reply_message(
        from_addr="bot@agentmail.to",
        to_addr="you@example.com",
        subject="Hello",
        body="Reply body",
        in_reply_to="",
        domain="agentmail.to",
    )
    assert msg.get("In-Reply-To") is None
    assert msg.get("References") is None
