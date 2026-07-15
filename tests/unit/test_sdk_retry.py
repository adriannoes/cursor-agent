"""Unit tests for ADR-024 retry helpers in sdk_retry."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from cursor_agent.sdk_retry import (
    RETRY_BACKOFF_CAP_SECONDS,
    RETRY_MAX_ATTEMPTS,
    is_retryable_error,
    parse_retry_after_seconds,
    retry_after_seconds,
    retry_sdk_call,
)


class _RetryableExc(Exception):
    is_retryable = True

    def __init__(self, message: str, *, retry_after: object | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _NonRetryableExc(Exception):
    is_retryable = False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, 12.0),
        (0, 0.0),
        (3.5, 3.5),
        ("2.5", 2.5),
        ("0", 0.0),
        (-1, None),
        ("-0.5", None),
        ("bad", None),
        (None, None),
        # bool subclasses int; keep ADR-024 behavior explicit.
        (True, 1.0),
        ([], None),
    ],
)
def test_parse_retry_after_seconds(value: object, expected: float | None) -> None:
    """Accept non-negative numbers/strings; reject negatives and junk."""
    assert parse_retry_after_seconds(value) == expected


def test_is_retryable_error_reads_attribute() -> None:
    """Only exceptions advertising ``is_retryable=True`` are retryable."""
    assert is_retryable_error(_RetryableExc("transient")) is True
    assert is_retryable_error(_NonRetryableExc("fatal")) is False
    assert is_retryable_error(Exception("plain")) is False


def test_retry_after_seconds_prefers_parsed_hint() -> None:
    """SDK ``retry_after`` hint wins over exponential backoff."""
    exc = _RetryableExc("rate limited", retry_after="5")
    assert retry_after_seconds(exc, attempt=99) == 5.0


@patch("cursor_agent.sdk_retry.random.uniform", return_value=0.1)
def test_retry_after_seconds_exponential_backoff_with_jitter(
    _uniform: object,
) -> None:
    """Without a hint, delay is ``2**attempt`` plus deterministic jitter."""
    exc = _RetryableExc("transient")
    assert retry_after_seconds(exc, attempt=0) == pytest.approx(1.1)
    assert retry_after_seconds(exc, attempt=1) == pytest.approx(2.1)
    assert retry_after_seconds(exc, attempt=2) == pytest.approx(4.1)


@patch("cursor_agent.sdk_retry.random.uniform", return_value=0.1)
def test_retry_after_seconds_caps_exponential_backoff(_uniform: object) -> None:
    """Backoff is capped at ``RETRY_BACKOFF_CAP_SECONDS`` before jitter."""
    exc = _RetryableExc("transient")
    delay = retry_after_seconds(exc, attempt=10)
    assert delay == pytest.approx(RETRY_BACKOFF_CAP_SECONDS + 0.1)


@pytest.mark.asyncio
async def test_retry_sdk_call_succeeds_after_retryable_failures() -> None:
    """Retryable failures sleep then succeed within ``RETRY_MAX_ATTEMPTS``."""
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < RETRY_MAX_ATTEMPTS:
            raise _RetryableExc("transient", retry_after=0.01)
        return "ok"

    with patch(
        "cursor_agent.sdk_retry.asyncio.sleep", new_callable=AsyncMock
    ) as sleep_mock:
        assert await retry_sdk_call(flaky) == "ok"

    assert attempts == RETRY_MAX_ATTEMPTS
    assert sleep_mock.await_count == RETRY_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_retry_sdk_call_raises_after_max_attempts() -> None:
    """Exhausted retryable failures re-raise the last error."""

    async def always_fail() -> str:
        raise _RetryableExc("still broken", retry_after=0.01)

    with patch(
        "cursor_agent.sdk_retry.asyncio.sleep", new_callable=AsyncMock
    ) as sleep_mock:
        with pytest.raises(_RetryableExc, match="still broken"):
            await retry_sdk_call(always_fail)

    assert sleep_mock.await_count == RETRY_MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_retry_sdk_call_does_not_retry_non_retryable() -> None:
    """Non-retryable errors raise immediately without sleeping."""

    async def fatal() -> str:
        raise _NonRetryableExc("auth failed")

    with patch(
        "cursor_agent.sdk_retry.asyncio.sleep", new_callable=AsyncMock
    ) as sleep_mock:
        with pytest.raises(_NonRetryableExc, match="auth failed"):
            await retry_sdk_call(fatal)

    sleep_mock.assert_not_awaited()
