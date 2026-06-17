"""Unit tests for CLI resume-after-restart persistence (PRD-003 US-4).

Simulates a CLI process restart by using two distinct ``SessionAgentPool``
instances over the same ``SessionStore`` database and the same ``FakeSdkFacade``
instance. The fake facade represents server-side/SDK agent persistence that
survives process death; each pool's in-memory ``_resumed_agent_ids`` cache is
what resets when the CLI process restarts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config.loader import load_config
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunStatus
from cursor_agent.sessions.models import SessionCreateParams, build_cli_session_key
from cursor_agent.sessions.store import SessionStore


@pytest.mark.asyncio
async def test_resume_after_restart_reuses_persisted_agent_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh pool over same store resumes the persisted agent_id after restart."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()

    config = load_config(config_path=tmp_path / "missing.yaml")
    facade = FakeSdkFacade()
    session_key = build_cli_session_key(config.runtime.local.cwd)
    workspace = config.runtime.local.cwd

    # Process A: /new-like flow
    pool_a = SessionAgentPool(store=store, facade=facade, config=config)
    agent_id = await facade.create_agent(
        workspace=workspace,
        model=config.model,
        tool_profile=config.tool_profile,
        runtime_mode=config.runtime.mode,
    )
    row = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=config.runtime.mode,
            tool_profile=config.tool_profile,
            title=None,
        )
    )
    await pool_a.send(session_key, "hello", session_id=row.id)

    # Process B (restart): new pool, same store and facade
    pool_b = SessionAgentPool(store=store, facade=facade, config=config)
    resume_calls: list[str] = []
    original_resume = facade.resume_agent

    async def spy_resume_agent(
        agent_id_arg: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
    ) -> str:
        resume_calls.append(agent_id_arg)
        return await original_resume(
            agent_id_arg,
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
        )

    monkeypatch.setattr(facade, "resume_agent", spy_resume_agent)

    resumed = await pool_b.get(session_key)

    assert resumed.agent_id == agent_id
    assert resume_calls == [agent_id]

    result = await pool_b.send(session_key, "again", session_id=resumed.id)
    assert result.status == RunStatus.FINISHED
