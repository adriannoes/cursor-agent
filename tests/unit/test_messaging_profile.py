"""Unit tests for messaging profile SDK options in AsyncSdkFacade (PRD-005)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from cursor_agent.sdk_facade import AsyncSdkFacade


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


def _sandbox_enabled(local_opts: object) -> bool | None:
    """Return sandbox_options.enabled from LocalAgentOptions or a mapping."""
    sandbox = _local_option(local_opts, "sandbox_options")
    if sandbox is None:
        return None
    if isinstance(sandbox, dict):
        enabled = sandbox.get("enabled")
        return enabled if isinstance(enabled, bool) else None
    return getattr(sandbox, "enabled", None)


def _create_kwargs(mock_client: MagicMock) -> dict[str, Any]:
    """Extract kwargs passed to client.agents.create."""
    return mock_client.agents.create.await_args.kwargs


def _create_mcp_servers(mock_client: MagicMock) -> dict[str, Any] | None:
    """Extract mcp_servers from client.agents.create positional options or kwargs."""
    call = mock_client.agents.create.await_args
    options = call.args[0] if call.args else None
    if isinstance(options, dict) and "mcp_servers" in options:
        mcp_servers = options["mcp_servers"]
        return mcp_servers if isinstance(mcp_servers, dict) else None
    kwarg_value = call.kwargs.get("mcp_servers")
    return kwarg_value if isinstance(kwarg_value, dict) else None


def _resume_options(mock_client: MagicMock) -> dict[str, Any]:
    """Extract resume options dict from client.agents.resume."""
    resume_args = mock_client.agents.resume.await_args
    options = (
        resume_args.args[1]
        if len(resume_args.args) > 1
        else resume_args.kwargs.get("options")
    )
    assert isinstance(options, dict)
    json.dumps(options)
    return options


@pytest.fixture
def mock_sdk_agent() -> AsyncMock:
    """Async agent double returned by create/resume."""
    agent = AsyncMock()
    agent.agent_id = "agent-messaging"
    agent.__aenter__ = AsyncMock(return_value=agent)
    agent.__aexit__ = AsyncMock(return_value=None)
    return agent


@pytest.fixture
def facade_with_client(mock_sdk_agent: AsyncMock) -> tuple[AsyncSdkFacade, MagicMock]:
    """AsyncSdkFacade with a mocked SDK client."""
    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_sdk_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_sdk_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client
    return facade, mock_client


@pytest.mark.asyncio
async def test_messaging_create_agent_passes_empty_mcp_servers(
    facade_with_client: tuple[AsyncSdkFacade, MagicMock],
) -> None:
    """Messaging create must pass explicit empty MCP servers."""
    facade, mock_client = facade_with_client

    await facade.create_agent(
        workspace="/repo/path",
        tool_profile="messaging",
    )

    assert _create_mcp_servers(mock_client) == {}


@pytest.mark.asyncio
async def test_messaging_create_agent_passes_sandbox_enabled(
    facade_with_client: tuple[AsyncSdkFacade, MagicMock],
) -> None:
    """Messaging create must enable SDK sandbox in local options."""
    facade, mock_client = facade_with_client

    await facade.create_agent(
        workspace="/repo/path",
        tool_profile="messaging",
    )

    local_opts = _create_kwargs(mock_client)["local"]
    assert _sandbox_enabled(local_opts) is True


@pytest.mark.asyncio
async def test_messaging_resume_agent_passes_empty_mcp_servers(
    facade_with_client: tuple[AsyncSdkFacade, MagicMock],
) -> None:
    """Messaging resume must pass explicit empty MCP servers."""
    facade, mock_client = facade_with_client

    await facade.resume_agent(
        "agent-messaging",
        workspace="/repo",
        tool_profile="messaging",
    )

    options = _resume_options(mock_client)
    assert options.get("mcpServers") == {}


@pytest.mark.asyncio
async def test_messaging_resume_agent_passes_sandbox_enabled(
    facade_with_client: tuple[AsyncSdkFacade, MagicMock],
) -> None:
    """Messaging resume must enable SDK sandbox in local options."""
    facade, mock_client = facade_with_client

    await facade.resume_agent(
        "agent-messaging",
        workspace="/repo",
        tool_profile="messaging",
    )

    options = _resume_options(mock_client)
    local_opts = options.get("local")
    assert isinstance(local_opts, dict)
    assert _sandbox_enabled(local_opts) is True


@pytest.mark.asyncio
async def test_resume_in_memory_profile_change_tracks_profile_without_sdk_call(
    facade_with_client: tuple[AsyncSdkFacade, MagicMock],
) -> None:
    """In-memory resume updates tracked profile but skips SDK when agent is loaded."""
    facade, mock_client = facade_with_client

    agent_id = await facade.create_agent(
        workspace="/repo/path",
        tool_profile="coding",
    )
    resumed_id = await facade.resume_agent(
        agent_id,
        workspace="/repo/path",
        tool_profile="messaging",
    )

    assert resumed_id == agent_id
    assert facade._agent_tool_profiles[agent_id] == "messaging"
    mock_client.agents.resume.assert_not_called()


@pytest.mark.asyncio
async def test_messaging_create_then_resume_in_memory_skips_sdk_mcp_reinjection(
    facade_with_client: tuple[AsyncSdkFacade, MagicMock],
) -> None:
    """Same-process create→resume messaging must still cold-call SDK for MCP injection."""
    facade, mock_client = facade_with_client

    agent_id = await facade.create_agent(
        workspace="/repo/path",
        tool_profile="messaging",
    )
    await facade.resume_agent(
        agent_id,
        workspace="/repo/path",
        tool_profile="messaging",
    )

    mock_client.agents.create.assert_called_once()
    mock_client.agents.resume.assert_not_called()
