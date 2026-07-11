"""Unit tests for SdkFacade types, FakeSdkFacade, and create/MCP wiring (PRD-001)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cursor_agent.sdk_facade import (
    AsyncSdkFacade,
    FakeSdkFacade,
    LogContext,
    RunResult,
    RunStatus,
    StreamCallbacks,
)
from tests.unit.facade_test_fakes import (
    local_option,
    resume_request_options,
    sandbox_enabled,
)


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
    setting_sources = local_option(local_opts, "setting_sources")
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
    assert local_option(local_opts, "setting_sources") == ["project"]


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

    options = resume_request_options(mock_client)
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    setting_sources = local_option(local_opts, "setting_sources")
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

    options = resume_request_options(mock_client)
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert local_option(local_opts, "setting_sources") is None


@pytest.mark.asyncio
async def test_create_agent_uses_grok_and_local_cwd() -> None:
    """create_agent passes grok-4.5 and LocalAgentOptions cwd."""
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
    assert create_kwargs["model"] == "grok-4.5"
    local_opts = create_kwargs["local"]
    assert (
        getattr(local_opts, "cwd", None) == "/repo/path"
        or local_opts.get("cwd") == "/repo/path"
    )


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
    assert sandbox_enabled(local_opts) is None


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

    options = resume_request_options(mock_client)
    assert "mcpServers" not in options
    assert "mcp_servers" not in options
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert sandbox_enabled(local_opts) is None


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
    assert sandbox_enabled(local_opts) is True


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

    options = resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert sandbox_enabled(local_opts) is True


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

    options = resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert sandbox_enabled(local_opts) is True


@pytest.mark.asyncio
async def test_resume_agent_inherits_messaging_mcp_when_tool_profile_omitted() -> None:
    """Cold resume without tool_profile must reuse stored messaging profile and empty MCP."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-messaging-inherit"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(
        workspace="/repo/path", tool_profile="messaging"
    )
    facade._agents.clear()

    resumed_id = await facade.resume_agent(agent_id, workspace="/repo/path")
    assert resumed_id == agent_id

    options = resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert sandbox_enabled(local_opts) is True
