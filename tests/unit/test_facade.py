"""Unit tests for SdkFacade types, FakeSdkFacade, and AsyncSdkFacade (PRD-001)."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cursor_agent.errors import (
    AuthError,
    ConfigError,
    InvalidAgentError,
    NetworkError,
    SdkInternalError,
    TimeoutError,
)
from cursor_sdk.errors import (
    AgentNotFoundError as SdkAgentNotFoundError,
    APITimeoutError as SdkAPITimeoutError,
    AuthenticationError as SdkAuthenticationError,
    InternalServerError as SdkInternalServerError,
    RateLimitError as SdkRateLimitError,
)
from cursor_agent.facade_logging import _redact
from cursor_agent.sdk_facade import (
    AsyncSdkFacade,
    FakeSdkFacade,
    LogContext,
    RunResult,
    RunStatus,
    StreamCallbacks,
    _map_sdk_exception,
)
from cursor_agent.sdk_retry import retry_sdk_call
from cursor_agent.tool_profile_policy import resolve_mcp_servers


def _local_option(local_opts: object, key: str) -> object | None:
    """Read a LocalAgentOptions field from object or mapping test doubles."""
    if isinstance(local_opts, dict):
        wire_key = {
            "setting_sources": "settingSources",
            "sandbox_options": "sandboxOptions",
        }.get(key, key)
        if wire_key in local_opts:
            return local_opts.get(wire_key)
        return local_opts.get(key)
    return getattr(local_opts, key, None)


def _resume_request_options(mock_client: MagicMock) -> dict[str, Any]:
    """Extract JSON-serializable resume options passed to the SDK."""
    resume_args = mock_client.agents.resume.await_args
    options = (
        resume_args.args[1]
        if len(resume_args.args) > 1
        else resume_args.kwargs.get("options")
    )
    assert isinstance(options, dict)
    json.dumps(options)
    return options


def test_types_run_status_finished_value() -> None:
    """RunStatus.FINISHED must match SDK spike terminal status."""
    assert RunStatus.FINISHED.value == "finished"


def test_types_run_result_required_fields() -> None:
    """RunResult exposes run_id, status, text, and optional usage."""
    result = RunResult(
        run_id="run-1",
        status=RunStatus.FINISHED,
        text="hello",
        usage={"tokens": 42},
    )
    assert result.run_id == "run-1"
    assert result.status is RunStatus.FINISHED
    assert result.text == "hello"
    assert result.usage == {"tokens": 42}


def test_types_run_result_usage_optional() -> None:
    """usage may be omitted on RunResult."""
    result = RunResult(
        run_id="run-2",
        status=RunStatus.ERROR,
        text=None,
        usage=None,
    )
    assert result.usage is None


def test_types_stream_callbacks_defaults_none() -> None:
    """StreamCallbacks fields default to None."""
    callbacks = StreamCallbacks()
    assert callbacks.on_assistant_text is None
    assert callbacks.on_tool_start is None
    assert callbacks.on_tool_end is None


def test_types_log_context_optional_fields() -> None:
    """LogContext session fields are optional until PRD-002."""
    ctx = LogContext()
    assert ctx.session_id is None
    assert ctx.session_key is None
    assert ctx.agent_id is None


@pytest.mark.asyncio
async def test_fake_create_agent_returns_agent_id() -> None:
    """FakeSdkFacade.create_agent returns a non-empty agent_id."""
    facade = FakeSdkFacade()
    agent_id = await facade.create_agent(workspace="/tmp/ws")
    assert isinstance(agent_id, str)
    assert agent_id


@pytest.mark.asyncio
async def test_fake_send_returns_scripted_finished_result() -> None:
    """Fake send appends user message and returns FINISHED RunResult."""
    facade = FakeSdkFacade(scripted_replies={"default": "scripted reply"})
    agent_id = await facade.create_agent(workspace="/tmp/ws")
    result = await facade.send(agent_id, "hello")
    assert result.status is RunStatus.FINISHED
    assert result.text == "scripted reply"
    assert result.run_id


@pytest.mark.asyncio
async def test_fake_busy_hook_send_in_progress_event() -> None:
    """send_in_progress is set during send and cleared after."""
    release = asyncio.Event()
    facade = FakeSdkFacade(send_release=release)
    agent_id = await facade.create_agent(workspace="/tmp/ws")

    send_task = asyncio.create_task(facade.send(agent_id, "hold"))
    await asyncio.wait_for(facade.send_in_progress.wait(), timeout=1.0)
    assert not send_task.done()
    assert facade.send_in_progress.is_set() is True
    release.set()
    result = await send_task
    assert facade.send_in_progress.is_set() is False
    assert result.status is RunStatus.FINISHED


@pytest.mark.asyncio
async def test_fake_callbacks_invoke_in_order() -> None:
    """Fake dispatches assistant and tool callbacks in stream order."""
    facade = FakeSdkFacade(
        scripted_replies={"default": "ab"},
        scripted_tool_events=[
            ("grep", {"pattern": "x"}),
        ],
    )
    agent_id = await facade.create_agent(workspace="/tmp/ws")
    events: list[str] = []

    async def on_text(delta: str) -> None:
        events.append(f"text:{delta}")

    async def on_tool_start(name: str, args: dict[str, Any]) -> None:
        events.append(f"start:{name}")

    async def on_tool_end(name: str, payload: dict[str, Any]) -> None:
        events.append(f"end:{name}")

    callbacks = StreamCallbacks(
        on_assistant_text=on_text,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
    )
    await facade.send(agent_id, "go", callbacks=callbacks)
    assert events == ["start:grep", "end:grep", "text:a", "text:b"]


@pytest.mark.asyncio
async def test_async_context_manager_launches_and_closes_bridge() -> None:
    """__aenter__ launches bridge; __aexit__ closes it."""
    mock_bridge = AsyncMock()
    mock_bridge.aclose = AsyncMock()

    with patch(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        new_callable=AsyncMock,
        return_value=mock_bridge,
    ) as launch_mock:
        async with AsyncSdkFacade(api_key="test-key") as facade:
            assert facade._client is mock_bridge
        launch_mock.assert_awaited_once()
        mock_bridge.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_agent_local_options_include_setting_sources_from_config() -> None:
    """create_agent passes explicit project/user setting_sources for local runtime."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-settings"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        local_setting_sources=["project", "user"],
    )
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", runtime_mode="local")

    create_kwargs = mock_client.agents.create.await_args.kwargs
    local_opts = create_kwargs["local"]
    setting_sources = _local_option(local_opts, "setting_sources")
    assert setting_sources == ["project", "user"]
    assert setting_sources != "all"


@pytest.mark.asyncio
async def test_create_agent_honors_custom_setting_sources_from_config() -> None:
    """create_agent uses config-provided setting_sources instead of SDK defaults."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-custom-sources"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        local_setting_sources=["project"],
    )
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", runtime_mode="local")

    local_opts = mock_client.agents.create.await_args.kwargs["local"]
    assert _local_option(local_opts, "setting_sources") == ["project"]


@pytest.mark.asyncio
async def test_resume_agent_local_options_include_setting_sources_from_config() -> None:
    """resume_agent passes explicit project/user setting_sources for local runtime."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-resume-sources"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        local_setting_sources=["project", "user"],
    )
    facade._client = mock_client

    await facade.resume_agent(
        "agent-resume-sources",
        workspace="/repo",
        tool_profile="coding",
    )

    options = _resume_request_options(mock_client)
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    setting_sources = _local_option(local_opts, "setting_sources")
    assert setting_sources == ["SETTING_SOURCE_PROJECT", "SETTING_SOURCE_USER"]
    assert setting_sources != "all"


@pytest.mark.asyncio
async def test_resume_agent_cloud_options_omit_local_setting_sources() -> None:
    """resume_agent omits local setting_sources for cloud runtime sessions."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-cloud-resume"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        local_setting_sources=["project", "user"],
    )
    facade._client = mock_client

    await facade.resume_agent(
        "agent-cloud-resume",
        workspace="/repo",
        tool_profile="coding",
        runtime_mode="cloud",
    )

    options = _resume_request_options(mock_client)
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert _local_option(local_opts, "setting_sources") is None


@pytest.mark.asyncio
async def test_create_agent_uses_composer_and_local_cwd() -> None:
    """create_agent passes composer-2.5 and LocalAgentOptions cwd."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-abc"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo/path")

    assert agent_id == "agent-abc"
    create_kwargs = mock_client.agents.create.await_args.kwargs
    assert create_kwargs["model"] == "composer-2.5"
    local_opts = create_kwargs["local"]
    assert (
        getattr(local_opts, "cwd", None) == "/repo/path"
        or local_opts.get("cwd") == "/repo/path"
    )


def _sandbox_enabled(local_opts: object) -> bool | None:
    """Return sandbox_options.enabled from LocalAgentOptions or a mapping."""
    sandbox = _local_option(local_opts, "sandbox_options")
    if sandbox is None:
        return None
    if isinstance(sandbox, dict):
        enabled = sandbox.get("enabled")
        return enabled if isinstance(enabled, bool) else None
    return getattr(sandbox, "enabled", None)


@pytest.mark.asyncio
async def test_coding_create_agent_omits_mcp_servers_and_sandbox() -> None:
    """Coding create keeps legacy behavior without MCP or sandbox options."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-coding-create"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", tool_profile="coding")

    create_call = mock_client.agents.create.await_args
    create_options = create_call.args[0] if create_call.args else None
    if isinstance(create_options, dict):
        assert "mcp_servers" not in create_options
    assert "mcp_servers" not in create_call.kwargs
    local_opts = create_call.kwargs["local"]
    assert _sandbox_enabled(local_opts) is None


@pytest.mark.asyncio
async def test_coding_resume_agent_omits_mcp_servers_and_sandbox() -> None:
    """Coding resume must omit MCP override so SDK/project settings apply."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-coding-resume"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    await facade.resume_agent(
        "agent-coding-resume",
        workspace="/repo",
        tool_profile="coding",
    )

    options = _resume_request_options(mock_client)
    assert "mcpServers" not in options
    assert "mcp_servers" not in options
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert _sandbox_enabled(local_opts) is None


@pytest.mark.asyncio
async def test_messaging_create_agent_passes_empty_mcp_servers_and_sandbox() -> None:
    """Messaging create must pass explicit empty MCP servers and sandbox."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-messaging-create"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", tool_profile="messaging")

    create_call = mock_client.agents.create.await_args
    create_options = create_call.args[0] if create_call.args else None
    assert isinstance(create_options, dict)
    assert create_options.get("mcp_servers") == {}
    local_opts = create_call.kwargs["local"]
    assert _sandbox_enabled(local_opts) is True


@pytest.mark.asyncio
async def test_messaging_resume_agent_passes_empty_mcp_servers_and_sandbox() -> None:
    """Messaging resume must pass explicit empty MCP servers and sandbox."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-messaging-resume"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    await facade.resume_agent(
        "agent-messaging-resume",
        workspace="/repo",
        tool_profile="messaging",
    )

    options = _resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert _sandbox_enabled(local_opts) is True


@pytest.mark.asyncio
async def test_messaging_resume_after_warm_coding_agent_calls_sdk_with_empty_mcp() -> (
    None
):
    """Warm coding agent resumed as messaging must re-inject empty MCP servers."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-warm-profile-switch"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="coding")
    await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="messaging",
    )

    options = _resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert _sandbox_enabled(local_opts) is True


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
    options = _resume_request_options(mock_client)
    assert options.get("mcpServers") == {}


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
    options = _resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert _sandbox_enabled(local_opts) is True


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
        model="composer-2.5-fast",
        tool_profile="coding",
    )

    assert resumed_id == agent_id
    mock_client.agents.resume.assert_called_once()
    options = _resume_request_options(mock_client)
    assert options.get("model") == {"id": "composer-2.5-fast"}


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


def test_resolve_mcp_servers_stub_profiles() -> None:
    """Legacy MCP API returns empty dict for coding and messaging profiles."""
    assert resolve_mcp_servers("coding") == {}
    assert resolve_mcp_servers("messaging") == {}


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
async def test_retry_sdk_call_does_not_catch_cancelled_error() -> None:
    """CancelledError must propagate without retry (PR #22 regression guard)."""

    async def raise_cancelled() -> str:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await retry_sdk_call(raise_cancelled)


@pytest.mark.asyncio
async def test_fake_resume_unknown_agent_raises() -> None:
    """Fake resume rejects unknown agent ids."""
    facade = FakeSdkFacade()
    with pytest.raises(ValueError, match="invalid fake agent_id"):
        await facade.resume_agent("missing", workspace="/tmp")


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
