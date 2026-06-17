"""Gateway graceful shutdown integration tests (PRD-006, ADR-021).

Exercises SIGTERM-driven shutdown with a real ``AsyncSdkFacade`` bridge when
``CURSOR_API_KEY`` is set. Skips cleanly without an API key.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.gateway.runner import gateway_runtime, register_shutdown_signals
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

GRACEFUL_SHUTDOWN_BUDGET_SECONDS = 35.0
MINIMAL_PROMPT = "Reply with the single word OK."
SESSION_KEY = "telegram:123456789:shutdown-integration"


async def _seed_session(
    store: SessionStore,
    facade: AsyncSdkFacade,
    *,
    workspace: str,
    session_key: str,
) -> str:
    """Create a session row backed by a live SDK agent; return ``agent_id``."""
    agent_id = await facade.create_agent(workspace=workspace, tool_profile="messaging")
    await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime="local",
            tool_profile="messaging",
        )
    )
    return agent_id


async def test_sigterm_shutdown_disposes_real_sdk_bridge(tmp_path: Path) -> None:
    """SIGTERM triggers ADR-021 shutdown and releases the live SDK bridge."""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    workspace = str(workspace_dir)
    config = gateway_config(workspace=workspace)
    adapter = FakePlatformAdapter(platform="telegram")
    db_path = tmp_path / "sessions.db"
    shutdown_complete = asyncio.Event()
    facade_ref: AsyncSdkFacade | None = None
    started = time.perf_counter()

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            store_path=db_path,
            shutdown_complete=shutdown_complete,
            register_signals=False,
        ) as ctx:
            facade = ctx.facade
            assert isinstance(facade, AsyncSdkFacade)
            facade_ref = facade

            agent_id = await _seed_session(
                ctx.store,
                facade,
                workspace=workspace,
                session_key=SESSION_KEY,
            )

            dispatch_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=SESSION_KEY,
                        text=MINIMAL_PROMPT,
                    )
                )
            )

            loop = asyncio.get_running_loop()
            handlers: dict[int, object] = {}
            real_add_signal_handler = loop.add_signal_handler

            def _capture_handler(sig: int, handler: object) -> None:
                handlers[sig] = handler
                real_add_signal_handler(sig, handler)  # type: ignore[arg-type]

            with patch.object(
                loop,
                "add_signal_handler",
                side_effect=_capture_handler,
            ):
                register_shutdown_signals(ctx.shutdown_coordinator, ctx, loop=loop)

            if signal.SIGTERM not in handlers:
                pytest.skip("SIGTERM handler not supported on this platform")

            loop.call_soon(lambda: os.kill(os.getpid(), signal.SIGTERM))

            await asyncio.wait_for(
                shutdown_complete.wait(),
                timeout=GRACEFUL_SHUTDOWN_BUDGET_SECONDS,
            )

            await asyncio.wait_for(dispatch_task, timeout=5.0)

    elapsed = time.perf_counter() - started
    assert elapsed <= GRACEFUL_SHUTDOWN_BUDGET_SECONDS, (
        f"shutdown exceeded {GRACEFUL_SHUTDOWN_BUDGET_SECONDS}s budget: {elapsed:.3f}s"
    )
    assert facade_ref is not None
    assert facade_ref._closed is True
    assert facade_ref._client is None
    assert adapter.stopped is True

    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as replacement:
        replacement_agent_id = await replacement.create_agent(
            workspace=workspace,
            tool_profile="messaging",
        )
        assert replacement_agent_id != agent_id
