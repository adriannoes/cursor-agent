"""SDK integration smoke tests (PRD-000 FR-5, FR-6).

Validates AsyncClient.launch_bridge, a minimal agent turn, and native tool usage.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cursor_sdk import AsyncClient, AsyncRun, LocalAgentOptions
from cursor_sdk.types import SDKToolUseMessage

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("CURSOR_API_KEY"),
        reason="requires CURSOR_API_KEY",
    ),
]

MODEL = "composer-2.5"
MINIMAL_PROMPT = "Reply with the single word OK."
README_FIRST_HEADING_PHRASE = "cursor agent"
TOOL_TURN_PROMPT = (
    "Read README.md at the repository root and reply with only the exact "
    "markdown text of the first heading line (the line that starts with #)."
)


def repo_root() -> Path:
    """Return the repository root directory for local agent workspace.

    Example:
        workspace = str(repo_root())
    """
    return Path(__file__).resolve().parents[2]


async def collect_tool_call_events(run: AsyncRun) -> list[SDKToolUseMessage]:
    """Drain ``run.messages()`` and return observed tool-call events.

    Tool payloads are unstable; callers should inspect envelope fields only.
    """
    events: list[SDKToolUseMessage] = []
    async for message in run.messages():
        if isinstance(message, SDKToolUseMessage):
            events.append(message)
    return events


async def test_sdk_bridge_basic_turn() -> None:
    """Bridge launches and agent returns a non-empty response (PRD-000)."""
    workspace = str(repo_root())
    async with await AsyncClient.launch_bridge(workspace=workspace) as client:
        async with await client.agents.create(
            model=MODEL,
            local=LocalAgentOptions(cwd=workspace),
        ) as agent:
            run = await agent.send(MINIMAL_PROMPT)
            text = (await run.text()).strip()
            result = await run.wait()

    assert text, "expected non-empty assistant text from minimal prompt"
    assert result.status == "finished", (
        f"expected run status 'finished', got {result.status!r}"
    )


async def test_sdk_native_tool_turn() -> None:
    """Agent uses a native file tool and cites README content (PRD-000)."""
    workspace = str(repo_root())
    async with await AsyncClient.launch_bridge(workspace=workspace) as client:
        async with await client.agents.create(
            model=MODEL,
            local=LocalAgentOptions(cwd=workspace),
        ) as agent:
            run = await agent.send(TOOL_TURN_PROMPT)
            tool_call_events = await collect_tool_call_events(run)
            text = (await run.text()).strip()
            result = await run.wait()

    assert result.status == "finished", (
        f"expected run status 'finished', got {result.status!r}"
    )
    assert text, "expected non-empty assistant text after tool turn"
    normalized = text.lower().replace("-", " ")
    assert README_FIRST_HEADING_PHRASE in normalized, (
        "expected response to reference README first heading "
        f"({README_FIRST_HEADING_PHRASE!r} or cursor-agent), got {text!r}"
    )

    completed_tool_calls = [
        event for event in tool_call_events if event.status == "completed"
    ]
    assert completed_tool_calls, (
        "expected at least one completed tool_call event while streaming run.messages(); "
        f"observed statuses: {[event.status for event in tool_call_events]!r}"
    )
