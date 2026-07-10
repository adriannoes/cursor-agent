"""Live smoke for ``tool_profile: full`` github HTTP MCP (PRD-012 Wave 5 / T7).

Uses github-only allowlist against the official remote HTTP default
(``https://api.githubcopilot.com/mcp/``). Skips cleanly without
``CURSOR_API_KEY`` or ``GITHUB_PERSONAL_ACCESS_TOKEN`` so CI never fails
without secrets.
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
    pytest.mark.skipif(
        not os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN"),
        reason="requires GITHUB_PERSONAL_ACCESS_TOKEN",
    ),
]

# G5 / D5: explicit Composer override fixture — default-path smokes use DEFAULT_AGENT_MODEL.
MODEL = "composer-2.5"
MINIMAL_PROMPT = "Reply with the single word OK."
MCP_PROBE_PROMPT = (
    "List the names of any MCP / external tools you currently have available. "
    "If you have GitHub MCP tools, mention github. "
    "Reply in at most three short lines."
)


def repo_root() -> Path:
    """Return the repository root directory for local agent workspace."""
    return Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_full_profile_injects_github_http_mcp_and_completes_turn() -> None:
    """Live create under full+github must inject HTTP MCP and finish a turn."""
    workspace = str(repo_root())
    logger = logging.getLogger("test.integration.full_github_http_smoke")
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
            mcp_full_servers=["github"],
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
    assert injected[0]["server_names"] == ["github"]


@pytest.mark.asyncio
async def test_full_profile_agent_can_see_github_mcp_tools() -> None:
    """Best-effort probe: agent text should acknowledge github MCP tools.

    This is intentionally soft: SDK/tool discovery timing can vary. The hard
    contract is injection + finished turn in the sibling smoke test.
    """
    workspace = str(repo_root())
    async with AsyncSdkFacade(
        api_key=os.environ.get("CURSOR_API_KEY"),
        bridge_options={"workspace": workspace},
        mcp_full_servers=["github"],
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
    if "github" not in lowered and "mcp" not in lowered:
        pytest.skip(
            "agent reply did not mention github/MCP tools; injection smoke "
            "still covers the product contract. reply="
            f"{result.text!r}"
        )
