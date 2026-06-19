"""Unit tests for cron job agent isolation (PRD-010 FR-3)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.cron.executor import (
    build_cron_session_key,
    create_cron_run_session,
    run_cron_job,
)
from cursor_agent.cron.models import CRON_PROMPT_MAX_BYTES, CronJob
from cursor_agent.facade_logging import LogContext
from cursor_agent.memory import (
    MEMORY_SECTION_MARKER,
    TOTAL_MEMORY_BUDGET_BYTES,
    USER_MEMORY_BUDGET_BYTES,
    USER_MEMORY_SECTION_MARKER,
    LocalMemoryStore,
    format_memory_injection_message,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, StreamCallbacks
from cursor_agent.sessions.models import SessionCreateParams, build_cli_session_key
from cursor_agent.sessions.store import SessionStore

_USER_FILENAME = "USER.md"
_MEMORY_FILENAME = "MEMORY.md"
_CRON_PROMPT_HEAD_MARKER = "CRON_PROMPT_HEAD"
_CRON_PROMPT_TAIL_MARKER = "CRON_PROMPT_TAIL"

_FORBIDDEN_CRON_BOUNDARY_TOKENS: tuple[str, ...] = (
    "skill_discovery",
    "CommandRouter",
    "skills.injection",
)


@pytest.fixture
def cron_job() -> CronJob:
    """Minimal validated cron job for executor tests."""
    return CronJob.model_validate(
        {
            "id": "daily-report",
            "schedule": "0 9 * * *",
            "prompt": "Summarize open tasks.",
        }
    )


@pytest.fixture
async def store(tmp_path: Path) -> SessionStore:
    """Initialized session store on a temp database."""
    session_store = SessionStore(tmp_path / "sessions.db")
    await session_store.initialize()
    return session_store


@pytest.fixture
def config(tmp_path: Path) -> CursorAgentConfig:
    """Local runtime config rooted at tmp_path."""
    return load_config(config_path=tmp_path / "missing.yaml")


def _write_exact_bytes(path: Path, byte_count: int, *, fill: str) -> None:
    """Write exactly ``byte_count`` UTF-8 bytes using a single-byte fill character."""
    if len(fill.encode("utf-8")) != 1:
        raise ValueError(
            f"fill must be a single UTF-8 byte character, received {fill!r}"
        )
    path.write_text(fill * byte_count, encoding="utf-8")


def _write_full_memory_budget(memory_root: Path) -> None:
    """Populate USER.md and MEMORY.md to consume the full 8 KB memory budget."""
    memory_root.mkdir(parents=True, exist_ok=True)
    _write_exact_bytes(
        memory_root / _USER_FILENAME,
        USER_MEMORY_BUDGET_BYTES,
        fill="u",
    )
    _write_exact_bytes(
        memory_root / _MEMORY_FILENAME,
        TOTAL_MEMORY_BUDGET_BYTES - USER_MEMORY_BUDGET_BYTES,
        fill="m",
    )


def _near_max_cron_job_prompt() -> str:
    """Build a cron job prompt that fills the 64 KiB MVP cap with edge markers."""
    head = _CRON_PROMPT_HEAD_MARKER
    tail = _CRON_PROMPT_TAIL_MARKER
    filler_bytes = (
        CRON_PROMPT_MAX_BYTES - len(head.encode("utf-8")) - len(tail.encode("utf-8"))
    )
    if filler_bytes < 0:
        raise ValueError("cron prompt markers exceed CRON_PROMPT_MAX_BYTES")
    return head + ("j" * filler_bytes) + tail


class SendCapturingFacade(FakeSdkFacade):
    """FakeSdkFacade that records send keyword arguments."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.send_calls: list[dict[str, object]] = []

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Record send parameters and delegate to the parent fake."""
        self.send_calls.append(
            {
                "agent_id": agent_id,
                "message": message,
                "callbacks": callbacks,
                "log_context": log_context,
            }
        )
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,
        )


@pytest.mark.asyncio
async def test_run_cron_job_creates_unique_session_key_per_run(
    cron_job: CronJob,
    store: SessionStore,
    config: object,
    tmp_path: Path,
) -> None:
    """Each cron execution uses cron:{job_id}:{run_id} with a unique run_id."""
    facade = FakeSdkFacade(default_reply="cron done")
    pool = SessionAgentPool(store=store, facade=facade, config=config)  # type: ignore[arg-type]
    run_id_a = uuid.uuid4().hex
    run_id_b = uuid.uuid4().hex

    outcome_a = await run_cron_job(
        cron_job,
        pool=pool,
        store=store,
        facade=facade,
        config=config,  # type: ignore[arg-type]
        run_id=run_id_a,
    )
    outcome_b = await run_cron_job(
        cron_job,
        pool=pool,
        store=store,
        facade=facade,
        config=config,  # type: ignore[arg-type]
        run_id=run_id_b,
    )

    assert outcome_a.session_key == build_cron_session_key(cron_job.id, run_id_a)
    assert outcome_b.session_key == build_cron_session_key(cron_job.id, run_id_b)
    assert outcome_a.session_key != outcome_b.session_key
    assert outcome_a.run_id == run_id_a
    assert outcome_b.run_id == run_id_b


@pytest.mark.asyncio
async def test_run_cron_job_session_key_distinct_from_chat_keys(
    cron_job: CronJob,
    store: SessionStore,
    config: object,
    tmp_path: Path,
) -> None:
    """Cron session keys never reuse Telegram or CLI session_key patterns."""
    facade = FakeSdkFacade(default_reply="cron done")
    pool = SessionAgentPool(store=store, facade=facade, config=config)  # type: ignore[arg-type]
    run_id = uuid.uuid4().hex
    telegram_key = "telegram:123456789:busytest"
    cli_key = build_cli_session_key(tmp_path)

    outcome = await run_cron_job(
        cron_job,
        pool=pool,
        store=store,
        facade=facade,
        config=config,  # type: ignore[arg-type]
        run_id=run_id,
    )

    assert outcome.session_key.startswith(f"cron:{cron_job.id}:")
    assert outcome.session_key != telegram_key
    assert outcome.session_key != cli_key
    assert not outcome.session_key.startswith("telegram:")
    assert not outcome.session_key.startswith("cli:")


@pytest.mark.asyncio
async def test_create_cron_run_session_persists_isolation_metadata(
    cron_job: CronJob,
    store: SessionStore,
    config: object,
) -> None:
    """Fresh cron rows store cron_job_id, cron_run_id, and memory_injected=false."""
    facade = FakeSdkFacade()
    run_id = uuid.uuid4().hex

    row = await create_cron_run_session(
        cron_job,
        store=store,
        facade=facade,
        config=config,  # type: ignore[arg-type]
        run_id=run_id,
    )

    assert row.session_key == build_cron_session_key(cron_job.id, run_id)
    assert row.metadata.get("cron_job_id") == cron_job.id
    assert row.metadata.get("cron_run_id") == run_id
    assert row.metadata.get("memory_injected") is False


@pytest.mark.asyncio
async def test_run_cron_job_completes_with_finished_status(
    cron_job: CronJob,
    store: SessionStore,
    config: object,
) -> None:
    """Successful cron execution returns structured finished outcome."""
    facade = FakeSdkFacade(default_reply="batch complete")
    pool = SessionAgentPool(store=store, facade=facade, config=config)  # type: ignore[arg-type]

    outcome = await run_cron_job(
        cron_job,
        pool=pool,
        store=store,
        facade=facade,
        config=config,  # type: ignore[arg-type]
    )

    assert outcome.status.value == "finished"
    assert outcome.result_text == "batch complete"
    assert outcome.error_message is None


@pytest.mark.asyncio
async def test_combined_prompt_budget_cron_first_send_injects_memory_before_job_prompt(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Cron first send keeps full 8 KB memory before a near-max job prompt."""
    memory_root = tmp_path / "memory"
    _write_full_memory_budget(memory_root)
    memory_store = LocalMemoryStore(root=memory_root)
    payload = memory_store.build_effective_payload()
    assert payload.total_effective_bytes == TOTAL_MEMORY_BUDGET_BYTES

    job_prompt = _near_max_cron_job_prompt()
    assert len(job_prompt.encode("utf-8")) == CRON_PROMPT_MAX_BYTES
    cron_job = CronJob.model_validate(
        {
            "id": "budget-report",
            "schedule": "0 9 * * *",
            "prompt": job_prompt,
        }
    )

    facade = SendCapturingFacade(default_reply="cron budget ok")
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=memory_store,
    )

    outcome = await run_cron_job(
        cron_job,
        pool=pool,
        store=store,
        facade=facade,
        config=config,
    )

    assert outcome.status.value == "finished"
    assert len(facade.send_calls) == 1
    sent_message = facade.send_calls[0]["message"]
    expected = format_memory_injection_message(payload, job_prompt)
    assert sent_message == expected
    assert sent_message.index(USER_MEMORY_SECTION_MARKER) < sent_message.index(
        MEMORY_SECTION_MARKER
    )
    assert sent_message.index(MEMORY_SECTION_MARKER) < sent_message.index(
        _CRON_PROMPT_HEAD_MARKER
    )
    assert sent_message.endswith(_CRON_PROMPT_TAIL_MARKER)
    assert payload.user.effective_text in sent_message
    assert payload.memory.effective_text in sent_message
    assert sent_message != job_prompt

    row = await store.resolve(outcome.session_key, session_id=outcome.session_id)
    assert row is not None
    assert row.metadata.get("memory_injected") is True


class CancelRecordingFacade(FakeSdkFacade):
    """FakeSdkFacade that records which agent ids were cancelled."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.cancelled_agents: list[str] = []

    async def cancel(self, agent_id: str) -> None:
        """Record the cancelled agent id and delegate to the parent fake."""
        self.cancelled_agents.append(agent_id)
        await super().cancel(agent_id)


class _SessionCreateFailingStore(SessionStore):
    """SessionStore whose ``create`` always fails to simulate a persist error."""

    async def create(self, params: object) -> object:  # type: ignore[override]
        raise RuntimeError("simulated session store failure")


@pytest.mark.asyncio
async def test_create_cron_run_session_cancels_agent_when_store_create_fails(
    cron_job: CronJob,
    config: object,
    tmp_path: Path,
) -> None:
    """A persist failure after create_agent must cancel the orphaned SDK agent."""
    failing_store = _SessionCreateFailingStore(tmp_path / "sessions.db")
    await failing_store.initialize()
    facade = CancelRecordingFacade()

    with pytest.raises(RuntimeError, match="simulated session store failure"):
        await create_cron_run_session(
            cron_job,
            store=failing_store,
            facade=facade,
            config=config,  # type: ignore[arg-type]
            run_id="run-leak",
        )

    assert len(facade.cancelled_agents) == 1


@pytest.mark.asyncio
async def test_run_cron_job_returns_error_when_session_setup_fails(
    cron_job: CronJob,
    config: object,
    tmp_path: Path,
) -> None:
    """run_cron_job reports ERROR (not raise) and cancels the agent on setup failure."""
    failing_store = _SessionCreateFailingStore(tmp_path / "sessions.db")
    await failing_store.initialize()
    facade = CancelRecordingFacade()
    pool = SessionAgentPool(store=failing_store, facade=facade, config=config)  # type: ignore[arg-type]

    outcome = await run_cron_job(
        cron_job,
        pool=pool,
        store=failing_store,
        facade=facade,
        config=config,  # type: ignore[arg-type]
        run_id="run-error",
    )

    assert outcome.status is outcome.status.ERROR
    assert outcome.session_key == build_cron_session_key(cron_job.id, "run-error")
    assert outcome.session_id == ""
    assert len(facade.cancelled_agents) == 1


async def _create_cron_session_row(
    store: SessionStore,
    *,
    job_id: str,
    run_id: str,
    agent_id: str,
    workspace: Path,
) -> None:
    """Persist one cron session row for pruning specificity tests."""
    await store.create(
        SessionCreateParams(
            session_key=build_cron_session_key(job_id, run_id),
            agent_id=agent_id,
            workspace=str(workspace.resolve()),
            runtime="local",
            tool_profile="coding",
        )
    )


@pytest.mark.asyncio
async def test_prune_cron_sessions_only_affects_exact_job_id_prefix(
    store: SessionStore,
    tmp_path: Path,
) -> None:
    """Pruning one job must not delete sessions for colliding cron job ids."""
    collision_specs: tuple[tuple[str, str, str], ...] = (
        ("daily", "run-daily", "agent-daily"),
        ("daily_%", "run-daily-pct", "agent-daily-pct"),
        ("daily:report", "run-daily-report", "agent-daily-report"),
    )
    for job_id, run_id, agent_id in collision_specs:
        await _create_cron_session_row(
            store,
            job_id=job_id,
            run_id=run_id,
            agent_id=agent_id,
            workspace=tmp_path,
        )

    pruned_agent_ids = await store.prune_cron_sessions("daily", keep_last=0)

    assert pruned_agent_ids == ["agent-daily"]
    for job_id, run_id, expected_agent_id in collision_specs[1:]:
        row = await store.resolve(build_cron_session_key(job_id, run_id))
        assert row is not None, (
            f"expected surviving session for job_id={job_id!r}, "
            f"run_id={run_id!r} after pruning daily"
        )
        assert row.agent_id == expected_agent_id


@pytest.mark.asyncio
async def test_prune_cron_sessions_returns_pruned_agent_ids_for_cancellation(
    store: SessionStore,
    tmp_path: Path,
) -> None:
    """Pruned rows must return agent_id values for SDK cancellation."""
    await _create_cron_session_row(
        store,
        job_id="daily",
        run_id="run-old",
        agent_id="agent-old",
        workspace=tmp_path,
    )
    await _create_cron_session_row(
        store,
        job_id="daily",
        run_id="run-new",
        agent_id="agent-new",
        workspace=tmp_path,
    )

    pruned_agent_ids = await store.prune_cron_sessions("daily", keep_last=1)

    assert pruned_agent_ids == ["agent-old"]
    surviving = await store.resolve(build_cron_session_key("daily", "run-new"))
    assert surviving is not None
    assert surviving.agent_id == "agent-new"


@pytest.mark.asyncio
async def test_run_cron_job_prunes_old_sessions_beyond_retention(
    cron_job: CronJob,
    store: SessionStore,
    config: object,
) -> None:
    """Repeated runs keep at most ``keep_sessions`` cron rows for the job."""
    facade = CancelRecordingFacade(default_reply="done")
    pool = SessionAgentPool(store=store, facade=facade, config=config)  # type: ignore[arg-type]

    for index in range(5):
        await run_cron_job(
            cron_job,
            pool=pool,
            store=store,
            facade=facade,
            config=config,  # type: ignore[arg-type]
            run_id=f"run-{index}",
            keep_sessions=2,
        )

    # Three oldest per-run agents were cancelled during pruning across the runs.
    assert len(facade.cancelled_agents) == 3
    # Exactly the two most recent rows survived (keep_sessions=2).
    remaining = await store.prune_cron_sessions(cron_job.id, keep_last=0)
    assert len(remaining) == 2


@pytest.mark.parametrize(
    ("relative_path",),
    [
        ("src/cursor_agent/cron/executor.py",),
        ("src/cursor_agent/cron/scheduler.py",),
    ],
)
def test_cron_execution_boundary_has_no_skill_router(relative_path: str) -> None:
    """Cron execution path must not reference CLI skill discovery or router."""
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / relative_path).read_text(encoding="utf-8")
    for token in _FORBIDDEN_CRON_BOUNDARY_TOKENS:
        assert token not in source, (
            f"forbidden token {token!r} found in {relative_path}; "
            "cron must use job prompt only (PRD-009 boundary)"
        )
