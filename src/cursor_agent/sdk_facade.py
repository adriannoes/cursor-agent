"""Async SDK facade for cursor-agent (PRD-001).

This module hosts ``SdkFacade`` and ``AsyncSdkFacade``. It is an approved
``cursor_sdk`` import boundary together with ``sdk_error_mapping``.

Stream strategy: drain ``run.messages()`` once, then ``await run.wait()``;
never call ``run.text()`` after consuming messages (PRD-000 double-consume bug).

PRD-017 Q2 LOCKED (operator CLI hygiene):

- API-key probe = SDK ``AsyncCursor.me`` (async ``Cursor.me``) via
  module-level ``probe_api_key``. Return boolean ok only; never expose
  ``SDKUser`` identity fields (``api_key_name``, ``user_email``, names,
  etc. — ADR-025).
- Live model catalog = SDK ``AsyncCursor.models.list`` via module-level
  ``list_models``. Emit project DTOs (``ModelCatalogEntry``), not raw SDK
  types, to the CLI.
- Both use an **ephemeral** bridge lifecycle:
  ``AsyncClient.launch_bridge`` → single call → ``aclose()``.
- Named timeouts live **per surface**
  (``AUTH_PROBE_TIMEOUT_SECONDS``, ``MODELS_LIST_TIMEOUT_SECONDS``) — do not
  reuse ``usage.DEFAULT_TIMEOUT_SECONDS`` (dashboard HTTP only).
- Bridge launch/spawn failure is an environment fault, not auth: map via
  existing ``map_sdk_exception`` → ``ConfigError``. WHY: ``sdk_error_mapping``
  already maps ``cursor_sdk.errors.ConfigurationError`` (and other non-auth
  SDK config/env faults) to ``ConfigError`` — do not invent a second mapping
  layer in the CLI or facade.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, TypeVar

from cursor_agent.errors import ConfigError
from cursor_agent.facade_logging import (
    LogContext,
    emit_mcp_servers_injected,
    emit_send_end,
    emit_send_start,
)
from cursor_agent.first_party_models import DEFAULT_AGENT_MODEL
from cursor_agent.sdk_error_mapping import map_sdk_exception
from cursor_agent.sdk_facade_models import (
    ModelCatalogEntry,
    RunResult,
    RunStatus,
    StreamCallbacks,
)
from cursor_agent.sdk_facade_protocol import SdkFacade
from cursor_agent.sdk_fake import FakeSdkFacade
from cursor_agent.sdk_retry import retry_sdk_call
from cursor_agent.sdk_streaming import (
    dispatch_stream_message,
    extract_assistant_delta,
    extract_text_from_messages,
    map_run_result,
)
from cursor_agent.mcp_registry import GithubTransport
from cursor_agent.tool_profile_policy import (
    mcp_servers_override_for_profile,
    passes_mcp_servers_on_cold_resume,
    sandbox_enabled,
)

_MODULE_LOGGER = logging.getLogger(__name__)

# Backward-compatible private aliases for tests and internal callers.
_map_run_result = map_run_result
_extract_assistant_delta = extract_assistant_delta
_extract_text_from_messages = extract_text_from_messages
_map_sdk_exception = map_sdk_exception

# WHY: bridge spawn + me/list RPC dwarfs the 15s usage-dashboard HTTP timeout;
# keep probe/list budgets independent so a slow bridge does not inherit the
# short dashboard constant (and vice versa).
AUTH_PROBE_TIMEOUT_SECONDS: float = 45.0
MODELS_LIST_TIMEOUT_SECONDS: float = 60.0

_T = TypeVar("_T")


# SDK import boundary (see AGENTS.md).
from cursor_sdk import (  # noqa: E402
    AsyncClient,
    AsyncCursor,
    LocalAgentOptions,
    SandboxOptions,
)
from cursor_sdk.types import options_to_json  # noqa: E402


async def _with_ephemeral_bridge(
    *,
    timeout_seconds: float,
    operation: Callable[[AsyncClient], Awaitable[_T]],
) -> _T:
    """Run ``operation`` on a one-shot bridge, always ``aclose``-ing the client."""
    client: AsyncClient | None = None
    try:
        try:
            client = await AsyncClient.launch_bridge(
                workspace=os.getcwd(),
                timeout=timeout_seconds,
            )
            return await operation(client)
        except Exception as exc:
            # WHY: keep KeyboardInterrupt/CancelledError out of map_sdk_exception.
            raise map_sdk_exception(exc) from exc
    finally:
        if client is not None:
            await client.aclose()


def _model_catalog_entry_from_sdk(raw: Any) -> ModelCatalogEntry:
    """Map one SDK model row to ``ModelCatalogEntry`` (no raw SDK leak).

    Raises:
        ConfigError: When ``id`` or ``display_name`` is missing/empty so CLI
            callers that only catch ``CursorAgentError`` stay on the domain path.
    """
    model_id = str(getattr(raw, "id", "") or "")
    display_name = str(getattr(raw, "display_name", "") or "")
    if not model_id or not display_name:
        raise ConfigError(
            "invalid SDK model row: received "
            f"id={model_id!r} display_name={display_name!r}, "
            "expected non-empty id and display_name"
        )
    description_raw = getattr(raw, "description", None)
    description = str(description_raw) if description_raw else None
    return ModelCatalogEntry(
        id=model_id,
        display_name=display_name,
        description=description,
    )


async def probe_api_key(
    *,
    api_key: str,
    timeout_seconds: float | None = None,
) -> bool:
    """Probe ``CURSOR_API_KEY`` via ephemeral ``AsyncCursor.me``; return bool only.

    Example::

        ok = await probe_api_key(api_key=os.environ["CURSOR_API_KEY"])
    """
    timeout = AUTH_PROBE_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds

    async def _me(client: AsyncClient) -> bool:
        # WHY: discard SDKUser identity — ADR-025 boolean-only probe surface.
        await AsyncCursor.me(client=client, api_key=api_key)
        return True

    return await _with_ephemeral_bridge(timeout_seconds=timeout, operation=_me)


async def list_models(
    *,
    api_key: str,
    timeout_seconds: float | None = None,
) -> list[ModelCatalogEntry]:
    """List live models via ephemeral ``AsyncCursor.models.list`` as project DTOs.

    Example::

        rows = await list_models(api_key=os.environ["CURSOR_API_KEY"])
    """
    timeout = (
        MODELS_LIST_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
    )

    async def _catalog(client: AsyncClient) -> list[ModelCatalogEntry]:
        raw_models = await AsyncCursor.models.list(
            client=client,
            api_key=api_key,
        )
        return [_model_catalog_entry_from_sdk(row) for row in raw_models]

    return await _with_ephemeral_bridge(timeout_seconds=timeout, operation=_catalog)


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


def _resume_cache_key(
    *,
    model: str | None,
    tool_profile: str,
) -> str:
    """Build a stable key for in-memory resume short-circuit decisions."""
    return f"{model}:{tool_profile}"


def _emit_full_mcp_injection(
    logger: logging.Logger,
    *,
    tool_profile: str,
    mcp_override: dict[str, Any] | None,
) -> None:
    """Emit mcp_servers_injected for full when servers were actually injected.

    Empty maps (explicit empty allowlist or every server omitted) stay silent —
    ADR-029 observability is about injected server names, not empty payloads.
    """
    if tool_profile != "full" or not mcp_override:
        return
    emit_mcp_servers_injected(
        logger,
        tool_profile=tool_profile,
        server_names=sorted(mcp_override),
    )


class AsyncSdkFacade:
    """Production SdkFacade backed by the Cursor Python SDK bridge."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        bridge_options: dict[str, Any] | None = None,
        local_setting_sources: list[str] | None = None,
        mcp_full_servers: Sequence[str] | None = None,
        mcp_full_github_transport: GithubTransport = "http",
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_key = api_key
        self._bridge_options = bridge_options or {}
        self._local_setting_sources = local_setting_sources
        # From config.mcp.full.servers; None means all curated ids (ADR-029 Q3).
        self._mcp_full_servers: Sequence[str] | None = mcp_full_servers
        # From config.mcp.full.github_transport; default http (Wave 5).
        self._mcp_full_github_transport: GithubTransport = mcp_full_github_transport
        self._logger = logger or _MODULE_LOGGER
        self._client: AsyncClient | None = None
        self._agents: dict[str, Any] = {}
        self._agent_tool_profiles: dict[str, str] = {}
        self._agent_models: dict[str, str | None] = {}
        self._active_runs: dict[str, Any] = {}
        self._cancelled_agents: set[str] = set()
        self._closed = False

    def _mcp_override_for_facade(self, tool_profile: str) -> dict[str, Any] | None:
        """Resolve MCP override; full uses constructor allowlist + process environ."""
        return mcp_servers_override_for_profile(
            tool_profile,
            allowlist=self._mcp_full_servers,
            environ=os.environ,
            github_transport=self._mcp_full_github_transport,
        )

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
        model: str = DEFAULT_AGENT_MODEL,
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Create a local SDK agent and register it by ``agent_id``."""
        client = self._require_client()
        local_setting_sources = (
            self._local_setting_sources if runtime_mode == "local" else None
        )

        mcp_override = self._mcp_override_for_facade(tool_profile)
        create_options: dict[str, Any] | None = None
        if mcp_override is not None:
            create_options = {"mcp_servers": mcp_override}
            _emit_full_mcp_injection(
                self._logger,
                tool_profile=tool_profile,
                mcp_override=mcp_override,
            )

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
            self._agent_tool_profiles[agent.agent_id] = tool_profile
            self._agent_models[agent.agent_id] = model
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
        """Resume an SDK agent; reinject MCP on cold resume for messaging/full.

        Warm agents already in ``_agents`` with the same ``model:tool_profile``
        short-circuit for every profile. SDK ``agents.resume`` on an in-memory
        handle returns a new object; disposing the previous one (or the warm
        resume itself) invalidates the server agent (``Unknown agent`` /
        internal error). MCP overrides were applied on create; cold resume
        (agent not in memory) still reinjects via ``passes_mcp_servers_on_cold_resume``.
        """
        profile = tool_profile or self._agent_tool_profiles.get(agent_id, "coding")
        effective_model = (
            model if model is not None else self._agent_models.get(agent_id)
        )
        requested_key = _resume_cache_key(model=effective_model, tool_profile=profile)
        if agent_id in self._agents:
            cached_key = _resume_cache_key(
                model=self._agent_models.get(agent_id),
                tool_profile=self._agent_tool_profiles.get(agent_id, "coding"),
            )
            if cached_key == requested_key:
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
        if passes_mcp_servers_on_cold_resume(profile):
            mcp_override = self._mcp_override_for_facade(profile)
            if mcp_override is not None:
                resume_payload["mcp_servers"] = mcp_override
                _emit_full_mcp_injection(
                    self._logger,
                    tool_profile=profile,
                    mcp_override=mcp_override,
                )
        request_options = options_to_json(
            resume_payload,
            local=local_options,
            model=model,
            api_key=self._api_key,
        )

        async def _resume() -> str:
            agent = await client.agents.resume(agent_id, request_options)
            await agent.__aenter__()
            previous = self._agents.get(agent.agent_id)
            if previous is not None and previous is not agent:
                try:
                    await previous.__aexit__(None, None, None)
                except Exception:
                    self._logger.debug(
                        "agent dispose failed during resume for agent_id=%s",
                        agent.agent_id,
                        exc_info=True,
                    )
            self._agents[agent.agent_id] = agent
            self._agent_tool_profiles[agent.agent_id] = profile
            if model is not None:
                self._agent_models[agent.agent_id] = model
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

    async def dispose_agent(self, agent_id: str) -> None:
        """Cancel any active run and release the SDK agent handle from memory."""
        await self.cancel(agent_id)
        agent = self._agents.pop(agent_id, None)
        self._agent_tool_profiles.pop(agent_id, None)
        self._agent_models.pop(agent_id, None)
        self._cancelled_agents.discard(agent_id)
        if agent is None:
            return
        try:
            await agent.__aexit__(None, None, None)
        except Exception:
            self._logger.debug(
                "agent dispose failed for agent_id=%s",
                agent_id,
                exc_info=True,
            )

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
    "AUTH_PROBE_TIMEOUT_SECONDS",
    "AsyncSdkFacade",
    "FakeSdkFacade",
    "LogContext",
    "MODELS_LIST_TIMEOUT_SECONDS",
    "ModelCatalogEntry",
    "RunResult",
    "RunStatus",
    "SdkFacade",
    "StreamCallbacks",
    "list_models",
    "probe_api_key",
]
