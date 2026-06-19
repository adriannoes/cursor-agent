"""Unit tests for cron runtime: cloud persistence and pool override (PRD-010 FR-4)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

from cursor_agent.config.loader import load_config
from cursor_agent.cron.executor import create_cron_run_session, run_cron_job
from cursor_agent.cron.models import CronJob
from cursor_agent.errors import ConfigError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.cron.executor import CronRunStatus
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore


class ResumeTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records resume_agent runtime_mode."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.resume_calls: list[dict[str, object]] = []

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Record resume parameters and delegate to the parent fake."""
        self.resume_calls.append(
            {
                "agent_id": agent_id,
                "runtime_mode": runtime_mode,
            }
        )
        return await super().resume_agent(
            agent_id,
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )


@pytest.fixture
async def store(tmp_path: Path) -> SessionStore:
    """Initialized session store on a temp database."""
    session_store = SessionStore(tmp_path / "sessions.db")
    await session_store.initialize()
    return session_store


@pytest.fixture
def local_config(tmp_path: Path) -> object:
    """Gateway-style local runtime config for cron tests."""
    return load_config(config_path=tmp_path / "missing.yaml")


@pytest.fixture
def cloud_job() -> CronJob:
    """Cron job configured for cloud runtime."""
    return CronJob.model_validate(
        {
            "id": "cloud-batch",
            "schedule": "0 9 * * *",
            "prompt": "Run cloud batch work.",
            "runtime": "cloud",
        }
    )


@pytest.mark.asyncio
async def test_cloud_job_persists_cloud_runtime_on_session_row(
    cloud_job: CronJob,
    store: SessionStore,
    local_config: object,
) -> None:
    """runtime: cloud jobs store cloud on the dedicated per-run session row."""
    facade = FakeSdkFacade()
    run_id = uuid.uuid4().hex

    row = await create_cron_run_session(
        cloud_job,
        store=store,
        facade=facade,
        config=local_config,  # type: ignore[arg-type]
        run_id=run_id,
    )

    assert row.runtime == "cloud"


@pytest.mark.asyncio
async def test_run_cloud_cron_job_uses_cloud_runtime_on_sdk_resume(
    cloud_job: CronJob,
    store: SessionStore,
    local_config: object,
) -> None:
    """Cron executor passes cloud runtime through pool.send despite local config."""
    facade = ResumeTrackingFacade(default_reply="cloud result")
    pool = SessionAgentPool(store=store, facade=facade, config=local_config)  # type: ignore[arg-type]

    outcome = await run_cron_job(
        cloud_job,
        pool=pool,
        store=store,
        facade=facade,
        config=local_config,  # type: ignore[arg-type]
    )

    assert outcome.status == CronRunStatus.FINISHED
    assert len(facade.resume_calls) == 1
    assert facade.resume_calls[0]["runtime_mode"] == "cloud"


@pytest.mark.asyncio
async def test_local_cli_cannot_resume_cloud_cron_session(
    cloud_job: CronJob,
    store: SessionStore,
    local_config: object,
) -> None:
    """Local CLI pool.get() still blocks cross-runtime resume for cron cloud rows."""
    facade = FakeSdkFacade()
    run_id = uuid.uuid4().hex
    row = await create_cron_run_session(
        cloud_job,
        store=store,
        facade=facade,
        config=local_config,  # type: ignore[arg-type]
        run_id=run_id,
    )
    pool = SessionAgentPool(store=store, facade=facade, config=local_config)  # type: ignore[arg-type]

    with pytest.raises(ConfigError, match="/new"):
        await pool.get(row.session_key, session_id=row.id)


@pytest.mark.asyncio
async def test_run_cron_job_reports_busy_without_deadlock(
    cloud_job: CronJob,
    store: SessionStore,
    local_config: object,
) -> None:
    """AgentBusy on the cron session returns a busy outcome instead of hanging."""
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release, default_reply="late reply")
    pool = SessionAgentPool(store=store, facade=facade, config=local_config)  # type: ignore[arg-type]
    run_id = uuid.uuid4().hex
    row = await create_cron_run_session(
        cloud_job,
        store=store,
        facade=facade,
        config=local_config,  # type: ignore[arg-type]
        run_id=run_id,
    )

    first_send = asyncio.create_task(
        pool.send(
            row.session_key,
            "hold lock",
            session_row=row,
            skip_runtime_guard=True,
        )
    )
    await facade.send_in_progress.wait()

    outcome = await run_cron_job(
        cloud_job,
        pool=pool,
        store=store,
        facade=facade,
        config=local_config,  # type: ignore[arg-type]
        run_id=run_id,
        blocking=False,
    )

    send_release.set()
    await first_send

    assert outcome.status.value == "busy"
    assert outcome.error_message is not None
    assert cloud_job.prompt not in (outcome.error_message or "")
    assert "late reply" not in (outcome.error_message or "")
