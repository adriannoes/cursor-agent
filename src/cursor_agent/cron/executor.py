"""Cron job execution with isolated per-run session rows (PRD-010, FR-3, FR-4)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.cron.models import CronJob
from cursor_agent.errors import AgentBusyError, CursorAgentError
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import RunResult, RunStatus, SdkFacade
from cursor_agent.sessions.models import SessionCreateParams, SessionRecord
from cursor_agent.sessions.store import SessionStore

_MODULE_LOGGER = logging.getLogger(__name__)

_CRON_SESSION_PREFIX = "cron:"

# Per-job cron session rows are never resumed; keep a bounded history per job so
# the sessions table does not grow without limit (PRD-010 FR-3).
CRON_SESSION_RETENTION_PER_JOB = 20


class CronRunStatus(str, Enum):
    """Terminal status for a cron job execution attempt."""

    FINISHED = "finished"
    BUSY = "busy"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CronJobRunOutcome:
    """Structured result of ``run_cron_job`` for delivery and logging layers."""

    job_id: str
    run_id: str
    session_id: str
    session_key: str
    status: CronRunStatus
    result_text: str | None = None
    error_message: str | None = None


def build_cron_session_key(job_id: str, run_id: str) -> str:
    """Build per-run cron session key as ``cron:{job_id}:{run_id}``.

    Args:
        job_id: Validated cron job identifier from ``jobs.yaml``.
        run_id: Unique execution identifier for this scheduled fire.

    Returns:
        Session key that never overlaps CLI or Telegram chat keys.
    """
    if not job_id:
        raise ValueError(
            f"invalid job_id: received {job_id!r}, expected non-empty string"
        )
    if not run_id:
        raise ValueError(
            f"invalid run_id: received {run_id!r}, expected non-empty string"
        )
    return f"{_CRON_SESSION_PREFIX}{job_id}:{run_id}"


def build_cron_session_metadata(job_id: str, run_id: str) -> dict[str, object]:
    """Return fresh cron isolation metadata for a new session row."""
    return {
        "cron_job_id": job_id,
        "cron_run_id": run_id,
        "memory_injected": False,
    }


async def _cancel_agent_quietly(facade: SdkFacade, agent_id: str) -> None:
    """Best-effort cancel of an SDK agent; never raises to the caller."""
    try:
        await facade.cancel(agent_id)
    except Exception:
        _MODULE_LOGGER.warning(
            "cron cleanup: failed to cancel orphaned agent_id=%s",
            agent_id,
            exc_info=True,
        )


async def create_cron_run_session(
    job: CronJob,
    *,
    store: SessionStore,
    facade: SdkFacade,
    config: CursorAgentConfig,
    run_id: str | None = None,
) -> SessionRecord:
    """Create a dedicated SDK agent and session row for one cron execution.

    If persisting the session row fails after the SDK agent is created, the
    agent is cancelled before re-raising so it does not leak without a backing
    session record.
    """
    effective_run_id = run_id if run_id is not None else uuid.uuid4().hex
    session_key = build_cron_session_key(job.id, effective_run_id)
    workspace = str(Path(config.runtime.local.cwd).resolve())
    agent_id = await facade.create_agent(
        workspace=workspace,
        model=config.model,
        tool_profile=config.tool_profile,
        runtime_mode=job.runtime,
    )
    try:
        return await store.create(
            SessionCreateParams(
                session_key=session_key,
                agent_id=agent_id,
                workspace=workspace,
                runtime=job.runtime,
                tool_profile=config.tool_profile,
                title=None,
                metadata=build_cron_session_metadata(job.id, effective_run_id),
            )
        )
    except Exception:
        await _cancel_agent_quietly(facade, agent_id)
        raise


def _map_run_status(result: RunResult) -> CronRunStatus:
    """Map facade run status onto cron run outcome status."""
    if result.status == RunStatus.FINISHED:
        return CronRunStatus.FINISHED
    return CronRunStatus.ERROR


async def run_cron_job(
    job: CronJob,
    *,
    pool: SessionAgentPool,
    store: SessionStore,
    facade: SdkFacade,
    config: CursorAgentConfig,
    run_id: str | None = None,
    blocking: bool = True,
    keep_sessions: int = CRON_SESSION_RETENTION_PER_JOB,
) -> CronJobRunOutcome:
    """Execute a cron job through the shared pool with an isolated session row.

    Creates ``cron:{job_id}:{run_id}``, sends the job prompt via
    ``SessionAgentPool.send()``, and returns a channel-neutral outcome for the
    delivery layer. Prompt bodies and assistant output are never logged here.

    After the run, cron session rows for the job beyond the most recent
    ``keep_sessions`` are pruned and their SDK agents cancelled, bounding
    accumulation. If the run task is cancelled (ADR-021 gateway shutdown drain
    timeout), the per-run SDK agent is cancelled before the cancellation
    propagates so it does not keep running after the gateway stops.
    """
    effective_run_id = run_id if run_id is not None else uuid.uuid4().hex
    try:
        row = await create_cron_run_session(
            job,
            store=store,
            facade=facade,
            config=config,
            run_id=effective_run_id,
        )
    except Exception as exc:
        _MODULE_LOGGER.warning(
            "cron job setup failed: job_id=%s run_id=%s exception_class=%s",
            job.id,
            effective_run_id,
            exc.__class__.__name__,
        )
        return CronJobRunOutcome(
            job_id=job.id,
            run_id=effective_run_id,
            session_id="",
            session_key=build_cron_session_key(job.id, effective_run_id),
            status=CronRunStatus.ERROR,
            error_message=str(exc),
        )
    try:
        outcome = await _send_cron_prompt(
            job,
            row=row,
            pool=pool,
            blocking=blocking,
            run_id=effective_run_id,
        )
    except asyncio.CancelledError:
        await _cancel_agent_quietly(facade, row.agent_id)
        raise
    await _prune_cron_sessions(store, facade, job.id, keep_last=keep_sessions)
    return outcome


async def _prune_cron_sessions(
    store: SessionStore,
    facade: SdkFacade,
    job_id: str,
    *,
    keep_last: int,
) -> None:
    """Prune stale cron session rows for a job and cancel their SDK agents."""
    try:
        pruned_agent_ids = await store.prune_cron_sessions(job_id, keep_last=keep_last)
    except Exception:
        _MODULE_LOGGER.warning(
            "cron session prune failed: job_id=%s", job_id, exc_info=True
        )
        return
    for agent_id in pruned_agent_ids:
        await _cancel_agent_quietly(facade, agent_id)


async def _send_cron_prompt(
    job: CronJob,
    *,
    row: SessionRecord,
    pool: SessionAgentPool,
    blocking: bool,
    run_id: str,
) -> CronJobRunOutcome:
    """Send the job prompt through the pool and map the result to an outcome."""
    session_key = row.session_key
    effective_run_id = run_id
    try:
        # Per-run cron sessions use the job runtime; skip pool resume guard (PRD-010 FR-4).
        result = await pool.send(
            session_key,
            job.prompt,
            session_row=row,
            blocking=blocking,
            skip_runtime_guard=True,
        )
    except AgentBusyError as exc:
        _MODULE_LOGGER.info(
            "cron job busy: job_id=%s run_id=%s exception_class=%s",
            job.id,
            effective_run_id,
            exc.__class__.__name__,
        )
        return CronJobRunOutcome(
            job_id=job.id,
            run_id=effective_run_id,
            session_id=row.id,
            session_key=session_key,
            status=CronRunStatus.BUSY,
            error_message=str(exc),
        )
    except CursorAgentError as exc:
        _MODULE_LOGGER.warning(
            "cron job failed: job_id=%s run_id=%s exception_class=%s",
            job.id,
            effective_run_id,
            exc.__class__.__name__,
        )
        return CronJobRunOutcome(
            job_id=job.id,
            run_id=effective_run_id,
            session_id=row.id,
            session_key=session_key,
            status=CronRunStatus.ERROR,
            error_message=str(exc),
        )

    return CronJobRunOutcome(
        job_id=job.id,
        run_id=effective_run_id,
        session_id=row.id,
        session_key=session_key,
        status=_map_run_status(result),
        result_text=result.text,
    )
