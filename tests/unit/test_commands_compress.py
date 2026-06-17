"""Unit tests for /compress saga (PRD-004 FR-6, FR-7 / ADR-011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.cli.compress import load_compress_prompt, run_compress_session
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import ConfigError
from cursor_agent.sdk_facade import (
    FakeSdkFacade,
    RunResult,
    StreamCallbacks,
)
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import seed_session

_SUMMARY_REPLY = """\
## Goal
Ship /compress saga with rollback.

## Decisions made
- Use FakeSdkFacade in unit tests.

## Current state
SessionStore.update_agent_id exists.

## Open questions
None.

## Next steps
1. Wire handler in slash_commands.
"""


def test_load_compress_prompt_reads_versioned_file() -> None:
    """load_compress_prompt returns the repo prompt with expected section headings."""
    prompt = load_compress_prompt()
    assert "## Goal" in prompt
    assert "## Decisions made" in prompt
    assert "## Current state" in prompt
    assert "## Open questions" in prompt
    assert "## Next steps" in prompt
    assert "injected as the first message" in prompt


def test_load_compress_prompt_reads_packaged_file() -> None:
    """load_compress_prompt resolves the wheel-shipped prompt under cursor_agent."""
    from importlib import resources

    packaged = resources.files("cursor_agent").joinpath("prompts/compress.txt")
    assert packaged.is_file()
    assert load_compress_prompt() == packaged.read_text(encoding="utf-8")


async def test_compress_session_requires_active_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """run_compress_session rejects missing session rows."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:test"

    with pytest.raises(ConfigError, match="session not found"):
        await run_compress_session(
            store=store,
            facade=facade,
            config=config,
            session_key=session_key,
            session_id="00000000-0000-0000-0000-000000000099",
        )


class _CompressSendSpyFacade(FakeSdkFacade):
    """FakeSdkFacade that records sends and can fail on the summary delivery step."""

    def __init__(
        self,
        *,
        fail_on_summary_delivery: bool = False,
        store: SessionStore | None = None,
        session_key: str | None = None,
        session_id: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.fail_on_summary_delivery = fail_on_summary_delivery
        self._status_store = store
        self._status_session_key = session_key
        self._status_session_id = session_id
        self.send_calls: list[dict[str, str]] = []
        self.create_agent_calls: list[dict[str, object]] = []
        self._summary_generated = False

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Record create_agent and delegate to the parent fake."""
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

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Record sends; optionally fail when delivering the summary to the new agent."""
        if (
            not self._summary_generated
            and self._status_store is not None
            and self._status_session_key is not None
            and self._status_session_id is not None
        ):
            row = await self._status_store.resolve(
                self._status_session_key,
                session_id=self._status_session_id,
            )
            assert row is not None
            assert row.metadata.get("status") == "compressing"
        self.send_calls.append({"agent_id": agent_id, "message": message})
        if self.fail_on_summary_delivery and self._summary_generated:
            msg = (
                "simulated summary delivery failure: "
                f"agent_id={agent_id!r}, expected successful second send"
            )
            raise RuntimeError(msg)
        result = await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,  # type: ignore[arg-type]
        )
        if not self._summary_generated:
            self._summary_generated = True
        return result

    def messages_for(self, agent_id: str) -> list[dict[str, str]]:
        """Return recorded user/assistant messages for an agent."""
        return list(self._messages_by_agent.get(agent_id, []))


async def test_compress_session_happy_path_updates_same_row(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Successful /compress sets compressing status, swaps agent_id, and seeds summary."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-happy"
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    facade._status_session_id = session_id
    row_before = await store.resolve(session_key, session_id=session_id)
    assert row_before is not None
    previous_agent_id = row_before.agent_id
    compress_prompt = load_compress_prompt()

    result = await run_compress_session(
        store=store,
        facade=facade,
        config=config,
        session_key=session_key,
        session_id=session_id,
    )

    assert result.session_id == session_id
    assert result.previous_agent_id == previous_agent_id
    assert result.new_agent_id != previous_agent_id

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.id == session_id
    assert row_after.agent_id == result.new_agent_id
    assert "status" not in row_after.metadata

    assert len(facade.create_agent_calls) == 2
    assert facade.send_calls[0]["agent_id"] == previous_agent_id
    assert facade.send_calls[0]["message"] == compress_prompt
    assert facade.send_calls[1]["agent_id"] == result.new_agent_id
    assert facade.send_calls[1]["message"] == _SUMMARY_REPLY

    new_agent_messages = facade.messages_for(result.new_agent_id)
    assert new_agent_messages[0]["role"] == "user"
    assert new_agent_messages[0]["content"] == _SUMMARY_REPLY


async def test_compress_session_rollback_on_summary_delivery_failure(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Mid-flight failure restores previous agent_id and clears compressing status."""
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        fail_on_summary_delivery=True,
    )
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-rollback"
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    row_before = await store.resolve(session_key, session_id=session_id)
    assert row_before is not None
    previous_agent_id = row_before.agent_id

    with pytest.raises(ConfigError, match="summary delivery"):
        await run_compress_session(
            store=store,
            facade=facade,
            config=config,
            session_key=session_key,
            session_id=session_id,
        )

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.id == session_id
    assert row_after.agent_id == previous_agent_id
    assert "status" not in row_after.metadata

    assert len(facade.create_agent_calls) == 2
    assert len(facade.send_calls) == 2
