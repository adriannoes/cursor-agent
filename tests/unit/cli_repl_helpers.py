"""Shared helpers for CLI REPL unit tests."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.rich_display import ThinkingDisplay
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.first_party_models import DEFAULT_AGENT_MODEL
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import (
    FakeSdkFacade,
    RunResult,
    RunStatus,
    StreamCallbacks,
)
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


class FakeThinkingDisplay:
    """Recording ThinkingDisplay for REPL / slash-command wiring assertions (PRD-018).

    Shares an ``events`` list so call order relative to ``pool.send`` can be
    asserted (``start_thinking`` → ``pool.send`` → ``stop_thinking``).
    """

    def __init__(self, events: list[str] | None = None) -> None:
        self.events: list[str] = events if events is not None else []

    def start_thinking(self) -> None:
        """Record a ``start_thinking`` call on the shared event timeline."""
        self.events.append("start_thinking")

    def stop_thinking(self) -> None:
        """Record a ``stop_thinking`` call on the shared event timeline."""
        self.events.append("stop_thinking")


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
        model_override: str | None = None,
    ) -> RunResult:
        """Record send parameters and delegate to the parent pool."""
        self.send_calls.append(
            {
                "session_key": session_key,
                "message": message,
                "session_id": session_id,
                "callbacks": callbacks,
                "blocking": blocking,
                "model_override": model_override,
            }
        )
        return await super().send(
            session_key,
            message,
            session_id=session_id,
            callbacks=callbacks,
            blocking=blocking,
            model_override=model_override,
        )


class TimelineSendSpyPool(SendSpyPool):
    """SendSpyPool that also appends ``pool.send`` to a shared event timeline."""

    def __init__(
        self,
        *args: object,
        events: list[str],
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._events = events

    async def send(
        self,
        session_key: str,
        message: str,
        *,
        session_id: str | None = None,
        callbacks: StreamCallbacks | None = None,
        blocking: bool = True,
        model_override: str | None = None,
    ) -> RunResult:
        """Append ``pool.send`` then delegate to ``SendSpyPool.send``."""
        self._events.append("pool.send")
        return await super().send(
            session_key,
            message,
            session_id=session_id,
            callbacks=callbacks,
            blocking=blocking,
            model_override=model_override,
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
        *,
        model_override: str | None = None,
    ) -> object:
        """Record get parameters and delegate to the parent pool."""
        self.get_calls.append(
            {
                "session_key": session_key,
                "session_id": session_id,
                "model_override": model_override,
            }
        )
        return await super().get(
            session_key,
            session_id=session_id,
            model_override=model_override,
        )


class CreateAgentTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records create_agent invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.create_agent_calls: list[dict[str, object]] = []

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = DEFAULT_AGENT_MODEL,
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
    memory_root: Path | None = None,
    user_skills_root: Path | None = None,
    thinking: ThinkingDisplay | None = None,
) -> RunStatus | None:
    """Invoke ``run_repl`` with the PRD-003 / PRD-018 keyword-only contract.

    ``thinking`` is forwarded only when set so callers that omit it stay on the
    default ``None`` path without an explicit keyword.
    """
    # WHY: omit the kwarg when unset — optional forward keeps older call sites
    # that never passed thinking= identical while still injecting fakes in
    # PRD-018 wiring tests.
    repl_kwargs: dict[str, object] = {
        "config": config,
        "facade": facade,
        "reader": line_reader(*lines),
        "writer": writer,
        "stream_writer": stream_writer,
        "auto_resume": auto_resume,
        "memory_root": memory_root,
        "user_skills_root": user_skills_root,
    }
    if thinking is not None:
        repl_kwargs["thinking"] = thinking
    return await run_repl(pool, session_key, store, **repl_kwargs)  # type: ignore[arg-type]
