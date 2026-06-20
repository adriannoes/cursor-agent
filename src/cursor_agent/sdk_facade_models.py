"""Shared facade types for SDK send operations (no cursor_sdk import)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    """Terminal status for a facade run."""

    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RunResult:
    """Normalized result of a facade send operation."""

    run_id: str
    status: RunStatus
    text: str | None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class StreamCallbacks:
    """Optional streaming callbacks for assistant text and tool events."""

    on_assistant_text: Callable[[str], Awaitable[None]] | None = None
    on_tool_start: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
    on_tool_end: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
