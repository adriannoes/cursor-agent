"""Tests for ADR-024 error taxonomy (CursorAgentError hierarchy)."""

from __future__ import annotations

import pytest

from cursor_agent.errors import (
    AgentBusyError,
    AuthError,
    ConfigError,
    CursorAgentError,
    InvalidAgentError,
    NetworkError,
    TimeoutError,
)

_CURSOR_AGENT_SUBCLASSES: tuple[type[CursorAgentError], ...] = (
    AuthError,
    ConfigError,
    NetworkError,
    TimeoutError,
    InvalidAgentError,
)


@pytest.mark.parametrize("error_cls", _CURSOR_AGENT_SUBCLASSES)
def test_subclass_inherits_from_cursor_agent_error(
    error_cls: type[CursorAgentError],
) -> None:
    """ADR-024 §1: facade errors form a single hierarchy under CursorAgentError."""
    assert issubclass(error_cls, CursorAgentError)
    assert issubclass(error_cls, Exception)


@pytest.mark.parametrize(
    ("error_cls", "expected_retryable"),
    [
        (AuthError, False),
        (ConfigError, False),
        (NetworkError, True),
        (TimeoutError, True),
        (InvalidAgentError, False),
    ],
)
def test_subclass_is_retryable_per_adr_024(
    error_cls: type[CursorAgentError],
    expected_retryable: bool,
) -> None:
    """ADR-024 §1: is_retryable drives facade retry policy."""
    err = error_cls("failure")
    assert err.is_retryable is expected_retryable


def test_retry_after_defaults_to_none() -> None:
    """ADR-024 §1: retry_after is optional upstream hint."""
    err = NetworkError("transient failure")
    assert err.retry_after is None


def test_retry_after_honored_when_provided() -> None:
    """ADR-024 §1: honor Retry-After or SDK equivalent when present."""
    err = NetworkError("rate limited", retry_after=12.5)
    assert err.retry_after == 12.5


def test_error_message_preserved() -> None:
    err = AuthError("invalid api key")
    assert str(err) == "invalid api key"


def test_agent_busy_error_is_not_cursor_agent_error() -> None:
    """ADR-024 §3: AgentBusyError is a shared type outside the facade hierarchy."""
    assert not issubclass(AgentBusyError, CursorAgentError)
    err = AgentBusyError("session busy")
    assert isinstance(err, Exception)
    assert not isinstance(err, CursorAgentError)


def test_agent_busy_error_docstring_documents_pool_only() -> None:
    """ADR-008: raised only by SessionAgentPool; facade must never raise it."""
    assert AgentBusyError.__doc__ is not None
    doc_lower = AgentBusyError.__doc__.lower()
    assert "pool" in doc_lower
    assert "facade" in doc_lower
    assert "never" in doc_lower or "not" in doc_lower
