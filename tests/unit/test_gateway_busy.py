"""Unit tests for gateway busy mapping (ADR-008)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.base import (
    GATEWAY_BUSY_MESSAGE,
    InboundMessage,
    OutboundMessage,
)
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    SendSpyPool,
    gateway_config,
    seed_session,
)


async def _wait_for_outbound_count(
    adapter: FakePlatformAdapter,
    expected_count: int,
) -> None:
    """Wait for background dispatch to publish enough outbound messages."""
    for _attempt in range(20):
        if len(adapter.outbound_messages) >= expected_count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"expected {expected_count} outbound messages, "
        f"received {len(adapter.outbound_messages)}"
    )


class SendCapturingFacade(FakeSdkFacade):
    """FakeSdkFacade that records send message text for busy/no-queue assertions."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.send_calls: list[str] = []

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: object = None,
        log_context: object = None,
    ) -> object:
        self.send_calls.append(message)
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,  # type: ignore[arg-type]
            log_context=log_context,  # type: ignore[arg-type]
        )


async def test_dispatch_busy_session_sends_adr008_message(tmp_path: Path) -> None:
    """Second inbound while send is in-flight returns the ADR-008 busy message."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="agent reply")
    session_key = "telegram:123456789:busytest"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
        ) as ctx:
            await seed_session(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
                tool_profile="messaging",
            )

            first_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="first message",
                    )
                )
            )
            await facade.send_in_progress.wait()

            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=session_key,
                    text="second message",
                )
            )
            await _wait_for_outbound_count(adapter, 1)

            send_release.set()
            await first_task
            await _wait_for_outbound_count(adapter, 2)

    assert len(adapter.outbound_messages) == 2
    busy_outbound = adapter.outbound_messages[0]
    assert busy_outbound == OutboundMessage(
        platform="telegram",
        sender_id="123456789",
        session_key=session_key,
        text=GATEWAY_BUSY_MESSAGE,
    )
    assert busy_outbound.text == GATEWAY_BUSY_MESSAGE
    assert adapter.outbound_messages[1].text == "agent reply"


async def test_sequential_adapter_callback_still_allows_busy_response(
    tmp_path: Path,
) -> None:
    """Adapters that await on_inbound still let later messages hit the busy path."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="finished")
    session_key = "telegram:123456789:serial-adapter"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
        ) as ctx:
            await seed_session(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
                tool_profile="messaging",
            )

            await asyncio.wait_for(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="first serial message",
                    )
                ),
                timeout=0.05,
            )
            await facade.send_in_progress.wait()

            await asyncio.wait_for(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="second serial message",
                    )
                ),
                timeout=0.05,
            )
            await _wait_for_outbound_count(adapter, 1)

            send_release.set()
            await _wait_for_outbound_count(adapter, 2)

    assert adapter.outbound_messages[0].text == GATEWAY_BUSY_MESSAGE
    assert adapter.outbound_messages[1].text == "finished"


async def test_dispatch_busy_does_not_queue_or_invoke_facade_twice(
    tmp_path: Path,
) -> None:
    """Busy inbound is rejected without queueing; only the first message reaches the facade."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    send_release = asyncio.Event()
    facade = SendCapturingFacade(send_release=send_release, default_reply="only once")
    session_key = "telegram:123456789:noqueue"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
        ) as ctx:
            await seed_session(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
                tool_profile="messaging",
            )

            first_task = asyncio.create_task(
                adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text="in flight",
                    )
                )
            )
            await facade.send_in_progress.wait()

            for extra_text in ("queued?", "also queued?"):
                await adapter.simulate_inbound(
                    InboundMessage(
                        platform="telegram",
                        sender_id="123456789",
                        session_key=session_key,
                        text=extra_text,
                    )
                )
            await _wait_for_outbound_count(adapter, 2)

            send_release.set()
            await first_task
            await _wait_for_outbound_count(adapter, 3)

    assert len(facade.send_calls) == 1
    assert facade.send_calls[0] == "in flight"

    busy_messages = [
        msg for msg in adapter.outbound_messages if msg.text == GATEWAY_BUSY_MESSAGE
    ]
    assert len(busy_messages) == 2
    assert adapter.outbound_messages[-1].text == "only once"


async def test_dispatch_passes_resolved_session_row_to_pool(tmp_path: Path) -> None:
    """Inbound dispatch avoids a second store resolve by passing session_row."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="ok")
    session_key = "telegram:123456789:session-row"
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            pool_factory=SendSpyPool,
        ) as ctx:
            await seed_session(
                ctx.store,
                facade,
                session_key,
                workspace=config.workspace,
            )
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=session_key,
                    text="hello",
                )
            )
            for _ in range(20):
                if ctx.pool.send_calls:
                    break
                await asyncio.sleep(0.01)

    assert len(ctx.pool.send_calls) == 1
    assert ctx.pool.send_calls[0]["session_row"] is not None
