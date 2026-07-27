"""Unit tests for email session_key helpers (ADR-004)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.platforms.email_chunking import (
    email_session_key,
    email_workspace_hash,
    normalize_email_address,
    parse_email_sender,
)


def test_normalize_email_address_lowercases_and_strips() -> None:
    assert normalize_email_address("  You@Example.COM ") == "you@example.com"


def test_email_session_key_format(tmp_path: Path) -> None:
    key = email_session_key("You@Example.com", tmp_path)
    workspace_hash = email_workspace_hash(tmp_path)
    assert key == f"email:you@example.com:{workspace_hash}"


def test_parse_email_sender_round_trip(tmp_path: Path) -> None:
    key = email_session_key("alice@example.com", tmp_path)
    assert parse_email_sender(key) == "alice@example.com"


def test_parse_email_sender_rejects_invalid_key() -> None:
    with pytest.raises(ValueError, match="invalid email session_key"):
        parse_email_sender("telegram:123:abcdef01")


def test_email_session_key_rejects_empty_sender() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        email_session_key("  ", "/tmp/ws")


def test_email_session_key_rejects_colon_in_sender() -> None:
    with pytest.raises(ValueError, match="without ':'"):
        email_session_key("bad:addr@example.com", "/tmp/ws")
