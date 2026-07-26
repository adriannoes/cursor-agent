"""SdkFacade protocol for cursor-agent SDK boundary (PRD-001)."""

from __future__ import annotations

from typing import Protocol

from cursor_agent.facade_logging import LogContext
from cursor_agent.first_party_models import DEFAULT_AGENT_MODEL
from cursor_agent.sdk_facade_models import ModelCatalogEntry, RunResult, StreamCallbacks


class ApiKeyProber(Protocol):
    """Narrow protocol for API-key probe (PRD-017); boolean only — ADR-025."""

    async def probe_api_key(self) -> bool:
        """Return True when the credential is accepted; never identity fields."""
        ...


class ModelCatalogReader(Protocol):
    """Narrow protocol for live model catalog (PRD-017); project DTOs only."""

    async def list_models(self) -> list[ModelCatalogEntry]:
        """Return catalog rows as ``ModelCatalogEntry`` (not raw SDK types)."""
        ...


class SdkFacade(Protocol):
    """Protocol for SDK access; implemented by AsyncSdkFacade and FakeSdkFacade."""

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = DEFAULT_AGENT_MODEL,
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

    async def dispose_agent(self, agent_id: str) -> None:
        """Cancel any active run and release the SDK agent handle."""
        ...

    async def close(self) -> None:
        """Release bridge and internal state."""
        ...

    def has_agent(self, agent_id: str) -> bool:
        """Return True when the facade holds an in-memory agent handle."""
        ...
