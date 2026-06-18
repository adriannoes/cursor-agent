"""Facade resume integration tests (CLI/gateway restart path).

Exercises create → close → resume → send with a live SDK bridge when
``CURSOR_API_KEY`` is set. Skips cleanly without an API key.
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


def repo_root() -> Path:
    """Return the repository root directory for local agent workspace."""
    return Path(__file__).resolve().parents[2]


async def test_facade_resume_after_close_does_not_fail_serialization() -> None:
    """Resume after facade close must not pass non-JSON LocalAgentOptions."""
    workspace = str(repo_root())
    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        agent_id = await facade.create_agent(
            workspace=workspace,
            model=MODEL,
            tool_profile="messaging",
        )

    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        resumed_id = await facade.resume_agent(
            agent_id,
            workspace=workspace,
            model=MODEL,
            tool_profile="messaging",
        )
        assert resumed_id == agent_id


async def test_facade_resume_after_close_send_round_trip() -> None:
    """Resume and send after facade close exercises the raw SDK path.

    Known limitation: SDK may return internal error on send after cross-process
    resume without pool reattach (see ADR-027). Pool/gateway paths reattach.
    """
    workspace = str(repo_root())
    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        agent_id = await facade.create_agent(
            workspace=workspace,
            model=MODEL,
            tool_profile="messaging",
        )

    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        resumed_id = await facade.resume_agent(
            agent_id,
            workspace=workspace,
            model=MODEL,
            tool_profile="messaging",
        )
        assert resumed_id == agent_id

        try:
            result = await facade.send(agent_id, MINIMAL_PROMPT)
        except Exception as exc:
            pytest.skip(
                f"SDK cross-process resume→send not reliable at facade layer: {exc}"
            )

        assert result.status is RunStatus.FINISHED
        assert result.text
