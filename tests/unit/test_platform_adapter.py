"""Unit tests for the platform adapter contract (PRD-006 FR8, FR9)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import cursor_agent

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    OutboundSink,
    assert_lifecycle,
    is_platform_adapter,
    track_inbound,
)


def _package_source_dir() -> Path:
    """Return the filesystem directory for the cursor_agent package."""
    init_file = Path(cursor_agent.__file__)
    if init_file.name == "__init__.py":
        return init_file.parent
    msg = f"expected package __init__.py, got {init_file!r}"
    raise AssertionError(msg)


def _platforms_base_path() -> Path:
    """Return the path to ``platforms/base.py``."""
    return _package_source_dir() / "platforms" / "base.py"


def test_inbound_message_is_frozen_dataclass_with_required_fields() -> None:
    """InboundMessage carries platform identity, opaque session_key, and text."""
    from cursor_agent.platforms.base import InboundMessage

    message = InboundMessage(
        platform="telegram",
        sender_id="user-42",
        session_key="telegram:42:deadbeef",
        text="hello gateway",
    )
    assert message.platform == "telegram"
    assert message.sender_id == "user-42"
    assert message.session_key == "telegram:42:deadbeef"
    assert message.text == "hello gateway"
    with pytest.raises(AttributeError):
        message.text = "mutated"  # type: ignore[misc]


def test_outbound_message_carries_reply_target_without_platform_api_details() -> None:
    """OutboundMessage includes enough metadata for adapters to deliver replies."""
    from cursor_agent.platforms.base import OutboundMessage

    outbound = OutboundMessage(
        platform="telegram",
        sender_id="user-42",
        session_key="telegram:42:deadbeef",
        text="agent reply",
    )
    assert outbound.platform == "telegram"
    assert outbound.sender_id == "user-42"
    assert outbound.session_key == "telegram:42:deadbeef"
    assert outbound.text == "agent reply"


def test_outbound_reply_builds_reply_from_inbound() -> None:
    """outbound_reply copies routing metadata from the inbound message."""
    from cursor_agent.platforms.base import InboundMessage, outbound_reply

    inbound = InboundMessage(
        platform="telegram",
        sender_id="user-42",
        session_key="telegram:42:deadbeef",
        text="hello",
    )
    outbound = outbound_reply(inbound, "pong")
    assert outbound.platform == inbound.platform
    assert outbound.sender_id == inbound.sender_id
    assert outbound.session_key == inbound.session_key
    assert outbound.text == "pong"


def test_platform_adapter_protocol_declares_platform_property() -> None:
    """PlatformAdapter documents a stable platform identifier property."""
    adapter = FakePlatformAdapter(platform="telegram")
    assert adapter.platform == "telegram"
    assert is_platform_adapter(adapter)


def test_gateway_busy_message_matches_adr_008() -> None:
    """ADR-008 busy copy is exported as a stable constant from product_copy."""
    from cursor_agent.platforms.base import GATEWAY_BUSY_MESSAGE
    from cursor_agent.product_copy import GATEWAY_BUSY_MESSAGE as CANONICAL_BUSY_MESSAGE

    assert GATEWAY_BUSY_MESSAGE == CANONICAL_BUSY_MESSAGE
    assert "/stop" in GATEWAY_BUSY_MESSAGE


def test_platform_adapter_protocol_lifecycle_shape() -> None:
    """PlatformAdapter exposes async start, stop, and send_message."""
    from cursor_agent.platforms.base import PlatformAdapter

    assert inspect.isclass(PlatformAdapter)
    for method_name in ("start", "stop", "send_message"):
        method = getattr(PlatformAdapter, method_name)
        assert callable(method)


def test_fake_platform_adapter_satisfies_protocol() -> None:
    """Shared fake adapter implements the PlatformAdapter contract."""
    adapter = FakePlatformAdapter(platform="fake")
    assert is_platform_adapter(adapter)


@pytest.mark.asyncio
async def test_fake_adapter_registers_inbound_callback_on_start() -> None:
    """start stores the inbound callback for later simulated messages."""
    adapter = FakePlatformAdapter()
    received: list[object] = []
    from cursor_agent.platforms.base import InboundMessage

    await adapter.start(track_inbound(received))  # type: ignore[arg-type]
    inbound = InboundMessage(
        platform="fake",
        sender_id="sender-1",
        session_key="fake:sender-1:abc12345",
        text="ping",
    )
    await adapter.simulate_inbound(inbound)
    assert received == [inbound]


@pytest.mark.asyncio
async def test_fake_adapter_start_stop_ordering() -> None:
    """Fake adapter records start before stop in lifecycle order."""
    adapter = FakePlatformAdapter()
    await adapter.start(track_inbound([]))  # type: ignore[arg-type]
    await adapter.stop()
    assert_lifecycle(adapter, "start", "stop")
    assert adapter.started is False
    assert adapter.stopped is True


@pytest.mark.asyncio
async def test_fake_adapter_captures_outbound_messages() -> None:
    """send_message appends outbound replies for runner assertions."""
    from cursor_agent.platforms.base import OutboundMessage

    adapter = FakePlatformAdapter()
    outbound = OutboundMessage(
        platform="fake",
        sender_id="sender-1",
        session_key="fake:sender-1:abc12345",
        text="pong",
    )
    await adapter.send_message(outbound)
    assert adapter.outbound_messages == [outbound]


@pytest.mark.asyncio
async def test_outbound_sink_captures_messages() -> None:
    """OutboundSink collects outbound payloads independently of adapters."""
    from cursor_agent.platforms.base import OutboundMessage

    sink = OutboundSink()
    outbound = OutboundMessage(
        platform="fake",
        sender_id="sender-1",
        session_key="fake:sender-1:abc12345",
        text="captured",
    )
    await sink.capture(outbound)
    assert sink.messages == [outbound]


def test_platforms_package_exports_stable_symbols() -> None:
    """Public adapter types are importable from cursor_agent.platforms."""
    from cursor_agent.platforms import (
        GATEWAY_BUSY_MESSAGE,
        GatewayInboundCallback,
        InboundMessage,
        OutboundMessage,
        PlatformAdapter,
    )

    assert GATEWAY_BUSY_MESSAGE
    assert InboundMessage is not None
    assert OutboundMessage is not None
    assert PlatformAdapter is not None
    assert GatewayInboundCallback is not None


@pytest.mark.asyncio
async def test_gateway_inbound_callback_is_async_callable() -> None:
    """GatewayInboundCallback accepts async handlers returning awaitables."""
    from cursor_agent.platforms.base import GatewayInboundCallback, InboundMessage

    async def _handler(message: InboundMessage) -> None:
        _ = message

    callback: GatewayInboundCallback = _handler
    await callback(
        InboundMessage(
            platform="fake",
            sender_id="1",
            session_key="fake:1:abc12345",
            text="hi",
        )
    )


def _file_imports_forbidden_platform_deps(py_file: Path) -> list[str]:
    """Return forbidden import module names found in ``py_file``."""
    forbidden_prefixes = (
        "aiogram",
        "telegram",
    )
    forbidden_exact = {
        "cursor_agent.sessions.models.build_cli_session_key",
    }
    offenders: list[str] = []
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_prefixes or alias.name.startswith(
                    tuple(f"{prefix}." for prefix in forbidden_prefixes)
                ):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            module = node.module
            if module in forbidden_prefixes or module.startswith(
                tuple(f"{prefix}." for prefix in forbidden_prefixes)
            ):
                offenders.append(module)
            if node.names:
                for alias in node.names:
                    qualified = f"{module}.{alias.name}"
                    if qualified in forbidden_exact:
                        offenders.append(qualified)
    source = py_file.read_text(encoding="utf-8")
    if "build_telegram_session_key" in source:
        offenders.append("build_telegram_session_key")
    if "build_cli_session_key" in source:
        offenders.append("build_cli_session_key")
    return offenders


def test_no_telegram_dependency_in_platforms_base() -> None:
    """platforms/base.py stays free of Telegram SDKs and session-key builders."""
    base_path = _platforms_base_path()
    assert base_path.is_file(), f"expected {base_path} to exist"
    offenders = _file_imports_forbidden_platform_deps(base_path)
    assert offenders == [], f"forbidden platform imports in base.py: {offenders!r}"
