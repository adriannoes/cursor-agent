"""Unit tests for AsyncSdkFacade warm resume, send/stream, retry, cancel, close."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cursor_agent.sdk_facade import AsyncSdkFacade, RunStatus, StreamCallbacks
from cursor_agent.sdk_retry import retry_sdk_call
from tests.unit.facade_test_fakes import resume_request_options, sandbox_enabled


@pytest.mark.asyncio
async def test_messaging_warm_resume_reinjects_empty_mcp_servers() -> None:
    """Messaging warm resume still calls SDK to enforce empty MCP servers."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-warm-messaging"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="messaging")
    mock_client.agents.resume.reset_mock()

    await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="messaging",
    )

    mock_client.agents.resume.assert_called_once()
    options = resume_request_options(mock_client)
    assert options.get("mcpServers") == {}


@pytest.mark.asyncio
async def test_resume_agent_defaults_to_coding_mcp_omission_for_unknown_agent() -> None:
    """Cold resume for unknown agent_id without profile must omit MCP override (coding default)."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-unknown-cold"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    await facade.resume_agent("agent-unknown-cold", workspace="/repo")

    options = resume_request_options(mock_client)
    assert "mcpServers" not in options
    assert "mcp_servers" not in options


@pytest.mark.asyncio
async def test_resume_agent_skips_sdk_call_when_agent_already_loaded() -> None:
    """resume_agent short-circuits when the agent is already in memory."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-in-memory"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="coding")
    resumed_id = await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="coding",
    )

    assert resumed_id == agent_id
    mock_client.agents.resume.assert_not_called()


@pytest.mark.asyncio
async def test_resume_agent_profile_change_invokes_sdk_with_mcp_override() -> None:
    """resume_agent calls the SDK again when tool_profile changes."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-profile-change"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="coding")
    resumed_id = await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="messaging",
    )

    assert resumed_id == agent_id
    mock_client.agents.resume.assert_called_once()
    options = resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert sandbox_enabled(local_opts) is True


@pytest.mark.asyncio
async def test_resume_agent_applies_model_change_when_agent_already_in_memory() -> None:
    """resume_agent calls the SDK again when the effective model changes."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-in-memory"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(
        workspace="/repo",
        model="composer-2.5",
        tool_profile="coding",
    )
    resumed_id = await facade.resume_agent(
        agent_id,
        workspace="/repo",
        model="grok-4.5",
        tool_profile="coding",
    )

    assert resumed_id == agent_id
    mock_client.agents.resume.assert_called_once()
    options = resume_request_options(mock_client)
    assert options.get("model") == {"id": "grok-4.5"}


@pytest.mark.asyncio
async def test_async_send_drains_messages_and_wait() -> None:
    """send drains messages(), calls wait(), and never uses run.text()."""
    assistant_msg = SimpleNamespace(
        type="assistant",
        message=SimpleNamespace(
            content=[SimpleNamespace(text="Hi ", type="text")],
        ),
    )
    tool_running = SimpleNamespace(
        type="tool_call",
        name="read",
        status="running",
        args={"path": "README.md"},
        result=None,
    )
    tool_done = SimpleNamespace(
        type="tool_call",
        name="read",
        status="completed",
        args={"path": "README.md"},
        result="ok",
    )

    async def message_iter() -> Any:
        for item in (assistant_msg, tool_running, tool_done):
            yield item

    mock_run = MagicMock()
    mock_run.messages = MagicMock(return_value=message_iter())
    mock_run.text = AsyncMock(
        side_effect=AssertionError("run.text() must not be called")
    )
    mock_run.wait = AsyncMock(
        return_value=SimpleNamespace(
            id="run-99",
            status="finished",
            result="Hi ",
            duration_ms=50,
        ),
    )

    mock_agent = MagicMock()
    mock_agent.send = AsyncMock(return_value=mock_run)
    mock_agent.agent_id = "agent-send"

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = MagicMock()
    facade._agents = {"agent-send": mock_agent}

    tool_events: list[str] = []

    async def on_tool_start(name: str, args: dict[str, Any]) -> None:
        tool_events.append(f"start:{name}")

    async def on_tool_end(name: str, payload: dict[str, Any]) -> None:
        tool_events.append(f"end:{name}")

    result = await facade.send(
        "agent-send",
        "hello",
        callbacks=StreamCallbacks(on_tool_start=on_tool_start, on_tool_end=on_tool_end),
    )

    mock_run.text.assert_not_called()
    assert result.run_id == "run-99"
    assert result.status is RunStatus.FINISHED
    assert result.text == "Hi "
    assert tool_events == ["start:read", "end:read"]


class _RetryableFacadeError(Exception):
    """Stand-in for CursorAgentError in retry tests."""

    is_retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class _NonRetryableFacadeError(Exception):
    """Stand-in for non-retryable CursorAgentError subclasses."""

    is_retryable = False


@pytest.mark.asyncio
async def test_retry_honors_retryable_errors_max_three_attempts() -> None:
    """Pre-run retryable errors retry up to 3 times with retry_after."""
    attempts = 0
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-retry"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    async def flaky_create(**_kwargs: Any) -> AsyncMock:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _RetryableFacadeError("transient", retry_after=0.01)
        return mock_agent

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(side_effect=flaky_create)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    with patch(
        "cursor_agent.sdk_retry.asyncio.sleep", new_callable=AsyncMock
    ) as sleep_mock:
        agent_id = await facade.create_agent(workspace="/ws")

    assert agent_id == "agent-retry"
    assert attempts == 3
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_retry_does_not_retry_non_retryable_errors() -> None:
    """Non-retryable errors fail immediately without sleep."""
    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(
        side_effect=_NonRetryableFacadeError("bad key"),
    )

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    with patch(
        "cursor_agent.sdk_retry.asyncio.sleep", new_callable=AsyncMock
    ) as sleep_mock:
        with pytest.raises(_NonRetryableFacadeError):
            await facade.create_agent(workspace="/ws")

    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_during_send_returns_cancelled() -> None:
    """cancel during active send yields CANCELLED RunResult."""
    blocked = asyncio.Event()

    async def message_iter() -> Any:
        await blocked.wait()
        if False:  # pragma: no cover - makes this an async generator
            yield None

    mock_run = MagicMock()
    mock_run.messages = MagicMock(return_value=message_iter())
    mock_run.cancel = MagicMock()
    mock_run.wait = AsyncMock()

    mock_agent = MagicMock()
    mock_agent.send = AsyncMock(return_value=mock_run)
    mock_agent.agent_id = "agent-cancel"

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = MagicMock()
    facade._agents = {"agent-cancel": mock_agent}

    send_task = asyncio.create_task(facade.send("agent-cancel", "long"))
    await asyncio.sleep(0.01)
    await facade.cancel("agent-cancel")
    blocked.set()
    result = await send_task

    assert result.status is RunStatus.CANCELLED
    mock_run.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_close_is_idempotent() -> None:
    """close may be called multiple times safely."""
    mock_bridge = AsyncMock()
    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_bridge

    await facade.close()
    await facade.close()

    mock_bridge.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_sdk_call_does_not_catch_cancelled_error() -> None:
    """CancelledError must propagate without retry (PR #22 regression guard)."""

    async def raise_cancelled() -> str:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await retry_sdk_call(raise_cancelled)
