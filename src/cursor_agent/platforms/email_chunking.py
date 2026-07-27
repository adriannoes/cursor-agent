"""Pure email session-key helpers (ADR-004)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_SESSION_KEY_PATTERN = re.compile(
    r"^email:(?P<sender>[^:]+):(?P<hash>[0-9a-f]{8})$",
)


def email_workspace_hash(workspace: Path | str) -> str:
    """Return the first 8 hex chars of sha256(abs(workspace)).

    Example:
        >>> email_workspace_hash("/tmp/project")  # doctest: +SKIP
        'a1b2c3d4'
    """
    absolute = str(Path(workspace).resolve())
    return hashlib.sha256(absolute.encode()).hexdigest()[:8]


def normalize_email_address(address: str) -> str:
    """Normalize an email address for session keys and allowlist matching."""
    return address.strip().lower()


def email_session_key(sender: str, workspace: Path | str) -> str:
    """Build the email session key for a sender and workspace.

    Format: ``email:{sender}:{workspace_hash}``.

    Example:
        >>> email_session_key("you@example.com", "/tmp/project")  # doctest: +SKIP
        'email:you@example.com:a1b2c3d4'
    """
    normalized = normalize_email_address(sender)
    if not normalized:
        msg = (
            f"invalid email sender for session_key: received {sender!r}, "
            "expected non-empty address"
        )
        raise ValueError(msg)
    if ":" in normalized:
        msg = (
            f"invalid email sender for session_key: received {sender!r}, "
            "expected address without ':'"
        )
        raise ValueError(msg)
    workspace_hash = email_workspace_hash(workspace)
    return f"email:{normalized}:{workspace_hash}"


def parse_email_sender(session_key: str) -> str:
    """Extract the sender address from an email session key."""
    match = _SESSION_KEY_PATTERN.match(session_key)
    if match is None:
        msg = (
            "invalid email session_key for outbound delivery: "
            f"received {session_key!r}, expected "
            "'email:<sender>:<8-char-hex-workspace-hash>'"
        )
        raise ValueError(msg)
    return match.group("sender")


__all__ = [
    "email_session_key",
    "email_workspace_hash",
    "normalize_email_address",
    "parse_email_sender",
]
