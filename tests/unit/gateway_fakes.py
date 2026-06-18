"""Shared gateway fakes for platform adapter and runner unit tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import (
    GatewayConfig,
    PlatformsConfig,
    TelegramPlatformConfig,
)
from cursor_agent.memory import LocalMemoryStore
from cursor_agent.platforms.base import (
    GatewayInboundCallback,
    InboundMessage,
    OutboundMessage,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, SdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


def gateway_config(
    *,
    tool_profile: str = "messaging",
    workspace: str = "/tmp/gateway-workspace",
    allowed_users: list[int] | None = None,
) -> GatewayConfig:
    users = allowed_users if allowed_users is not None else [123456789]
    return GatewayConfig(
        workspace=workspace,
        tool_profile=tool_profile,  # type: ignore[arg-type]
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(
                enabled=True,
                bot_token="123456789:AAFakeTestTokenForUnitTests",
                allowed_users=users,
            ),
        ),
    )


def write_gateway_yaml(
    path: Path,
    *,
    tool_profile: str = "messaging",
    workspace: str = "/tmp/gateway-workspace",
    allowed_users: str = "123456789",
) -> None:
    path.write_text(
        (
            f"workspace: {workspace}\n"
            f"tool_profile: {tool_profile}\n"
            "platforms:\n"
            "  telegram:\n"
            "    enabled: true\n"
            "    bot_token: 123456789:AAFakeTestTokenForUnitTests\n"
            "    allowed_users:\n"
            f"      - {allowed_users}\n"
        ),
        encoding="utf-8",
    )


async def seed_session(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    workspace: str = "/tmp/gateway-workspace",
    runtime: str = "local",
    tool_profile: str = "messaging",
) -> str:
    agent_id = await facade.create_agent(workspace=workspace, tool_profile=tool_profile)
    record = await session_store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=runtime,
            tool_profile=tool_profile,
        )
    )
    return record.id


async def seed_session_with_agent(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    workspace: str = "/tmp/gateway-workspace",
    tool_profile: str = "messaging",
) -> tuple[str, str]:
    agent_id = await facade.create_agent(workspace=workspace, tool_profile=tool_profile)
    record = await session_store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime="local",
            tool_profile=tool_profile,
        )
    )
    return record.id, agent_id


def memory_enabled_pool_factory(
    memory_root: Path,
) -> Callable[[SessionStore, SdkFacade, CursorAgentConfig], SessionAgentPool]:
    """Build a pool factory that reads memory files from a temporary root."""

    def factory(
        store: SessionStore,
        facade: SdkFacade,
        config: CursorAgentConfig,
    ) -> SessionAgentPool:
        return SendSpyPool(
            store,
            facade,
            config,
            memory_store=LocalMemoryStore(root=memory_root),
        )

    return factory


class SendSpyPool(SessionAgentPool):
    """SessionAgentPool that records send keyword arguments."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.send_calls: list[dict[str, object]] = []

    async def send(
        self,
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        session_row: object = None,
        callbacks: object = None,
        blocking: bool = True,
        model_override: str | None = None,
    ) -> object:
        self.send_calls.append(
            {
                "session_key": session_key,
                "message": message,
                "session_id": session_id,
                "session_row": session_row,
                "blocking": blocking,
                "model_override": model_override,
            }
        )
        return await super().send(
            session_key,
            message,
            session_id=session_id,
            session_row=session_row,  # type: ignore[arg-type]
            callbacks=callbacks,  # type: ignore[arg-type]
            blocking=blocking,
            model_override=model_override,
        )


@dataclass
class OutboundSink:
    messages: list[OutboundMessage] = field(default_factory=list)

    async def capture(self, outbound: OutboundMessage) -> None:
        self.messages.append(outbound)


class FakePlatformAdapter:
    def __init__(self, *, platform: str = "telegram") -> None:
        self._platform = platform
        self.lifecycle: list[str] = []
        self.outbound_messages: list[OutboundMessage] = []
        self._on_inbound: GatewayInboundCallback | None = None
        self._started = False

    @property
    def platform(self) -> str:
        return self._platform

    @property
    def started(self) -> bool:
        return self._started

    @property
    def stopped(self) -> bool:
        return "stop" in self.lifecycle

    async def start(self, on_inbound: GatewayInboundCallback) -> None:
        self.lifecycle.append("start")
        self._on_inbound = on_inbound
        self._started = True

    async def stop(self) -> None:
        self.lifecycle.append("stop")
        self._started = False

    async def send_message(self, outbound: OutboundMessage) -> None:
        self.outbound_messages.append(outbound)

    async def simulate_inbound(self, message: InboundMessage) -> None:
        if self._on_inbound is None:
            msg = (
                "fake adapter has no inbound callback: call start(on_inbound) "
                "before simulate_inbound"
            )
            raise RuntimeError(msg)
        await self._on_inbound(message)


class OrderTrackingAdapter(FakePlatformAdapter):
    def __init__(
        self,
        order: list[str],
        *,
        platform: str = "telegram",
    ) -> None:
        super().__init__(platform=platform)
        self._order = order

    async def start(self, on_inbound: GatewayInboundCallback) -> None:
        self._order.append("adapter_start")
        await super().start(on_inbound)


class OrderTrackingStopAdapter(FakePlatformAdapter):
    def __init__(
        self,
        events: list[str],
        *,
        platform: str = "telegram",
    ) -> None:
        super().__init__(platform=platform)
        self._events = events

    async def stop(self) -> None:
        self._events.append("adapter_stop")
        await super().stop()


def track_inbound(
    received: list[InboundMessage],
) -> GatewayInboundCallback:
    async def _on_inbound(message: InboundMessage) -> None:
        received.append(message)

    return _on_inbound


def assert_lifecycle(adapter: FakePlatformAdapter, *expected: str) -> None:
    assert adapter.lifecycle == list(expected), (
        f"expected lifecycle {list(expected)!r}, got {adapter.lifecycle!r}"
    )


def is_platform_adapter(obj: object) -> bool:
    platform = getattr(obj, "platform", None)
    required: tuple[str, ...] = ("start", "stop", "send_message")
    return isinstance(platform, str) and all(
        callable(getattr(obj, name, None)) for name in required
    )


RunTracker = Callable[[str], Awaitable[None]]


async def make_run_tracker(events: list[str]) -> RunTracker:
    async def _track(event: str) -> None:
        events.append(event)

    return _track
