"""Unit tests for CLI bootstrap and REPL loop skeleton (PRD-003)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.cli.app import run_default
from cursor_agent.cli.startup import (
    create_store,
    repl_runtime,
    resolve_sessions_db_path,
    session_key_for,
)
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import (
    SendSpyPool,
    drive_repl,
    expected_session_key,
    seed_session,
)


def test_session_key_for_returns_cli_default_hex(config: CursorAgentConfig) -> None:
    """session_key_for returns cli:default:{8hex} for config workspace."""
    key = session_key_for(config)
    expected = expected_session_key(config.runtime.local.cwd)
    assert key == expected
    assert key.startswith("cli:default:")
    assert len(key.split(":")[2]) == 8


def test_create_store_uses_override_path(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """create_store honors store_path override."""
    db_path = tmp_path / "custom.db"
    store = create_store(config, store_path=db_path)
    assert store._db_path == db_path


def test_resolve_sessions_db_path_uses_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default sessions DB path is used when CURSOR_AGENT_SESSIONS_DB is unset."""
    monkeypatch.delenv("CURSOR_AGENT_SESSIONS_DB", raising=False)
    from cursor_agent.cli.startup import DEFAULT_DB_PATH

    assert resolve_sessions_db_path() == DEFAULT_DB_PATH


def test_resolve_sessions_db_path_honors_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CURSOR_AGENT_SESSIONS_DB selects the SQLite session store path."""
    db_path = tmp_path / "custom-sessions.db"
    monkeypatch.setenv("CURSOR_AGENT_SESSIONS_DB", str(db_path))
    assert resolve_sessions_db_path() == db_path


def test_create_store_uses_env_sessions_db_when_no_store_path(
    config: CursorAgentConfig,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """create_store falls back to CURSOR_AGENT_SESSIONS_DB before the default path."""
    db_path = tmp_path / "env-sessions.db"
    monkeypatch.setenv("CURSOR_AGENT_SESSIONS_DB", str(db_path))
    store = create_store(config)
    assert store._db_path == db_path


async def test_repl_runtime_yields_pool_and_closes_facade(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """repl_runtime initializes store, yields pool, and closes injected facade."""
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    async with repl_runtime(
        config,
        store_path=db_path,
        facade=facade,
    ) as (pool, session_key, store, yielded_facade):
        assert isinstance(pool, SessionAgentPool)
        assert session_key == session_key_for(config)
        assert isinstance(store, SessionStore)
        assert yielded_facade is facade
        assert db_path.exists()
        assert facade._closed is False

    assert facade._closed is True


async def test_run_repl_auto_resume_with_existing_session(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """auto_resume sets active session and writes Resumed when store has a row."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key)

    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    status = await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=output.append,
        auto_resume=True,
    )

    assert status is None
    assert any("Resumed session" in line for line in output)


async def test_run_repl_no_session_writes_new_guidance(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """When no session exists, writer contains /new guidance."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=output.append,
        auto_resume=True,
    )

    assert any("/new" in line for line in output)


async def test_run_repl_quit_exits_and_returns_none(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """/quit breaks the loop and returns None."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    status = await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/quit",),
        writer=lambda _line: None,
        auto_resume=False,
    )

    assert status is None


async def test_run_repl_unknown_slash_without_skill_uses_free_text_path(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """ADR-013: unknown slash with no skill match follows the free-text REPL path."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/definitely-unknown", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert any("No active session" in line for line in output)
    assert not any("Command not available yet" in line for line in output)


async def test_run_repl_free_text_without_session_guidance(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Free text without active session prompts /new or /resume."""
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SendSpyPool(store=store, facade=facade, config=config)
    output: list[str] = []

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("hello", "/quit"),
        writer=output.append,
        auto_resume=False,
    )

    assert any("/new" in line and "/resume" in line for line in output)
    assert pool.send_calls == []


@pytest.fixture
def messaging_config(tmp_path: Path) -> CursorAgentConfig:
    """Config with messaging tool profile for hook deploy bootstrap tests."""
    return load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={"tool_profile": "messaging"},
    )


async def test_repl_runtime_messaging_deploys_hooks_before_pool(
    messaging_config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Messaging startup installs and deploys hooks before pool/facade use."""
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    with (
        patch(
            "cursor_agent.cli.startup.ensure_messaging_hooks",
        ) as mock_ensure,
    ):
        async with repl_runtime(
            messaging_config,
            store_path=db_path,
            facade=facade,
        ):
            mock_ensure.assert_called_once()

    assert facade._closed is True


async def test_repl_runtime_coding_skips_messaging_hook_deploy(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Coding startup must not install or deploy messaging deny hooks."""
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    with (
        patch(
            "cursor_agent.cli.startup.ensure_messaging_hooks",
        ) as mock_ensure,
    ):
        async with repl_runtime(
            config,
            store_path=db_path,
            facade=facade,
        ):
            mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_run_default_welcome_before_repl_bootstrap(
    config: CursorAgentConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default bootstrap invokes welcome rendering before REPL startup."""
    call_order: list[str] = []

    def stub_render_welcome(
        _writer: object,
        *,
        first_run: bool,
        is_tty: bool,
        no_banner: bool,
        is_ci: bool,
    ) -> bool:
        _ = (first_run, is_tty, no_banner, is_ci)
        call_order.append("render_welcome")
        return False

    @asynccontextmanager
    async def stub_repl_runtime(_cfg: CursorAgentConfig):
        call_order.append("repl_runtime")
        yield object(), session_key_for(config), object(), object()

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        call_order.append("run_repl")
        return None

    monkeypatch.setattr("cursor_agent.cli.app.render_welcome", stub_render_welcome)
    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", stub_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)

    await run_default(config, marker_home=tmp_path, is_tty=True, is_ci=False)

    assert call_order.index("render_welcome") < call_order.index("repl_runtime")
    assert call_order.index("render_welcome") < call_order.index("run_repl")
