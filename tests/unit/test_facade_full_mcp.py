"""Unit tests for AsyncSdkFacade full-profile MCP create/resume wiring."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from cursor_agent.sdk_facade import AsyncSdkFacade
from tests.unit.facade_test_fakes import (
    FAKE_FULL_BRAVE_KEY,
    FAKE_FULL_GITHUB_TOKEN,
    create_mcp_servers,
    resume_request_options,
    sandbox_enabled,
)


@pytest.mark.asyncio
async def test_full_create_agent_passes_curated_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full create must inject curated mcp_servers (at least playwright)."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-create"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    logger = logging.getLogger("test.facade.full.create")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    facade = AsyncSdkFacade(api_key="test-key", logger=logger)
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", tool_profile="full")

    logger.removeHandler(handler)
    mcp_servers = create_mcp_servers(mock_client)
    assert mcp_servers is not None
    assert set(mcp_servers) == {"brave-search", "github", "playwright"}
    local_opts = mock_client.agents.create.await_args.kwargs["local"]
    assert sandbox_enabled(local_opts) is None

    injected = [json.loads(line) for line in records if "mcp_servers_injected" in line]
    assert len(injected) == 1
    assert injected[0]["event"] == "mcp_servers_injected"
    assert injected[0]["tool_profile"] == "full"
    assert injected[0]["server_names"] == ["brave-search", "github", "playwright"]
    joined = "\n".join(records)
    assert FAKE_FULL_GITHUB_TOKEN not in joined
    assert FAKE_FULL_BRAVE_KEY not in joined


@pytest.mark.asyncio
async def test_full_warm_resume_skips_sdk_when_already_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full warm resume must not call SDK (create already injected curated MCP).

    Warm ``agents.resume`` invalidates the in-memory server agent; cold resume
    still reinjects curated MCP (see ``test_full_cold_resume_reinjects_curated_mcp_servers``).
    """
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-warm"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="full")
    mock_client.agents.resume.reset_mock()

    resumed_id = await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="full",
    )

    assert resumed_id == agent_id
    mock_client.agents.resume.assert_not_called()


@pytest.mark.asyncio
async def test_coding_to_full_resume_reinjects_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm coding agent resumed as full must re-resume with curated MCP."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-coding-to-full"
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
        tool_profile="full",
    )

    mock_client.agents.resume.assert_called_once()
    options = resume_request_options(mock_client)
    mcp_servers = options.get("mcpServers")
    assert isinstance(mcp_servers, dict)
    assert "playwright" in mcp_servers
    assert facade._agent_tool_profiles[agent_id] == "full"


@pytest.mark.asyncio
async def test_full_create_respects_mcp_full_servers_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facade must honor mcp.full.servers allowlist from constructor (config wiring)."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-allowlist"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        mcp_full_servers=["playwright"],
    )
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", tool_profile="full")

    mcp_servers = create_mcp_servers(mock_client)
    assert mcp_servers is not None
    assert set(mcp_servers) == {"playwright"}
    assert "github" not in mcp_servers
    assert "brave-search" not in mcp_servers


@pytest.mark.asyncio
async def test_full_create_github_transport_stdio_wires_command_based_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facade threads mcp_full_github_transport=stdio into command-based github MCP."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-github-stdio"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        mcp_full_servers=["github"],
        mcp_full_github_transport="stdio",
    )
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", tool_profile="full")

    mcp_servers = create_mcp_servers(mock_client)
    assert mcp_servers is not None
    assert set(mcp_servers) == {"github"}
    github = mcp_servers["github"]
    assert "command" in github
    assert "url" not in github


@pytest.mark.asyncio
async def test_full_create_github_transport_default_wires_url_based_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Facade default github transport wires URL-based MCP (not command-based)."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-github-http"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(
        api_key="test-key",
        mcp_full_servers=["github"],
    )
    facade._client = mock_client

    await facade.create_agent(workspace="/repo/path", tool_profile="full")

    mcp_servers = create_mcp_servers(mock_client)
    assert mcp_servers is not None
    assert set(mcp_servers) == {"github"}
    github = mcp_servers["github"]
    assert "url" in github
    assert "command" not in github


@pytest.mark.asyncio
async def test_full_to_messaging_resume_injects_empty_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching warm full → messaging must re-resume with explicit empty MCP."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-to-messaging"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="full")
    await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="messaging",
    )

    mock_client.agents.resume.assert_called_once()
    options = resume_request_options(mock_client)
    assert options.get("mcpServers") == {}
    assert facade._agent_tool_profiles[agent_id] == "messaging"


@pytest.mark.asyncio
async def test_full_to_coding_resume_omits_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching warm full → coding must re-resume and omit mcpServers."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-to-coding"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    agent_id = await facade.create_agent(workspace="/repo", tool_profile="full")
    await facade.resume_agent(
        agent_id,
        workspace="/repo",
        tool_profile="coding",
    )

    mock_client.agents.resume.assert_called_once()
    options = resume_request_options(mock_client)
    assert "mcpServers" not in options
    assert "mcp_servers" not in options
    assert facade._agent_tool_profiles[agent_id] == "coding"


@pytest.mark.asyncio
async def test_full_cold_resume_reinjects_curated_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold resume with tool_profile=full must inject curated mcp_servers."""
    monkeypatch.setenv("GITHUB_PERSONAL_ACCESS_TOKEN", FAKE_FULL_GITHUB_TOKEN)
    monkeypatch.setenv("BRAVE_API_KEY", FAKE_FULL_BRAVE_KEY)

    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-cold"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.resume = AsyncMock(return_value=mock_agent)

    facade = AsyncSdkFacade(api_key="test-key")
    facade._client = mock_client

    await facade.resume_agent(
        "agent-full-cold",
        workspace="/repo",
        tool_profile="full",
    )

    options = resume_request_options(mock_client)
    mcp_servers = options.get("mcpServers")
    assert isinstance(mcp_servers, dict)
    assert "playwright" in mcp_servers
    assert "github" in mcp_servers


@pytest.mark.asyncio
async def test_full_empty_allowlist_does_not_emit_mcp_servers_injected() -> None:
    """Empty curated map must not emit mcp_servers_injected (names-only observability)."""
    mock_agent = AsyncMock()
    mock_agent.agent_id = "agent-full-empty-log"
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=None)

    mock_client = MagicMock()
    mock_client.agents.create = AsyncMock(return_value=mock_agent)

    logger = logging.getLogger("test.facade.full.empty.log")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    facade = AsyncSdkFacade(
        api_key="test-key",
        mcp_full_servers=[],
        logger=logger,
    )
    facade._client = mock_client

    await facade.create_agent(workspace="/repo", tool_profile="full")
    logger.removeHandler(handler)

    mcp_servers = create_mcp_servers(mock_client)
    assert mcp_servers == {}
    assert not any("mcp_servers_injected" in line for line in records)
