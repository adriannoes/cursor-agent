"""Shared helpers for CLI REPL unit tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from cursor_agent.cli.repl_session import run_repl
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import (
    FakeSdkFacade,
    RunResult,
    RunStatus,
    StreamCallbacks,
)
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


def expected_session_key(cwd: str) -> str:
    """Return the expected cli:default session key for a workspace cwd."""
    absolute = str(Path(cwd).resolve())
    workspace_hash = hashlib.sha256(absolute.encode()).hexdigest()[:8]
    return f"cli:default:{workspace_hash}"


async def line_reader(*lines: str) -> AsyncIterator[str]:
    """Yield scripted REPL input lines in order."""
    for line in lines:
        yield line


async def seed_session(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    workspace: str = "/tmp/workspace",
    runtime: str = "local",
) -> str:
    """Create a facade agent and persist a matching session row."""
    agent_id = await facade.create_agent(workspace=workspace)
    record = await session_store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=runtime,
        )
    )
    return record.id


class SendSpyPool(SessionAgentPool):
    """SessionAgentPool that records send keyword arguments."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.send_calls: list[dict[str, object]] = []

    async def send(
        self,
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
    ) -> RunResult:
        """Record send parameters and delegate to the parent pool."""
        self.send_calls.append(
            {
                "session_key": session_key,
                "message": message,
                "session_id": session_id,
                "callbacks": callbacks,
                "blocking": blocking,
            }
        )
        return await super().send(
            session_key,
            message,
            session_id=session_id,
            callbacks=callbacks,
            blocking=blocking,
        )


class GetSpyPool(SessionAgentPool):
    """SessionAgentPool that records get invocations."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.get_calls: list[dict[str, object]] = []

    async def get(
        self,
        session_key: str,
        session_id: str | None = None,
    ) -> object:
        """Record get parameters and delegate to the parent pool."""
        self.get_calls.append({"session_key": session_key, "session_id": session_id})
        return await super().get(session_key, session_id=session_id)


class CreateAgentTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records create_agent invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.create_agent_calls: list[dict[str, object]] = []

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Record create_agent parameters and delegate to the parent fake."""
        self.create_agent_calls.append(
            {
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
                "runtime_mode": runtime_mode,
            }
        )
        return await super().create_agent(
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )


async def drive_repl(
    pool: SessionAgentPool,
    session_key: str,
    store: SessionStore,
    config: CursorAgentConfig,
    facade: FakeSdkFacade,
    *,
    lines: tuple[str, ...],
    writer: Callable[[str], None],
    stream_writer: Callable[[str], None] | None = None,
    auto_resume: bool = False,
) -> RunStatus | None:
    """Invoke ``run_repl`` with the PRD-003 keyword-only contract."""
    return await run_repl(
        pool,
        session_key,
        store,
        config=config,
        facade=facade,
        reader=line_reader(*lines),
        writer=writer,
        stream_writer=stream_writer,
        auto_resume=auto_resume,
    )
