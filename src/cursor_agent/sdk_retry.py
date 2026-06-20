"""Retry and backoff helpers for pre-run SDK operations (no cursor_sdk import)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

_T = TypeVar("_T")
RETRY_MAX_ATTEMPTS = 3
RETRY_BACKOFF_CAP_SECONDS = 30.0


def is_retryable_error(exc: Exception) -> bool:
    """Return True when an exception advertises ADR-024 retry semantics."""
    return bool(getattr(exc, "is_retryable", False))


def parse_retry_after_seconds(value: object) -> float | None:
    """Parse retry_after hints from SDK strings or numeric seconds."""
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed >= 0:
            return parsed
    return None


def retry_after_seconds(exc: Exception, attempt: int) -> float:
    """Compute delay before the next retry attempt."""
    retry_after = parse_retry_after_seconds(getattr(exc, "retry_after", None))
    if retry_after is not None:
        return retry_after
    backoff = min(2**attempt, RETRY_BACKOFF_CAP_SECONDS)
    return float(backoff + random.uniform(0, 0.25))


async def retry_sdk_call(operation: Callable[[], Awaitable[_T]]) -> _T:
    """Retry a pre-run SDK operation up to three times when retryable."""
    last_error: Exception | None = None
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            return await operation()
        except Exception as exc:
            if not is_retryable_error(exc):
                raise
            last_error = exc
            if attempt == RETRY_MAX_ATTEMPTS - 1:
                break
            await asyncio.sleep(retry_after_seconds(exc, attempt))
    assert last_error is not None
    raise last_error
