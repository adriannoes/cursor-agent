"""Unit tests for IMAP RFC822 parsing helpers."""

from __future__ import annotations

from email.message import EmailMessage

from cursor_agent.platforms.email_imap import (
    build_prompt_text,
    build_sample_rfc822,
    extract_email_address,
    html_to_plain_text,
    is_noreply_sender,
    parse_rfc822_bytes,
)


def test_extract_email_address_from_angle_brackets() -> None:
    assert (
        extract_email_address("Alice Example <Alice@Example.com>")
        == "alice@example.com"
    )


def test_build_prompt_text_prefixes_non_reply_subject() -> None:
    assert build_prompt_text(subject="Hello", body_text="Body") == (
        "[Subject: Hello]\n\nBody"
    )


def test_build_prompt_text_skips_re_subject() -> None:
    assert build_prompt_text(subject="Re: Hello", body_text="Body") == "Body"


def test_parse_rfc822_plain_text() -> None:
    raw = build_sample_rfc822(
        from_addr="You <you@example.com>",
        to_addr="bot@agentmail.to",
        subject="Task",
        body="Please help",
        message_id="<abc@example.com>",
    )
    parsed = parse_rfc822_bytes("1", raw)
    assert parsed is not None
    assert parsed.sender == "you@example.com"
    assert parsed.subject == "Task"
    assert parsed.message_id == "<abc@example.com>"
    assert parsed.body_text == "Please help"
    assert "[Subject: Task]" in parsed.prompt_text


def test_parse_rfc822_html_only_falls_back() -> None:
    raw = build_sample_rfc822(
        from_addr="you@example.com",
        to_addr="bot@agentmail.to",
        subject="Re: prior",
        body="<p>Hello <b>world</b></p>",
        content_type="html",
    )
    parsed = parse_rfc822_bytes("2", raw)
    assert parsed is not None
    assert "Hello" in parsed.body_text
    assert "world" in parsed.body_text
    assert parsed.prompt_text == parsed.body_text


def test_parse_rfc822_skips_noreply() -> None:
    raw = build_sample_rfc822(
        from_addr="noreply@example.com",
        to_addr="bot@agentmail.to",
        subject="Notice",
        body="ignore me",
    )
    assert parse_rfc822_bytes("3", raw) is None


def test_parse_rfc822_skips_bulk_precedence() -> None:
    msg = EmailMessage()
    msg["From"] = "list@example.com"
    msg["To"] = "bot@agentmail.to"
    msg["Subject"] = "Digest"
    msg["Precedence"] = "bulk"
    msg.set_content("list traffic")
    assert parse_rfc822_bytes("4", msg.as_bytes()) is None


def test_parse_rfc822_skips_empty_body() -> None:
    raw = build_sample_rfc822(
        from_addr="you@example.com",
        to_addr="bot@agentmail.to",
        subject="",
        body="   ",
    )
    assert parse_rfc822_bytes("5", raw) is None


def test_is_noreply_sender() -> None:
    assert is_noreply_sender("no-reply@example.com") is True
    assert is_noreply_sender("you@example.com") is False


def test_html_to_plain_text_strips_tags() -> None:
    assert "Hi" in html_to_plain_text("<div>Hi</div>")
