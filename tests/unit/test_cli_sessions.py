"""Unit tests for CLI sessions subcommands (PRD-003 FR-9)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.startup import create_store, load_cwd_dotenv, session_key_for
from cursor_agent.config.loader import load_config
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore


async def _seed_sessions(
    store: SessionStore,
    session_key: str,
    *,
    titles: list[str | None],
) -> list[str]:
    """Initialize store and create session rows; return created ids."""
    await store.initialize()
    ids: list[str] = []
    for title in titles:
        record = await store.create(
            SessionCreateParams(
                session_key=session_key,
                agent_id=f"agent-{len(ids)}",
                title=title,
                workspace="/tmp/workspace",
                runtime="local",
            )
        )
        ids.append(record.id)
    return ids


def test_sessions_list_prints_seeded_sessions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions list prints id, title, and updated_at for the current session_key."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    ids = asyncio.run(_seed_sessions(store, session_key, titles=["First session"]))

    def stub_create_store(
        _config: object,
        *,
        store_path: Path | None = None,
    ) -> SessionStore:
        return SessionStore(db_path)

    monkeypatch.setattr("cursor_agent.cli.app.create_store", stub_create_store)

    result = CliRunner().invoke(app, ["sessions", "list"])
    assert result.exit_code == 0
    assert ids[0] in result.stdout
    assert "First session" in result.stdout


def test_sessions_list_shows_untitled_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions list uses (untitled) when title is None."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    asyncio.run(_seed_sessions(store, session_key, titles=[None]))

    def stub_create_store(
        _config: object,
        *,
        store_path: Path | None = None,
    ) -> SessionStore:
        return SessionStore(db_path)

    monkeypatch.setattr("cursor_agent.cli.app.create_store", stub_create_store)

    result = CliRunner().invoke(app, ["sessions", "list"])
    assert result.exit_code == 0
    assert "(untitled)" in result.stdout


def test_sessions_list_empty_store_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty store prints a friendly message and exits 0."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))

    store = create_store(
        load_config(config_path=Path("/nonexistent/config.yaml")),
        store_path=db_path,
    )
    asyncio.run(store.initialize())

    def stub_create_store(
        _config: object,
        *,
        store_path: Path | None = None,
    ) -> SessionStore:
        return SessionStore(db_path)

    monkeypatch.setattr("cursor_agent.cli.app.create_store", stub_create_store)

    result = CliRunner().invoke(app, ["sessions", "list"])
    assert result.exit_code == 0
    assert "No sessions" in result.stdout


def test_sessions_list_uses_dotenv_workspace_for_session_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions list honors CURSOR_AGENT__RUNTIME__LOCAL__CWD from CWD .env."""
    workspace = tmp_path / "dotenv-workspace"
    workspace.mkdir()
    db_path = tmp_path / "sessions.db"
    (tmp_path / ".env").write_text(
        f"CURSOR_AGENT__RUNTIME__LOCAL__CWD={workspace}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", raising=False)
    monkeypatch.chdir(tmp_path)
    load_cwd_dotenv()

    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    ids = asyncio.run(
        _seed_sessions(store, session_key, titles=["Dotenv workspace session"])
    )

    def stub_create_store(
        _config: object,
        *,
        store_path: Path | None = None,
    ) -> SessionStore:
        return SessionStore(db_path)

    monkeypatch.setattr("cursor_agent.cli.app.create_store", stub_create_store)

    result = CliRunner().invoke(app, ["sessions", "list"])
    assert result.exit_code == 0
    assert ids[0] in result.stdout
    assert "Dotenv workspace session" in result.stdout
