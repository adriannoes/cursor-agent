"""Workspace session prune selection (PRD-017 FR-4).

Kept separate from ``SessionStore`` so cron prune and workspace prune stay
distinct code paths (do not reuse ``prune_cron_sessions``).
"""

from __future__ import annotations

import aiosqlite


def validate_prune_workspace_params(
    older_than_days: int | None,
    keep_last: int | None,
) -> None:
    """Reject empty or negative prune criteria for workspace session hygiene.

    Example:
        >>> validate_prune_workspace_params(7, None)
    """
    if older_than_days is None and keep_last is None:
        raise ValueError(
            "invalid prune criteria: received older_than_days=None and "
            "keep_last=None, expected at least one of older_than_days|keep_last"
        )
    if older_than_days is not None and older_than_days < 0:
        raise ValueError(
            f"invalid older_than_days: received {older_than_days!r}, "
            "expected non-negative integer"
        )
    if keep_last is not None and keep_last < 0:
        raise ValueError(
            f"invalid keep_last: received {keep_last!r}, expected non-negative integer"
        )


def select_workspace_prune_target_ids(
    rows: list[aiosqlite.Row],
    *,
    older_than_days: int | None,
    keep_last: int | None,
    cutoff_iso: str | None,
) -> list[str]:
    """Select session ids to delete under OR semantics (age match ∪ outside keep).

    WHY (PRD-017 Q3): when both criteria are set, ``keep_last`` does **not**
    protect age-matched rows — a row inside the newest-N window is still deleted
    if ``updated_at`` is older than the cutoff.

    Example:
        >>> select_workspace_prune_target_ids(
        ...     rows, older_than_days=7, keep_last=None, cutoff_iso=cutoff
        ... )
    """
    outside_keep: set[str] = set()
    if keep_last is not None:
        outside_keep = {str(row["id"]) for row in rows[keep_last:]}

    age_match: set[str] = set()
    if older_than_days is not None:
        if cutoff_iso is None:
            raise ValueError(
                f"invalid prune cutoff: received cutoff_iso={cutoff_iso!r}, "
                "expected ISO-8601 timestamp when older_than_days is set"
            )
        age_match = {
            str(row["id"]) for row in rows if str(row["updated_at"]) < cutoff_iso
        }

    if older_than_days is not None and keep_last is not None:
        target_ids = age_match | outside_keep
    elif older_than_days is not None:
        target_ids = age_match
    else:
        target_ids = outside_keep

    # Preserve selection order (updated_at DESC, id DESC) for deterministic returns.
    return [str(row["id"]) for row in rows if str(row["id"]) in target_ids]
