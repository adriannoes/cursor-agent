"""Live ``list_models`` integration (PRD-017 FR-7 stretch / Task 6.3).

Exercises the facade ephemeral catalog path against the real SDK.
Skips when ``CURSOR_API_KEY`` is unset or whitespace-only.
"""

from __future__ import annotations

import os

import pytest

from cursor_agent.first_party_models import recommended_agent_model_ids
from cursor_agent.sdk_facade import list_models


def _cursor_api_key_present() -> bool:
    """Return True when ``CURSOR_API_KEY`` is set to a non-empty (non-whitespace) value."""
    raw = os.getenv("CURSOR_API_KEY")
    return raw is not None and bool(raw.strip())


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _cursor_api_key_present(),
        reason="requires non-empty CURSOR_API_KEY",
    ),
]


async def test_list_models_live_catalog_non_empty_with_soft_ids() -> None:
    """Live catalog is non-empty; soft-catalog ids appear when Cursor still lists them.

    Soft ids from ``recommended_agent_model_ids()`` are asserted only when present
    in the live response — Cursor may retire an id without failing this test.
    Never prints the API key.
    """
    api_key = os.environ["CURSOR_API_KEY"].strip()
    rows = await list_models(api_key=api_key)

    assert rows, (
        f"expected non-empty live model catalog from list_models, got {len(rows)} rows"
    )

    live_ids = {entry.id for entry in rows}
    for soft_id in recommended_agent_model_ids():
        if soft_id not in live_ids:
            continue
        matches = [entry for entry in rows if entry.id == soft_id]
        assert matches, (
            f"soft-catalog id {soft_id!r} is in live catalog ids but missing "
            f"from list_models rows (live_ids sample={sorted(live_ids)[:5]!r})"
        )
        assert matches[0].display_name, (
            f"soft-catalog id {soft_id!r} must have a non-empty display_name, "
            f"got {matches[0].display_name!r}"
        )
