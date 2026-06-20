"""SdkFacade protocol for cursor-agent SDK boundary (PRD-001)."""

from __future__ import annotations

from typing import Protocol

from cursor_agent.facade_logging import LogContext
from cursor_agent.sdk_facade_models import RunResult, StreamCallbacks


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
        runtime_mode: str = "local",
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

    def has_agent(self, agent_id: str) -> bool:
        """Return True when the facade holds an in-memory agent handle."""
        ...
