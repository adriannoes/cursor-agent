"""Async SDK facade for cursor-agent (PRD-001).

This module hosts ``SdkFacade`` and ``AsyncSdkFacade``. It is an approved
``cursor_sdk`` import boundary together with ``sdk_error_mapping``.

Stream strategy: drain ``run.messages()`` once, then ``await run.wait()``;
never call ``run.text()`` after consuming messages (PRD-000 double-consume bug).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

from cursor_agent.facade_logging import LogContext, emit_send_end, emit_send_start
from cursor_agent.sdk_error_mapping import map_sdk_exception
from cursor_agent.sdk_facade_models import RunResult, RunStatus, StreamCallbacks
from cursor_agent.sdk_facade_protocol import SdkFacade
from cursor_agent.sdk_fake import FakeSdkFacade
from cursor_agent.sdk_retry import retry_sdk_call
from cursor_agent.sdk_streaming import (
    dispatch_stream_message,
    extract_assistant_delta,
    extract_text_from_messages,
    map_run_result,
)
from cursor_agent.tool_profile_policy import (
    mcp_servers_override_for_profile,
    passes_mcp_servers_on_resume,
    sandbox_enabled,
)

_MODULE_LOGGER = logging.getLogger(__name__)

# Backward-compatible private aliases for tests and internal callers.
_map_run_result = map_run_result
_extract_assistant_delta = extract_assistant_delta
_extract_text_from_messages = extract_text_from_messages
_map_sdk_exception = map_sdk_exception


# SDK import boundary (see AGENTS.md).
from cursor_sdk import AsyncClient, LocalAgentOptions, SandboxOptions  # noqa: E402
from cursor_sdk.types import options_to_json  # noqa: E402


def _resolve_sandbox_options(tool_profile: str) -> SandboxOptions | None:
    """Return SDK sandbox options for a tool profile; messaging enables sandbox."""
    if sandbox_enabled(tool_profile):
        return SandboxOptions(enabled=True)
    return None


def _build_local_agent_options(
    *,
    workspace: str,
    setting_sources: list[str] | None,
    tool_profile: str = "coding",
) -> LocalAgentOptions:
    """Build SDK local options with cwd, optional setting_sources, and sandbox."""
    sandbox_options = _resolve_sandbox_options(tool_profile)
    if setting_sources is None and sandbox_options is None:
        return LocalAgentOptions(cwd=workspace)
    if setting_sources is None:
        return LocalAgentOptions(cwd=workspace, sandbox_options=sandbox_options)
    if sandbox_options is None:
        return LocalAgentOptions(cwd=workspace, setting_sources=setting_sources)
    return LocalAgentOptions(
        cwd=workspace,
        setting_sources=setting_sources,
        sandbox_options=sandbox_options,
    )


class AsyncSdkFacade:
    """Production SdkFacade backed by the Cursor Python SDK bridge."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        bridge_options: dict[str, Any] | None = None,
        local_setting_sources: list[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_key = api_key
        self._bridge_options = bridge_options or {}
        self._local_setting_sources = local_setting_sources
        self._logger = logger or _MODULE_LOGGER
        self._client: AsyncClient | None = None
        self._agents: dict[str, Any] = {}
        self._agent_models: dict[str, str] = {}
        self._agent_tool_profiles: dict[str, str] = {}
        self._active_runs: dict[str, Any] = {}
        self._cancelled_agents: set[str] = set()
        self._closed = False

    async def __aenter__(self) -> AsyncSdkFacade:
        """Launch the SDK bridge and return this facade."""
        workspace = self._bridge_options.get("workspace")
        if workspace is None:
            workspace = os.getcwd()
        self._client = await AsyncClient.launch_bridge(
            workspace=str(workspace),
            **{
                key: value
                for key, value in self._bridge_options.items()
                if key != "workspace"
            },
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        """Dispose bridge resources on context exit."""
        _ = exc_type, exc, tb
        await self.close()

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Create a local SDK agent and register it by ``agent_id``."""
        client = self._require_client()
        local_setting_sources = (
            self._local_setting_sources if runtime_mode == "local" else None
        )

        mcp_override = mcp_servers_override_for_profile(tool_profile)
        create_options: dict[str, Any] | None = None
        if mcp_override is not None:
            create_options = {"mcp_servers": mcp_override}

        async def _create() -> str:
            local_options = _build_local_agent_options(
                workspace=workspace,
                setting_sources=local_setting_sources,
                tool_profile=tool_profile,
            )
            if create_options is None:
                agent = await client.agents.create(
                    model=model,
                    local=local_options,
                    api_key=self._api_key,
                )
            else:
                agent = await client.agents.create(
                    create_options,
                    model=model,
                    local=local_options,
                    api_key=self._api_key,
                )
            await agent.__aenter__()
            self._agents[agent.agent_id] = agent
            self._agent_models[agent.agent_id] = model
            self._agent_tool_profiles[agent.agent_id] = tool_profile
            return agent.agent_id

        try:
            return await retry_sdk_call(_create)
        except BaseException as exc:
            raise map_sdk_exception(exc) from exc

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Resume an SDK agent and re-inject MCP servers for the profile."""
        profile = tool_profile or self._agent_tool_profiles.get(agent_id, "coding")
        if agent_id in self._agents:
            cached_model = self._agent_models.get(agent_id)
            cached_profile = self._agent_tool_profiles.get(agent_id, "coding")
            model_unchanged = model is None or model == cached_model
            profile_unchanged = profile == cached_profile
            if model_unchanged and profile_unchanged:
                self._agent_tool_profiles[agent_id] = profile
                return agent_id

        client = self._require_client()
        local_setting_sources = (
            self._local_setting_sources if runtime_mode == "local" else None
        )
        local_options = _build_local_agent_options(
            workspace=workspace,
            setting_sources=local_setting_sources,
            tool_profile=profile,
        )
        resume_payload: dict[str, Any] = {}
        if passes_mcp_servers_on_resume(profile):
            mcp_override = mcp_servers_override_for_profile(profile)
            if mcp_override is not None:
                resume_payload["mcp_servers"] = mcp_override
        request_options = options_to_json(
            resume_payload,
            local=local_options,
            model=model,
            api_key=self._api_key,
        )

        async def _resume() -> str:
            agent = await client.agents.resume(agent_id, request_options)
            await agent.__aenter__()
            self._agents[agent.agent_id] = agent
            if model is not None:
                self._agent_models[agent.agent_id] = model
            self._agent_tool_profiles[agent.agent_id] = profile
            return agent.agent_id

        try:
            return await retry_sdk_call(_resume)
        except BaseException as exc:
            raise map_sdk_exception(exc) from exc

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Send a user message, stream callbacks, and return a mapped result."""
        agent = self._require_agent(agent_id)
        emit_send_start(self._logger, agent_id=agent_id, log_context=log_context)
        started = time.perf_counter()
        self._cancelled_agents.discard(agent_id)

        async def _send() -> Any:
            return await agent.send(message)

        try:
            run = await retry_sdk_call(_send)
        except BaseException as exc:
            raise map_sdk_exception(exc) from exc

        self._active_runs[agent_id] = run
        text_parts: list[str] = []
        cancelled = False
        try:
            async for stream_message in run.messages():
                if agent_id in self._cancelled_agents:
                    cancelled = True
                    break
                delta = await dispatch_stream_message(stream_message, callbacks)
                if delta:
                    text_parts.append(delta)

            if cancelled or agent_id in self._cancelled_agents:
                result = RunResult(
                    run_id=str(
                        getattr(run, "run_id", f"cancelled-{uuid.uuid4().hex[:8]}")
                    ),
                    status=RunStatus.CANCELLED,
                    text="".join(text_parts) or None,
                    usage=None,
                )
            else:
                wait_result = await run.wait()
                streamed_text = "".join(text_parts) or None
                result = map_run_result(wait_result, text=streamed_text)
        finally:
            self._active_runs.pop(agent_id, None)
            self._cancelled_agents.discard(agent_id)

        emit_send_end(
            self._logger,
            agent_id=agent_id,
            run_id=result.run_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            status=result.status.value,
            log_context=log_context,
        )
        return result

    async def cancel(self, agent_id: str) -> None:
        """Cancel an active run for the given agent when one exists."""
        self._cancelled_agents.add(agent_id)
        active_run = self._active_runs.get(agent_id)
        if active_run is not None:
            active_run.cancel()

    async def close(self) -> None:
        """Close registered agents and dispose the SDK bridge."""
        if self._closed:
            return
        self._closed = True

        for agent in list(self._agents.values()):
            try:
                await agent.__aexit__(None, None, None)
            except Exception:
                self._logger.debug("agent close failed", exc_info=True)
        self._agents.clear()

        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def has_agent(self, agent_id: str) -> bool:
        """Return True when the facade holds a live SDK agent handle."""
        return agent_id in self._agents

    def _require_client(self) -> AsyncClient:
        if self._client is None:
            msg = "AsyncSdkFacade bridge is not initialized; use 'async with' first"
            raise RuntimeError(msg)
        return self._client

    def _require_agent(self, agent_id: str) -> Any:
        agent = self._agents.get(agent_id)
        if agent is None:
            msg = f"unknown agent_id: received {agent_id!r}, expected registered agent"
            raise ValueError(msg)
        return agent


__all__ = [
    "AsyncSdkFacade",
    "FakeSdkFacade",
    "LogContext",
    "RunResult",
    "RunStatus",
    "SdkFacade",
    "StreamCallbacks",
]
