"""Unit tests for email allowlist authorization."""

from __future__ import annotations

from cursor_agent.gateway.auth import is_allowed_sender

from tests.unit.email_adapter_fakes import email_gateway_config


def test_is_allowed_sender_allows_listed_email_case_insensitive() -> None:
    config = email_gateway_config(allowed_users=["You@Example.com"])
    assert is_allowed_sender("email", "you@example.com", config) is True
    assert is_allowed_sender("email", "YOU@EXAMPLE.COM", config) is True


def test_is_allowed_sender_blocks_unlisted_email() -> None:
    config = email_gateway_config(allowed_users=["you@example.com"])
    assert is_allowed_sender("email", "other@example.com", config) is False


def test_is_allowed_sender_blocks_when_email_allowlist_empty() -> None:
    config = email_gateway_config(allowed_users=[])
    assert is_allowed_sender("email", "you@example.com", config) is False


def test_is_allowed_sender_email_platform_name_normalized() -> None:
    config = email_gateway_config(allowed_users=["you@example.com"])
    assert is_allowed_sender("Email", "you@example.com", config) is True
