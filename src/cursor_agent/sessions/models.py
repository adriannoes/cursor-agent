"""Pure session models and helpers (PRD-002 FR-2, FR-5)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_TITLE_MAX_LEN: Final[int] = 60
_TITLE_ELLIPSIS: Final[str] = "..."
_TITLE_BODY_MAX: Final[int] = _TITLE_MAX_LEN - len(_TITLE_ELLIPSIS)


def build_cli_session_key(cwd: Path | str, profile: str = "default") -> str:
    """Build CLI session_key as ``cli:{profile}:{workspace_hash}``.

    ``workspace_hash`` is the first 8 hex chars of ``sha256(abs(cwd))`` per ADR-004.

    Example:
        >>> build_cli_session_key("/tmp/project")
        'cli:default:...'
    """
    if not profile:
        raise ValueError(
            f"invalid profile: received {profile!r}, expected non-empty string"
        )
    absolute = str(Path(cwd).resolve())
    workspace_hash = hashlib.sha256(absolute.encode()).hexdigest()[:8]
    return f"cli:{profile}:{workspace_hash}"


def title_from_first_user_message(message: str) -> str:
    """Derive session title from the first user message (ADR-009).

    Strips whitespace, keeps messages up to 60 characters, and appends ``...``
    when truncated.

    Example:
        >>> title_from_first_user_message("  fix the bug  ")
        'fix the bug'
    """
    stripped = message.strip()
    if not stripped:
        raise ValueError(
            f"invalid message: received {message!r}, expected non-empty string after strip"
        )
    if len(stripped) <= _TITLE_MAX_LEN:
        return stripped
    return stripped[:_TITLE_BODY_MAX] + _TITLE_ELLIPSIS


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Persisted session row from SQLite."""

    id: str
    session_key: str
    agent_id: str
    title: str | None
    workspace: str
    runtime: str
    tool_profile: str
    created_at: str
    updated_at: str
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SessionCreateParams:
    """Inputs required to create a new session row."""

    session_key: str
    agent_id: str
    workspace: str
    runtime: str
    tool_profile: str = "coding"
    title: str | None = None
    metadata: dict[str, object] | None = None
