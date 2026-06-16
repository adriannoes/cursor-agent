"""Async SDK facade for cursor-agent (PRD-001).

This module hosts ``SdkFacade``, ``AsyncSdkFacade``, and ``FakeSdkFacade``.
It is the only module under ``src/`` allowed to import the Cursor Python SDK.

Stream strategy: drain ``run.messages()`` once, then ``await run.wait()``;
never call ``run.text()`` after consuming messages (PRD-000 double-consume bug).
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, TypeVar

from cursor_agent.facade_logging import LogContext, emit_send_end, emit_send_start

_T = TypeVar("_T")
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_CAP_SECONDS = 30.0
_MCP_PROFILE_STUBS: dict[str, dict[str, Any]] = {
    "coding": {},
    "messaging": {},
}
_MODULE_LOGGER = logging.getLogger(__name__)


class RunStatus(str, Enum):
    """Terminal status for a facade run."""

    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RunResult:
    """Normalized result of a facade send operation."""

    run_id: str
    status: RunStatus
    text: str | None
    usage: dict[str, Any] | None = None


@dataclass(frozen=True)
class StreamCallbacks:
    """Optional streaming callbacks for assistant text and tool events."""

    on_assistant_text: Callable[[str], Awaitable[None]] | None = None
    on_tool_start: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
    on_tool_end: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None


class SdkFacade(Protocol):
    """Protocol for SDK access; implemented by AsyncSdkFacade and FakeSdkFacade."""

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Create a new agent; returns ``agent_id``."""
        ...

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
    ) -> str:
        """Resume an existing agent; returns internal handle key."""
        ...

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Send a message; returns ``RunResult``."""
        ...

    async def cancel(self, agent_id: str) -> None:
        """Cancel an in-flight run for the agent."""
        ...

    async def close(self) -> None:
        """Release bridge and internal state."""
        ...


def _map_run_status(raw_status: object) -> RunStatus:
    """Map SDK or string statuses onto facade ``RunStatus`` values."""
    if isinstance(raw_status, RunStatus):
        return raw_status
    normalized = str(raw_status).lower()
    if normalized == RunStatus.FINISHED.value:
        return RunStatus.FINISHED
    if normalized == RunStatus.CANCELLED.value:
        return RunStatus.CANCELLED
    if normalized in {RunStatus.ERROR.value, "failed"}:
        return RunStatus.ERROR
    return RunStatus.ERROR


def _map_run_result(wait_result: object, *, text: str | None = None) -> RunResult:
    """Map an SDK ``run.wait()`` payload onto ``RunResult``."""
    run_id = getattr(wait_result, "id", None) or getattr(wait_result, "run_id", None)
    if not run_id:
        msg = (
            f"wait_result missing run id: received {wait_result!r}, "
            "expected attribute 'id' or 'run_id'"
        )
        raise ValueError(msg)

    status = _map_run_status(getattr(wait_result, "status", RunStatus.ERROR.value))
    usage = getattr(wait_result, "usage", None)
    if usage is None:
        duration_ms = getattr(wait_result, "duration_ms", None)
        if duration_ms is not None:
            usage = {"duration_ms": duration_ms}

    final_text = text
    if final_text is None:
        final_text = getattr(wait_result, "result", None)

    return RunResult(
        run_id=str(run_id),
        status=status,
        text=final_text,
        usage=usage if isinstance(usage, dict) else None,
    )


def _extract_assistant_delta(message: object) -> str | None:
    """Extract assistant text delta from a single streamed SDK message."""
    message_body = getattr(message, "message", None)
    if message_body is None:
        return None
    content_blocks = getattr(message_body, "content", None) or []
    parts: list[str] = []
    for block in content_blocks:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    if not parts:
        return None
    return "".join(parts)


def _extract_text_from_messages(messages: list[object]) -> str:
    """Concatenate assistant text deltas from drained SDK messages."""
    parts: list[str] = []
    for message in messages:
        delta = _extract_assistant_delta(message)
        if delta:
            parts.append(delta)
    return "".join(parts)


async def _invoke_callback(
    callback: Callable[..., Awaitable[None] | None] | None,
    *args: object,
) -> None:
    """Invoke a stream callback, awaiting when it returns a coroutine."""
    if callback is None:
        return
    result = callback(*args)
    if asyncio.iscoroutine(result):
        await result


async def _dispatch_stream_message(
    message: object,
    callbacks: StreamCallbacks | None,
) -> str | None:
    """Dispatch one streamed SDK message to callbacks; return assistant delta."""
    if callbacks is not None:
        message_type = getattr(message, "type", None)
        if message_type == "tool_call":
            tool_name = str(getattr(message, "name", "unknown"))
            tool_status = str(getattr(message, "status", ""))
            tool_args = getattr(message, "args", None) or {}
            if not isinstance(tool_args, dict):
                tool_args = {}
            if tool_status == "running":
                await _invoke_callback(callbacks.on_tool_start, tool_name, tool_args)
            elif tool_status in {"completed", "error"}:
                payload = {
                    "args": tool_args,
                    "result": getattr(message, "result", None),
                }
                await _invoke_callback(callbacks.on_tool_end, tool_name, payload)

    delta = _extract_assistant_delta(message)
    if delta and callbacks is not None:
        await _invoke_callback(callbacks.on_assistant_text, delta)
    return delta


def _resolve_mcp_servers(tool_profile: str) -> dict[str, Any]:
    """Resolve MCP servers for a tool profile (stub until PRD-005)."""
    if tool_profile in _MCP_PROFILE_STUBS:
        return _MCP_PROFILE_STUBS[tool_profile]
    return {}


def _is_retryable_error(exc: BaseException) -> bool:
    """Return True when an exception advertises ADR-024 retry semantics."""
    return bool(getattr(exc, "is_retryable", False))


def _parse_retry_after_seconds(value: object) -> float | None:
    """Parse retry_after hints from SDK strings or numeric seconds."""
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed >= 0:
            return parsed
    return None


def _retry_after_seconds(exc: BaseException, attempt: int) -> float:
    """Compute delay before the next retry attempt."""
    retry_after = _parse_retry_after_seconds(getattr(exc, "retry_after", None))
    if retry_after is not None:
        return retry_after
    backoff = min(2**attempt, _RETRY_BACKOFF_CAP_SECONDS)
    return float(backoff + random.uniform(0, 0.25))


async def _retry_sdk_call(operation: Callable[[], Awaitable[_T]]) -> _T:
    """Retry a pre-run SDK operation up to three times when retryable."""
    last_error: BaseException | None = None
    for attempt in range(_RETRY_MAX_ATTEMPTS):
        try:
            return await operation()
        except BaseException as exc:
            if not _is_retryable_error(exc):
                raise
            last_error = exc
            if attempt == _RETRY_MAX_ATTEMPTS - 1:
                break
            await asyncio.sleep(_retry_after_seconds(exc, attempt))
    assert last_error is not None
    raise last_error


def _map_sdk_exception(exc: BaseException) -> BaseException:
    """Map SDK and transport exceptions onto cursor-agent errors (ADR-024)."""
    from cursor_agent.errors import (
        AuthError,
        ConfigError,
        CursorAgentError,
        InvalidAgentError,
        NetworkError,
        TimeoutError as AgentTimeoutError,
    )

    if isinstance(exc, CursorAgentError):
        return exc

    try:
        from cursor_sdk.errors import (
            AgentNotFoundError as SdkAgentNotFoundError,
            APITimeoutError as SdkAPITimeoutError,
            AuthenticationError as SdkAuthenticationError,
            ConfigurationError as SdkConfigurationError,
            CursorAgentError as SdkCursorAgentError,
            InternalServerError as SdkInternalServerError,
            NetworkError as SdkNetworkError,
            PermissionDeniedError as SdkPermissionDeniedError,
            RateLimitError as SdkRateLimitError,
        )
    except ImportError:
        SdkCursorAgentError = ()  # type: ignore[assignment,misc]

    if isinstance(exc, SdkCursorAgentError):
        message = str(exc)
        retry_after = _parse_retry_after_seconds(getattr(exc, "retry_after", None))
        is_retryable = bool(getattr(exc, "is_retryable", False))

        if isinstance(exc, (SdkAuthenticationError, SdkPermissionDeniedError)):
            return AuthError(message)
        if isinstance(exc, SdkAPITimeoutError):
            return AgentTimeoutError(message, retry_after=retry_after)
        if isinstance(exc, SdkAgentNotFoundError):
            return InvalidAgentError(message)
        if isinstance(exc, SdkConfigurationError):
            return ConfigError(message)
        if isinstance(
            exc, (SdkNetworkError, SdkInternalServerError, SdkRateLimitError)
        ):
            return NetworkError(message, retry_after=retry_after)
        if is_retryable:
            return NetworkError(message, retry_after=retry_after)
        return ConfigError(message)

    exc_name = exc.__class__.__name__.lower()
    message = str(exc)
    if "auth" in exc_name or "unauthorized" in message.lower():
        return AuthError(message)
    if "timeout" in exc_name:
        return AgentTimeoutError(message)
    if "network" in exc_name or "connection" in exc_name:
        return NetworkError(message)
    return exc


class FakeSdkFacade:
    """In-memory SdkFacade for unit tests without a real SDK bridge."""

    def __init__(
        self,
        *,
        scripted_replies: dict[str, str] | None = None,
        scripted_tool_events: list[tuple[str, dict[str, Any]]] | None = None,
        default_reply: str = "fake reply",
    ) -> None:
        self._scripted_replies = scripted_replies or {}
        self._scripted_tool_events = scripted_tool_events or []
        self._default_reply = default_reply
        self._messages_by_agent: dict[str, list[dict[str, str]]] = {}
        self._agent_profiles: dict[str, str] = {}
        self.send_in_progress = asyncio.Event()
        self._logger = _MODULE_LOGGER
        self._closed = False

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Create a fake agent id and empty message history."""
        _ = workspace, model, runtime_mode
        agent_id = f"fake-{uuid.uuid4().hex[:8]}"
        self._messages_by_agent[agent_id] = []
        self._agent_profiles[agent_id] = tool_profile
        return agent_id

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
    ) -> str:
        """Resume a fake agent when it already exists."""
        _ = workspace, model
        if agent_id not in self._messages_by_agent:
            msg = f"invalid fake agent_id: received {agent_id!r}, expected known agent"
            raise ValueError(msg)
        if tool_profile is not None:
            self._agent_profiles[agent_id] = tool_profile
        return agent_id

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Append the user message and return a scripted assistant reply."""
        if agent_id not in self._messages_by_agent:
            msg = f"invalid fake agent_id: received {agent_id!r}, expected known agent"
            raise ValueError(msg)

        emit_send_start(self._logger, agent_id=agent_id, log_context=log_context)
        started = time.perf_counter()
        self.send_in_progress.set()
        await asyncio.sleep(0)
        run_id = f"fake-run-{uuid.uuid4().hex[:8]}"
        try:
            history = self._messages_by_agent[agent_id]
            history.append({"role": "user", "content": message})

            for tool_name, tool_args in self._scripted_tool_events:
                await _invoke_callback(
                    callbacks.on_tool_start if callbacks else None, tool_name, tool_args
                )
                await _invoke_callback(
                    callbacks.on_tool_end if callbacks else None,
                    tool_name,
                    {"args": tool_args, "result": "ok"},
                )

            profile = self._agent_profiles.get(agent_id, "default")
            reply = self._scripted_replies.get(
                profile, self._scripted_replies.get("default", self._default_reply)
            )
            for char in reply:
                await _invoke_callback(
                    callbacks.on_assistant_text if callbacks else None, char
                )

            history.append({"role": "assistant", "content": reply})
            result = RunResult(
                run_id=run_id,
                status=RunStatus.FINISHED,
                text=reply,
                usage=None,
            )
            emit_send_end(
                self._logger,
                agent_id=agent_id,
                run_id=run_id,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status=RunStatus.FINISHED.value,
                log_context=log_context,
            )
            return result
        finally:
            self.send_in_progress.clear()

    async def cancel(self, agent_id: str) -> None:
        """No-op cancel for fake runs without an active bridge."""
        _ = agent_id

    async def close(self) -> None:
        """Mark the fake facade as closed."""
        self._closed = True


# Task 5.2: first cursor_sdk import in this module.
from cursor_sdk import AsyncClient, LocalAgentOptions  # noqa: E402


class AsyncSdkFacade:
    """Production SdkFacade backed by the Cursor Python SDK bridge."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        bridge_options: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._api_key = api_key
        self._bridge_options = bridge_options or {}
        self._logger = logger or _MODULE_LOGGER
        self._client: AsyncClient | None = None
        self._agents: dict[str, Any] = {}
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
        _ = runtime_mode
        client = self._require_client()

        async def _create() -> str:
            agent = await client.agents.create(
                model=model,
                local=LocalAgentOptions(cwd=workspace),
                api_key=self._api_key,
            )
            await agent.__aenter__()
            self._agents[agent.agent_id] = agent
            self._agent_tool_profiles[agent.agent_id] = tool_profile
            return agent.agent_id

        try:
            return await _retry_sdk_call(_create)
        except BaseException as exc:
            raise _map_sdk_exception(exc) from exc

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
    ) -> str:
        """Resume an SDK agent and re-inject MCP servers for the profile."""
        client = self._require_client()
        profile = tool_profile or self._agent_tool_profiles.get(agent_id, "coding")
        options: dict[str, Any] = {
            "local": LocalAgentOptions(cwd=workspace),
            "mcp_servers": _resolve_mcp_servers(profile),
        }
        if model is not None:
            options["model"] = model

        async def _resume() -> str:
            agent = await client.agents.resume(agent_id, options)
            await agent.__aenter__()
            self._agents[agent.agent_id] = agent
            self._agent_tool_profiles[agent.agent_id] = profile
            return agent.agent_id

        try:
            return await _retry_sdk_call(_resume)
        except BaseException as exc:
            raise _map_sdk_exception(exc) from exc

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
            run = await _retry_sdk_call(_send)
        except BaseException as exc:
            raise _map_sdk_exception(exc) from exc

        self._active_runs[agent_id] = run
        text_parts: list[str] = []
        cancelled = False
        try:
            async for stream_message in run.messages():
                if agent_id in self._cancelled_agents:
                    cancelled = True
                    break
                delta = await _dispatch_stream_message(stream_message, callbacks)
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
                result = _map_run_result(wait_result, text=streamed_text)
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
