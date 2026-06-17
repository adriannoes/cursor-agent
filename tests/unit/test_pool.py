"""Unit tests for SessionAgentPool (PRD-002 FR-6–FR-8)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cursor_agent.config import CursorAgentConfig, load_config
from cursor_agent.errors import AgentBusyError, AuthError, ConfigError, CursorAgentError
from cursor_agent.facade_logging import LogContext
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, RunStatus, StreamCallbacks
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


@pytest.fixture
def config() -> CursorAgentConfig:
    """Default local runtime config for pool tests."""
    return load_config(config_path=Path("/nonexistent/config.yaml"))


@pytest.fixture
async def store(tmp_path: Path) -> SessionStore:
    """Initialized session store on a temp database."""
    session_store = SessionStore(tmp_path / "sessions.db")
    await session_store.initialize()
    return session_store


async def _seed_session(
    session_store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    runtime: str = "local",
    title: str | None = None,
    workspace: str = "/tmp/workspace",
    tool_profile: str = "coding",
) -> str:
    """Create a facade agent and persist a matching session row."""
    agent_id = await facade.create_agent(workspace=workspace)
    record = await session_store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=runtime,
            title=title,
            tool_profile=tool_profile,
        )
    )
    return record.id


def _config_with_tool_profile(tool_profile: str) -> CursorAgentConfig:
    """Return default config with an explicit tool_profile override."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    return config.model_copy(update={"tool_profile": tool_profile})


class ResumeTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records resume_agent invocations."""

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
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
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


class RaisingSendFacade(FakeSdkFacade):
    """FakeSdkFacade that raises a configured error on the first send only."""

    def __init__(
        self,
        error: CursorAgentError,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._error = error
        self._should_raise = True

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Raise the configured error once, then delegate to the parent fake."""
        if self._should_raise:
            self._should_raise = False
            raise self._error
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,
        )


class ErrorStatusSendFacade(FakeSdkFacade):
    """FakeSdkFacade that returns ERROR once, then a normal finished run."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._return_error_once = True

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Return ERROR status once without raising, then delegate."""
        if self._return_error_once:
            self._return_error_once = False
            return RunResult(
                run_id="error-run-1",
                status=RunStatus.ERROR,
                text=None,
            )
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,
        )


class ForbiddenResumeFacade(FakeSdkFacade):
    """FakeSdkFacade that fails if resume_agent is called."""

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Raise to prove resume was attempted."""
        msg = (
            f"resume should not run: agent_id={agent_id!r}, workspace={workspace!r}, "
            f"model={model!r}, tool_profile={tool_profile!r}, "
            f"runtime_mode={runtime_mode!r}"
        )
        raise AssertionError(msg)


# --- Task 4.1: lazy resume ---


@pytest.mark.asyncio
async def test_lazy_resume_get_calls_resume_agent(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """get() resolves the session and lazily resumes via facade.resume_agent."""
    session_key = "cli:default:abc12345"
    facade = ResumeTrackingFacade()
    session_id = await _seed_session(store, facade, session_key, workspace="/tmp/ws")

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    row = await pool.get(session_key)

    assert row.id == session_id
    assert len(facade.resume_calls) == 1
    call = facade.resume_calls[0]
    assert call["workspace"] == "/tmp/ws"
    assert call["model"] == config.model
    assert call["tool_profile"] == "coding"


@pytest.mark.asyncio
async def test_lazy_resume_get_is_idempotent_per_agent_and_model(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """Repeated get() for the same agent_id and model resumes only once."""
    session_key = "cli:default:abc12345"
    facade = ResumeTrackingFacade()
    await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)
    await pool.get(session_key)

    assert len(facade.resume_calls) == 1


@pytest.mark.asyncio
async def test_get_re_resumes_when_model_override_changes(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """get() resumes again when the effective model override changes."""
    session_key = "cli:default:modelchg1"
    facade = ResumeTrackingFacade()
    await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)
    await pool.get(session_key, model_override="composer-2.5-fast")

    assert len(facade.resume_calls) == 2
    assert facade.resume_calls[1]["model"] == "composer-2.5-fast"


@pytest.mark.asyncio
async def test_send_uses_model_override_on_resume(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """send() resumes with model_override instead of config.model."""
    session_key = "cli:default:modelsend1"
    facade = ResumeTrackingFacade()
    await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.send(session_key, "hello", model_override="composer-2.5-fast")

    assert len(facade.resume_calls) == 1
    assert facade.resume_calls[0]["model"] == "composer-2.5-fast"


# --- Task 4.3: runtime guard ---


@pytest.mark.asyncio
async def test_runtime_guard_get_raises_config_error_before_resume(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """Runtime mismatch on get() raises ConfigError and never calls resume_agent."""
    session_key = "cli:default:cloudkey1"
    facade = ForbiddenResumeFacade()
    await _seed_session(store, facade, session_key, runtime="cloud")

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    with pytest.raises(ConfigError) as exc_info:
        await pool.get(session_key)

    message = str(exc_info.value)
    assert "cloud" in message
    assert "local" in message
    assert "/new" in message


@pytest.mark.asyncio
async def test_runtime_guard_send_raises_config_error_before_lock(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """Runtime mismatch on send() raises ConfigError before acquiring the lock."""
    session_key = "cli:default:cloudkey2"
    send_release = asyncio.Event()
    send_release.set()
    facade = SendCapturingFacade(send_release=send_release)
    await _seed_session(store, facade, session_key, runtime="cloud")

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    with pytest.raises(ConfigError, match="/new"):
        await pool.send(session_key, "hello")

    assert facade.send_calls == []


# --- Task 4.5: locks CLI and gateway ---


@pytest.mark.asyncio
async def test_lock_cli_blocking_second_send_waits_for_first(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """CLI blocking send waits for an in-flight run instead of raising AgentBusyError."""
    session_key = "cli:default:lockcli1"
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release)
    await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    first_task = asyncio.create_task(pool.send(session_key, "first", blocking=True))
    await facade.send_in_progress.wait()

    second_task = asyncio.create_task(pool.send(session_key, "second", blocking=True))
    await asyncio.sleep(0)
    assert not second_task.done()

    send_release.set()
    await first_task
    await second_task


@pytest.mark.asyncio
async def test_lock_gateway_nonblocking_raises_agent_busy_error(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """Gateway non-blocking send raises AgentBusyError while the lock is held."""
    session_key = "cli:default:lockgw1"
    send_release = asyncio.Event()
    facade = FakeSdkFacade(send_release=send_release)
    await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    first_task = asyncio.create_task(pool.send(session_key, "first", blocking=True))
    await facade.send_in_progress.wait()

    with pytest.raises(AgentBusyError, match="session_key"):
        await pool.send(session_key, "second", blocking=False)

    send_release.set()
    await first_task


@pytest.mark.asyncio
async def test_send_rejects_whitespace_only_message_before_facade(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """Whitespace-only messages raise ConfigError before facade.send is called."""
    session_key = "cli:default:emptymsg"
    facade = SendCapturingFacade()
    await _seed_session(store, facade, session_key, title=None)

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    with pytest.raises(ConfigError, match="message"):
        await pool.send(session_key, "   \t\n  ")

    assert facade.send_calls == []


# --- Task 4.7: send wrapper and LogContext ---


@pytest.mark.asyncio
async def test_send_wrapper_builds_log_context_and_returns_result(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """send() passes LogContext to facade.send and returns the RunResult."""
    session_key = "cli:default:sendwrap1"
    facade = SendCapturingFacade()
    session_id = await _seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    result = await pool.send(session_key, "hello there")

    assert result.status == RunStatus.FINISHED
    assert len(facade.send_calls) == 1
    log_context = facade.send_calls[0]["log_context"]
    assert isinstance(log_context, LogContext)
    assert log_context.session_id == session_id
    assert log_context.session_key == session_key
    assert log_context.agent_id == facade.send_calls[0]["agent_id"]


@pytest.mark.asyncio
async def test_send_wrapper_sets_title_from_first_message(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """send() sets session title when the stored title is empty."""
    session_key = "cli:default:title1"
    facade = FakeSdkFacade()
    session_id = await _seed_session(store, facade, session_key, title=None)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.send(session_key, "  fix the failing test  ")

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.title == "fix the failing test"


@pytest.mark.asyncio
async def test_send_wrapper_persists_last_run_metadata(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """send() persists last_run_id and last_status in session metadata."""
    session_key = "cli:default:meta1"
    facade = FakeSdkFacade()
    session_id = await _seed_session(store, facade, session_key, title="existing")

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    result = await pool.send(session_key, "status please")

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata["last_run_id"] == result.run_id
    assert row.metadata["last_status"] == RunStatus.FINISHED.value


@pytest.mark.asyncio
async def test_send_wrapper_touches_updated_at(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """send() updates updated_at after facade.send returns."""
    session_key = "cli:default:touch1"
    facade = FakeSdkFacade()
    session_id = await _seed_session(store, facade, session_key, title="keep")

    before = await store.resolve(session_key, session_id=session_id)
    assert before is not None

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.send(session_key, "ping")

    after = await store.resolve(session_key, session_id=session_id)
    assert after is not None
    assert after.updated_at >= before.updated_at


# --- Task 4.9: error propagation and lock release ---


@pytest.mark.asyncio
async def test_error_propagation_cursor_agent_error_releases_lock(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """CursorAgentError from facade propagates and releases the per-session lock."""
    session_key = "cli:default:errprop1"
    facade = RaisingSendFacade(AuthError("invalid api key"))
    await _seed_session(store, facade, session_key, title="stable")

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    with pytest.raises(AuthError):
        await pool.send(session_key, "boom")

    result = await pool.send(session_key, "after error")
    assert result.status == RunStatus.FINISHED


@pytest.mark.asyncio
async def test_error_propagation_run_status_error_returns_and_releases_lock(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """RunStatus.ERROR returns normally, persists metadata, and releases the lock."""
    session_key = "cli:default:errstat1"
    facade = ErrorStatusSendFacade()
    session_id = await _seed_session(store, facade, session_key, title="stable")

    pool = SessionAgentPool(store=store, facade=facade, config=config)

    result = await pool.send(session_key, "fail run")
    assert result.status == RunStatus.ERROR

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata["last_status"] == RunStatus.ERROR.value

    second = await pool.send(session_key, "after error status")
    assert second.status == RunStatus.FINISHED


@pytest.mark.asyncio
async def test_send_raises_config_error_when_session_missing(
    store: SessionStore,
    config: CursorAgentConfig,
) -> None:
    """send() raises ConfigError when no session can be resolved."""
    facade = FakeSdkFacade()
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    with pytest.raises(ConfigError, match="session_key"):
        await pool.send("cli:default:missing", "hello")


@pytest.mark.asyncio
async def test_messaging_hook_deploy_does_not_corrupt_resume_cache_or_metadata(
    store: SessionStore,
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Workspace hook deploy must not change pool resume caching or session metadata."""
    from cursor_agent import messaging_hooks

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_key = "cli:default:hookdep1"
    facade = ResumeTrackingFacade()
    session_id = await _seed_session(
        store,
        facade,
        session_key,
        workspace=str(workspace),
    )

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)
    assert len(facade.resume_calls) == 1

    user_hooks = tmp_path / "user-hooks" / "messaging"
    messaging_hooks.install_messaging_hooks(target_dir=user_hooks)
    messaging_hooks.deploy_messaging_hooks_to_workspace(
        workspace,
        user_hooks_dir=user_hooks,
    )

    await pool.get(session_key)
    assert len(facade.resume_calls) == 1

    row = await store.resolve(session_key, session_id=session_id)
    assert row is not None
    assert row.metadata.get("status") != "compressing"


# --- PRD-005 security: effective resume tool_profile ---


@pytest.mark.asyncio
async def test_resume_uses_messaging_when_config_messaging_stored_coding(
    store: SessionStore,
) -> None:
    """Config messaging must win over a stored coding session profile on resume."""
    session_key = "cli:default:profmsg1"
    facade = ResumeTrackingFacade()
    await _seed_session(store, facade, session_key, tool_profile="coding")

    config = _config_with_tool_profile("messaging")
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)

    assert len(facade.resume_calls) == 1
    assert facade.resume_calls[0]["tool_profile"] == "messaging"


@pytest.mark.asyncio
async def test_resume_stays_messaging_when_config_coding_stored_messaging(
    store: SessionStore,
    tmp_path: Path,
) -> None:
    """Stored messaging profile must remain messaging even if config is coding."""
    session_key = "cli:default:profmsg2"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    facade = ResumeTrackingFacade()
    await _seed_session(
        store,
        facade,
        session_key,
        workspace=str(workspace),
        tool_profile="messaging",
    )

    config = _config_with_tool_profile("coding")
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)

    assert len(facade.resume_calls) == 1
    assert facade.resume_calls[0]["tool_profile"] == "messaging"
    assert (workspace / ".cursor" / "hooks.json").is_file()
    assert (workspace / ".cursor" / "hooks" / "messaging" / "shell-gate.sh").is_file()


@pytest.mark.asyncio
async def test_resume_skips_hook_deploy_for_coding_session(
    store: SessionStore,
    tmp_path: Path,
) -> None:
    """Coding sessions must not deploy messaging hooks on resume."""
    session_key = "cli:default:profcod2"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    facade = ResumeTrackingFacade()
    await _seed_session(
        store,
        facade,
        session_key,
        workspace=str(workspace),
        tool_profile="coding",
    )

    config = _config_with_tool_profile("coding")
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)

    assert not (workspace / ".cursor" / "hooks.json").exists()


@pytest.mark.asyncio
async def test_resume_stays_coding_when_config_and_stored_are_coding(
    store: SessionStore,
) -> None:
    """Coding config and stored profile must resume with coding tool_profile."""
    session_key = "cli:default:profcod1"
    facade = ResumeTrackingFacade()
    await _seed_session(store, facade, session_key, tool_profile="coding")

    config = _config_with_tool_profile("coding")
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    await pool.get(session_key)

    assert len(facade.resume_calls) == 1
    assert facade.resume_calls[0]["tool_profile"] == "coding"
