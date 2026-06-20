"""In-memory SdkFacade for unit tests without a real SDK bridge."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from cursor_agent.facade_logging import LogContext, emit_send_end, emit_send_start
from cursor_agent.sdk_facade_models import RunResult, RunStatus, StreamCallbacks
from cursor_agent.sdk_streaming import invoke_callback

_MODULE_LOGGER = logging.getLogger(__name__)


class FakeSdkFacade:
    """In-memory SdkFacade for unit tests without a real SDK bridge."""

    def __init__(
        self,
        *,
        scripted_replies: dict[str, str] | None = None,
        scripted_tool_events: list[tuple[str, dict[str, Any]]] | None = None,
        default_reply: str = "fake reply",
        send_release: asyncio.Event | None = None,
    ) -> None:
        self._scripted_replies = scripted_replies or {}
        self._scripted_tool_events = scripted_tool_events or []
        self._default_reply = default_reply
        self._messages_by_agent: dict[str, list[dict[str, str]]] = {}
        self._agent_profiles: dict[str, str] = {}
        # When set, ``send`` blocks until ``send_release`` is set (deterministic busy tests).
        self._send_release = send_release
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
        runtime_mode: str = "local",
    ) -> str:
        """Resume a fake agent when it already exists."""
        _ = workspace, model, runtime_mode
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
        run_id = f"fake-run-{uuid.uuid4().hex[:8]}"
        try:
            if self._send_release is not None:
                await self._send_release.wait()
            history = self._messages_by_agent[agent_id]
            history.append({"role": "user", "content": message})

            for tool_name, tool_args in self._scripted_tool_events:
                await invoke_callback(
                    callbacks.on_tool_start if callbacks else None, tool_name, tool_args
                )
                await invoke_callback(
                    callbacks.on_tool_end if callbacks else None,
                    tool_name,
                    {"args": tool_args, "result": "ok"},
                )

            profile = self._agent_profiles.get(agent_id, "default")
            reply = self._scripted_replies.get(
                profile, self._scripted_replies.get("default", self._default_reply)
            )
            for char in reply:
                await invoke_callback(
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

    def has_agent(self, agent_id: str) -> bool:
        """Return True when the fake facade tracks the agent in memory."""
        return agent_id in self._messages_by_agent

    async def close(self) -> None:
        """Mark the fake facade as closed."""
        self._closed = True
