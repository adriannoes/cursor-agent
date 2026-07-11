"""Unit tests for facade NDJSON logging, SDK error mapping, and dispose edges."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from cursor_agent.errors import (
    AuthError,
    ConfigError,
    InvalidAgentError,
    NetworkError,
    SdkInternalError,
    TimeoutError,
)
from cursor_agent.facade_logging import _redact, emit_mcp_servers_injected
from cursor_agent.sdk_facade import (
    AsyncSdkFacade,
    FakeSdkFacade,
    LogContext,
    RunStatus,
    _map_sdk_exception,
)
from cursor_sdk.errors import (
    AgentNotFoundError as SdkAgentNotFoundError,
    APITimeoutError as SdkAPITimeoutError,
    AuthenticationError as SdkAuthenticationError,
    InternalServerError as SdkInternalServerError,
    RateLimitError as SdkRateLimitError,
)


@pytest.mark.asyncio
async def test_log_emit_send_start_and_end_ndjson() -> None:
    """send emits NDJSON start/end events with schema v1 fields."""
    logger = logging.getLogger("test.facade.ndjson")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    facade._logger = logger
    agent_id = await facade.create_agent(workspace="/tmp")
    log_context = LogContext(session_id="sess-1", session_key="cli:default:abc")

    await facade.send(
        agent_id,
        "hi",
        log_context=log_context,
    )

    logger.removeHandler(handler)
    assert len(records) >= 2
    start_payload = json.loads(records[0])
    end_payload = json.loads(records[-1])

    for payload in (start_payload, end_payload):
        assert payload["v"] == 1
        assert payload["level"] == "info"
        assert "ts" in payload
        assert payload["agent_id"] == agent_id

    assert start_payload["event"] == "send_start"
    assert end_payload["event"] == "send_end"
    assert end_payload["status"] == RunStatus.FINISHED.value
    assert isinstance(end_payload["duration_ms"], int)
    assert end_payload["run_id"]
    assert start_payload["session_id"] == "sess-1"
    assert start_payload["session_key"] == "cli:default:abc"


def test_emit_mcp_servers_injected_logs_names_only() -> None:
    """mcp_servers_injected NDJSON includes tool_profile and sorted server names."""
    logger = logging.getLogger("test.facade.mcp_injected")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_mcp_servers_injected(
        logger,
        tool_profile="full",
        server_names=["playwright", "github"],
    )

    logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["v"] == 1
    assert payload["event"] == "mcp_servers_injected"
    assert payload["tool_profile"] == "full"
    assert payload["server_names"] == ["playwright", "github"]


def test_facade_logging_redacts_api_key_patterns() -> None:
    """Secret-like substrings are redacted before logging."""
    assert _redact("Bearer sk-live-secret") == "[REDACTED]"
    assert _redact(42) == 42


def test_map_sdk_exception_wraps_network_failures() -> None:
    """Unknown network failures map to retryable NetworkError."""
    mapped = _map_sdk_exception(ConnectionError("connection reset"))
    assert isinstance(mapped, NetworkError)
    assert mapped.is_retryable is True


def test_map_sdk_exception_maps_sdk_authentication_error() -> None:
    """SDK AuthenticationError maps to domain AuthError (ADR-024)."""
    mapped = _map_sdk_exception(SdkAuthenticationError("invalid api key"))
    assert isinstance(mapped, AuthError)
    assert mapped.is_retryable is False


def test_map_sdk_exception_maps_sdk_rate_limit_with_retry_after() -> None:
    """SDK RateLimitError maps to retryable NetworkError with parsed retry_after."""
    mapped = _map_sdk_exception(
        SdkRateLimitError("rate limited", is_retryable=True, retry_after="2.5")
    )
    assert isinstance(mapped, NetworkError)
    assert mapped.is_retryable is True
    assert mapped.retry_after == 2.5


def test_map_sdk_exception_maps_sdk_agent_not_found() -> None:
    """SDK AgentNotFoundError maps to InvalidAgentError."""
    mapped = _map_sdk_exception(SdkAgentNotFoundError("agent missing"))
    assert isinstance(mapped, InvalidAgentError)


def test_map_sdk_exception_maps_sdk_api_timeout() -> None:
    """SDK APITimeoutError maps to domain TimeoutError."""
    mapped = _map_sdk_exception(SdkAPITimeoutError("deadline exceeded"))
    assert isinstance(mapped, TimeoutError)
    assert mapped.is_retryable is True


def test_map_sdk_exception_maps_sdk_internal_server_error() -> None:
    """SDK InternalServerError maps to SdkInternalError for pool reattach detection."""
    mapped = _map_sdk_exception(SdkInternalServerError("upstream 500"))
    assert isinstance(mapped, SdkInternalError)
    assert mapped.is_retryable is True


def test_map_sdk_exception_maps_type_error_to_config_error() -> None:
    """TypeError from SDK serialization maps to ConfigError."""
    mapped = _map_sdk_exception(
        TypeError("Object of type LocalAgentOptions is not JSON serializable")
    )
    assert isinstance(mapped, ConfigError)
    assert "serialization failed" in str(mapped)


@pytest.mark.asyncio
async def test_fake_resume_unknown_agent_raises() -> None:
    """Fake resume rejects unknown agent ids."""
    facade = FakeSdkFacade()
    with pytest.raises(ValueError, match="invalid fake agent_id"):
        await facade.resume_agent("missing", workspace="/tmp")


@pytest.mark.asyncio
async def test_fake_dispose_agent_removes_handle() -> None:
    """FakeSdkFacade.dispose_agent drops the agent from has_agent tracking."""
    facade = FakeSdkFacade()
    agent_id = await facade.create_agent(workspace="/tmp")
    assert facade.has_agent(agent_id) is True
    await facade.dispose_agent(agent_id)
    assert facade.has_agent(agent_id) is False


@pytest.mark.asyncio
async def test_dispose_agent_cancels_active_run_and_exits_handle() -> None:
    """AsyncSdkFacade.dispose_agent cancels in-flight runs and releases SDK handles."""
    agent_id = "agent-dispose-active"
    mock_agent = AsyncMock()
    mock_agent.agent_id = agent_id
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_run = MagicMock()
    facade = AsyncSdkFacade(api_key="test-key")
    facade._agents[agent_id] = mock_agent
    facade._active_runs[agent_id] = mock_run

    await facade.dispose_agent(agent_id)

    mock_run.cancel.assert_called_once()
    mock_agent.__aexit__.assert_awaited_once()
    assert agent_id not in facade._agents


@pytest.mark.asyncio
async def test_resume_agent_disposes_previous_handle_when_sdk_returns_new_instance() -> (
    None
):
    """resume_agent must dispose the superseded SDK handle to prevent gateway leaks."""
    agent_id = "agent-resume-dispose"
    previous_agent = AsyncMock()
    previous_agent.agent_id = agent_id
    previous_agent.__aexit__ = AsyncMock(return_value=None)

    new_agent = AsyncMock()
    new_agent.agent_id = agent_id
    new_agent.__aenter__ = AsyncMock(return_value=new_agent)
    new_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=new_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client
    facade._agents[agent_id] = previous_agent
    facade._agent_tool_profiles[agent_id] = "coding"

    resumed_id = await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="messaging",
    )

    assert resumed_id == agent_id
    previous_agent.__aexit__.assert_awaited_once()
    assert facade._agents[agent_id] is new_agent


@pytest.mark.asyncio
async def test_fake_has_agent_tracks_create_and_resume() -> None:
    """FakeSdkFacade.has_agent reflects create_agent and resume_agent state."""
    facade = FakeSdkFacade()
    assert facade.has_agent("missing") is False
    agent_id = await facade.create_agent(workspace="/tmp")
    assert facade.has_agent(agent_id) is True
    assert (
        facade.has_agent(await facade.resume_agent(agent_id, workspace="/tmp")) is True
    )


@pytest.mark.asyncio
async def test_fake_send_unknown_agent_raises() -> None:
    """Fake send rejects unknown agent ids."""
    facade = FakeSdkFacade()
    with pytest.raises(ValueError, match="invalid fake agent_id"):
        await facade.send("missing", "hello")


@pytest.mark.asyncio
async def test_async_facade_requires_initialized_bridge() -> None:
    """Operations fail fast when bridge was not entered."""
    facade = AsyncSdkFacade(api_key="test-key")
    with pytest.raises(RuntimeError, match="not initialized"):
        await facade.create_agent(workspace="/tmp")
