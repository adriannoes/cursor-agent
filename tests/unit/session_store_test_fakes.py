"""Shared clock fakes and store bootstrap for SessionStore unit tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from cursor_agent.sessions.store import SessionStore


def iso_utc(dt: datetime) -> str:
    """Format datetime as UTC ISO-8601."""
    return dt.astimezone(UTC).isoformat()


class SteppingClock:
    """Return predetermined UTC timestamps for deterministic store tests."""

    def __init__(self, times: list[datetime]) -> None:
        self._times: Iterator[datetime] = iter(times)

    def __call__(self) -> datetime:
        return next(self._times)


class FrozenClock:
    """Return the same UTC timestamp for every call (tie-breaker tests)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def __call__(self) -> datetime:
        return self._moment


async def initialized_store(
    tmp_path: Path,
    clock: SteppingClock | FrozenClock,
) -> SessionStore:
    """Return an initialized SessionStore with injected clock."""
    store = SessionStore(tmp_path / "sessions.db", clock=clock)
    await store.initialize()
    return store
