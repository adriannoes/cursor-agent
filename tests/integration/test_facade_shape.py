"""Facade integration shape tests (PRD-001 task 3.4).

Documents real SDK 0.1.7 attributes observed through ``AsyncSdkFacade``.
Reuses the smoke pattern from ``test_sdk_smoke.py``; skip without API key.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cursor_agent.sdk_facade import AsyncSdkFacade, RunStatus

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("CURSOR_API_KEY"),
        reason="requires CURSOR_API_KEY",
    ),
]

MODEL = "composer-2.5"
MINIMAL_PROMPT = "Reply with the single word OK."

# SDK 0.1.7 shapes observed through the facade adapter:
# - ``create_agent`` returns ``agent.agent_id`` (non-empty str).
# - ``run.wait()`` returns ``RunResult`` with ``id`` (not ``run_id``), ``status``,
#   ``result`` (assistant text), and ``duration_ms`` (int). No ``usage`` dict.
# - Facade maps ``id`` -> ``RunResult.run_id`` and ``duration_ms`` ->
#   ``usage={"duration_ms": N}`` when present.


def repo_root() -> Path:
    """Return the repository root directory for local agent workspace."""
    return Path(__file__).resolve().parents[2]


async def test_facade_send_run_result_shape() -> None:
    """AsyncSdkFacade maps live SDK wait payload onto stable RunResult fields."""
    workspace = str(repo_root())
    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        agent_id = await facade.create_agent(workspace=workspace, model=MODEL)
        assert isinstance(agent_id, str) and agent_id

        result = await facade.send(agent_id, MINIMAL_PROMPT)

    assert result.status is RunStatus.FINISHED
    assert result.run_id
    assert result.text
    if result.usage is not None:
        assert isinstance(result.usage.get("duration_ms"), int)
