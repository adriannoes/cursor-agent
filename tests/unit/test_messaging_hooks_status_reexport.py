"""Compatibility re-export of status API from messaging_hooks."""

from __future__ import annotations


def test_messaging_hooks_reexports_status_api() -> None:
    """Old import path keeps MessagingHooksStatusReport / messaging_hooks_status."""
    from cursor_agent import messaging_hooks
    from cursor_agent.messaging_hooks_status import (
        MessagingHooksStatusReport as CanonicalReport,
        messaging_hooks_status as canonical_status,
    )

    assert messaging_hooks.MessagingHooksStatusReport is CanonicalReport
    assert messaging_hooks.messaging_hooks_status is canonical_status
