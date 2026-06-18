"""Gateway cold-start integration tests (process restart path).

Seeds a session in one facade lifetime, tears down the bridge, then
dispatches inbound through a fresh ``gateway_runtime`` — the Telegram
restart scenario before PRD-007.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.base import InboundMessage
from cursor_agent.sdk_facade import AsyncSdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import FakePlatformAdapter, gateway_config

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("CURSOR_API_KEY"),
        reason="requires CURSOR_API_KEY",
    ),
]

MINIMAL_PROMPT = "Reply with the single word OK."
SESSION_KEY = "telegram:123456789:coldstart"
_OUTBOUND_WAIT_SECONDS = 90.0


async def _wait_for_condition(
    condition: Callable[[], bool],
    *,
    description: str,
    timeout_seconds: float = _OUTBOUND_WAIT_SECONDS,
    poll_interval_seconds: float = 0.5,
) -> None:
    """Poll until ``condition`` is true or integration timeout elapses."""
    attempts = max(1, int(timeout_seconds / poll_interval_seconds))
    for _attempt in range(attempts):
        if condition():
            return
        await asyncio.sleep(poll_interval_seconds)
    raise AssertionError(f"condition did not become true: {description}")


async def _wait_for_outbound(adapter: FakePlatformAdapter) -> None:
    """Wait until the fake adapter captures an outbound reply."""
    await _wait_for_condition(
        lambda: bool(adapter.outbound_messages),
        description="gateway outbound reply after cold-start dispatch",
    )


async def test_gateway_cold_start_dispatches_after_bridge_restart(
    tmp_path: Path,
) -> None:
    """Inbound dispatch succeeds after gateway bridge restart (cold resume)."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    workspace = str(workspace_dir)
    config = gateway_config(workspace=workspace)
    db_path = tmp_path / "sessions.db"

    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as seed_facade:
        agent_id = await seed_facade.create_agent(
            workspace=workspace,
            tool_profile="messaging",
        )

    store_path = db_path
    store = SessionStore(store_path)
    await store.initialize()
    await store.create(
        SessionCreateParams(
            session_key=SESSION_KEY,
            agent_id=agent_id,
            workspace=workspace,
            runtime="local",
            tool_profile="messaging",
        )
    )

    adapter = FakePlatformAdapter(platform="telegram")
    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            store_path=store_path,
        ) as _ctx:
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=SESSION_KEY,
                    text=MINIMAL_PROMPT,
                )
            )
            await _wait_for_outbound(adapter)

    assert len(adapter.outbound_messages) == 1
    assert adapter.outbound_messages[0].text
