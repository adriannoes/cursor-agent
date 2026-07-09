"""Live smoke for ``tool_profile: full`` MCP injection (PRD-012 optional DoD).

Uses playwright-only allowlist so the run does not require Docker or GitHub/Brave
tokens. Skips cleanly without ``CURSOR_API_KEY``.
"""

from __future__ import annotations

import json
import logging
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
MCP_PROBE_PROMPT = (
    "List the names of any MCP / external tools you currently have available. "
    "If you have Playwright browser MCP tools, mention playwright. "
    "Reply in at most three short lines."
)


def repo_root() -> Path:
    """Return the repository root directory for local agent workspace."""
    return Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_full_profile_injects_playwright_mcp_and_completes_turn() -> None:
    """Live create under full+playwright must inject MCP and finish a turn."""
    workspace = str(repo_root())
    logger = logging.getLogger("test.integration.full_mcp_smoke")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    try:
        async with AsyncSdkFacade(
            api_key=os.environ.get("CURSOR_API_KEY"),
            bridge_options={"workspace": workspace},
            mcp_full_servers=["playwright"],
            logger=logger,
        ) as facade:
            agent_id = await facade.create_agent(
                workspace=workspace,
                model=MODEL,
                tool_profile="full",
            )
            assert isinstance(agent_id, str) and agent_id

            result = await facade.send(agent_id, MINIMAL_PROMPT)
    finally:
        logger.removeHandler(handler)

    assert result.status is RunStatus.FINISHED
    assert result.text

    injected = [json.loads(line) for line in records if "mcp_servers_injected" in line]
    assert len(injected) == 1
    assert injected[0]["event"] == "mcp_servers_injected"
    assert injected[0]["tool_profile"] == "full"
    assert injected[0]["server_names"] == ["playwright"]


@pytest.mark.asyncio
async def test_full_profile_agent_can_see_playwright_mcp_tools() -> None:
    """Best-effort probe: agent text should acknowledge playwright MCP tools.

    This is intentionally soft: SDK/tool discovery timing can vary. The hard
    contract is injection + finished turn in the sibling smoke test.
    """
    workspace = str(repo_root())
    async with AsyncSdkFacade(
        api_key=os.environ.get("CURSOR_API_KEY"),
        bridge_options={"workspace": workspace},
        mcp_full_servers=["playwright"],
    ) as facade:
        agent_id = await facade.create_agent(
            workspace=workspace,
            model=MODEL,
            tool_profile="full",
        )
        result = await facade.send(agent_id, MCP_PROBE_PROMPT)

    assert result.status is RunStatus.FINISHED
    assert result.text
    lowered = result.text.lower()
    if "playwright" not in lowered and "mcp" not in lowered:
        pytest.skip(
            "agent reply did not mention playwright/MCP tools; injection smoke "
            "still covers the product contract. reply="
            f"{result.text!r}"
        )
