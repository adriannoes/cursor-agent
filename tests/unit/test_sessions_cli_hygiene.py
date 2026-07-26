"""CLI tests for sessions show/delete/prune hygiene (PRD-017 FR-4).

Stub ``cursor_agent.cli.sessions_commands.create_store`` so commands use a
shared SQLite file under ``tmp_path`` (create_store lives in sessions_commands
after the Task 5.3 extract).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import load_config
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore
from tests.unit.session_store_test_fakes import ControllableClock


def _stub_create_store(
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
    *,
    clock: ControllableClock | None = None,
) -> None:
    """Point CLI create_store at a shared SQLite file (and optional clock)."""

    def stub_create_store(
        _config: object,
        *,
        store_path: Path | None = None,
    ) -> SessionStore:
        if clock is None:
            return SessionStore(db_path)
        return SessionStore(db_path, clock=clock)

    monkeypatch.setattr(
        "cursor_agent.cli.sessions_commands.create_store",
        stub_create_store,
    )


async def _seed_session(
    store: SessionStore,
    session_key: str,
    *,
    workspace: Path,
    agent_id: str,
    title: str | None = None,
) -> str:
    """Create one session row; return its id."""
    await store.initialize()
    record = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            title=title,
            workspace=str(workspace.resolve()),
            runtime="local",
        )
    )
    return record.id


def _combined_output(result: object) -> str:
    """Join stdout/stderr/output for assertion-friendly scanning."""
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = getattr(result, "output", "") or ""
    return f"{stdout}\n{stderr}\n{output}"


def test_sessions_show_prints_operator_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions show <id> prints all operator fields from _print_session_detail."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    session_id = asyncio.run(
        _seed_session(
            store,
            session_key,
            workspace=tmp_path,
            agent_id="agent-show",
            title="Show me",
        )
    )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(app, ["sessions", "show", session_id])

    assert result.exit_code == 0, result.output
    combined = _combined_output(result)
    # Match _print_session_detail tab-separated labels (sessions_commands.py).
    assert f"id\t{session_id}" in combined
    assert "title\tShow me" in combined
    assert "agent_id\tagent-show" in combined
    assert f"workspace\t{tmp_path.resolve()}" in combined
    assert "runtime\tlocal" in combined
    assert "tool_profile\tcoding" in combined
    assert "created_at\t" in combined
    assert "updated_at\t" in combined


def test_sessions_show_unknown_id_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions show with a missing id exits 1 with a clear message."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    store = SessionStore(db_path)
    asyncio.run(store.initialize())
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "show", "00000000-0000-0000-0000-000000000000"],
    )

    assert result.exit_code == 1
    assert "session" in _combined_output(result).lower()


def test_sessions_show_other_workspace_session_key_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions show must not reveal a row owned by another session_key."""
    db_path = tmp_path / "sessions.db"
    ws_a = tmp_path / "ws-a"
    ws_b = tmp_path / "ws-b"
    ws_a.mkdir()
    ws_b.mkdir()

    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(ws_a))
    config_a = load_config(config_path=Path("/nonexistent/config.yaml"))
    key_a = session_key_for(config_a)

    store = SessionStore(db_path)
    foreign_id = asyncio.run(
        _seed_session(
            store,
            key_a,
            workspace=ws_a,
            agent_id="agent-foreign",
            title="Other workspace",
        )
    )

    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(ws_b))
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(app, ["sessions", "show", foreign_id])

    assert result.exit_code == 1
    assert "Other workspace" not in _combined_output(result)


def test_sessions_delete_yes_removes_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions delete --yes deletes the scoped row without prompting."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    session_id = asyncio.run(
        _seed_session(
            store,
            session_key,
            workspace=tmp_path,
            agent_id="agent-del",
            title="Delete me",
        )
    )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "delete", session_id, "--yes"],
    )

    assert result.exit_code == 0, result.output
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert remaining == []


def test_sessions_delete_explicit_n_cancels_with_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit confirm ``n`` exits 0 and leaves the row untouched."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    session_id = asyncio.run(
        _seed_session(
            store,
            session_key,
            workspace=tmp_path,
            agent_id="agent-keep",
            title="Keep me",
        )
    )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "delete", session_id],
        input="n\n",
    )

    assert result.exit_code == 0, result.output
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert len(remaining) == 1
    assert remaining[0].id == session_id


def test_sessions_delete_eof_without_yes_exits_one_and_mentions_yes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EOF/empty stdin without --yes exits 1, zero mutations, mentions --yes."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    session_id = asyncio.run(
        _seed_session(
            store,
            session_key,
            workspace=tmp_path,
            agent_id="agent-eof",
            title="EOF guard",
        )
    )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "delete", session_id],
        input="",
    )

    assert result.exit_code == 1
    combined = _combined_output(result)
    assert "--yes" in combined
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert len(remaining) == 1
    assert remaining[0].id == session_id


def test_sessions_delete_wrong_id_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions delete for an unknown id exits 1."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    store = SessionStore(db_path)
    asyncio.run(store.initialize())
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "delete", "00000000-0000-0000-0000-000000000000", "--yes"],
    )

    assert result.exit_code == 1


def test_sessions_prune_or_caveat_deletes_all_old_keep_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI OR caveat: --older-than 7 --keep 5 deletes all 5 when all are stale."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    clock = ControllableClock(now - timedelta(days=30))
    store = SessionStore(db_path, clock=clock)
    asyncio.run(store.initialize())
    for index in range(5):
        asyncio.run(
            store.create(
                SessionCreateParams(
                    session_key=session_key,
                    agent_id=f"agent-old-{index}",
                    title=f"Old {index}",
                    workspace=str(tmp_path.resolve()),
                    runtime="local",
                )
            )
        )
    clock.moment = now
    _stub_create_store(monkeypatch, db_path, clock=clock)

    result = CliRunner().invoke(
        app,
        ["sessions", "prune", "--older-than", "7", "--keep", "5", "--yes"],
    )

    assert result.exit_code == 0, result.output
    combined = _combined_output(result)
    assert "5" in combined
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert remaining == []


def test_sessions_prune_requires_older_than_or_keep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions prune without --older-than or --keep exits non-zero with a hint."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    store = SessionStore(db_path)
    asyncio.run(store.initialize())
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(app, ["sessions", "prune", "--yes"])
    combined = _combined_output(result)

    # Fail RED on missing command; once registered, require a criterion hint.
    assert "No such command" not in combined
    assert result.exit_code != 0
    assert "older-than" in combined.lower() or "keep" in combined.lower()


def test_sessions_prune_explicit_n_cancels_with_exit_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit confirm ``n`` on prune exits 0 and leaves rows unchanged."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    asyncio.run(
        _seed_session(
            store,
            session_key,
            workspace=tmp_path,
            agent_id="agent-prune-keep",
            title="Stay",
        )
    )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "prune", "--keep", "0"],
        input="n\n",
    )

    assert result.exit_code == 0, result.output
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert len(remaining) == 1


def test_sessions_prune_eof_without_yes_exits_one_and_mentions_yes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EOF/empty stdin on prune without --yes exits 1, no mutation, mentions --yes."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    asyncio.run(
        _seed_session(
            store,
            session_key,
            workspace=tmp_path,
            agent_id="agent-prune-eof",
            title="EOF prune",
        )
    )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "prune", "--keep", "0"],
        input="",
    )

    assert result.exit_code == 1
    assert "--yes" in _combined_output(result)
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert len(remaining) == 1


def test_sessions_prune_prints_deleted_and_kept_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions prune --yes prints deleted and kept counts."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(tmp_path))
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    session_key = session_key_for(config)

    store = SessionStore(db_path)
    asyncio.run(store.initialize())
    for index in range(3):
        asyncio.run(
            store.create(
                SessionCreateParams(
                    session_key=session_key,
                    agent_id=f"agent-{index}",
                    title=f"S{index}",
                    workspace=str(tmp_path.resolve()),
                    runtime="local",
                )
            )
        )
    _stub_create_store(monkeypatch, db_path)

    result = CliRunner().invoke(
        app,
        ["sessions", "prune", "--keep", "1", "--yes"],
    )

    assert result.exit_code == 0, result.output
    combined = _combined_output(result)
    # Exact production format from sessions_prune (sessions_commands.py).
    assert "Deleted 2, kept 1." in combined
    remaining = asyncio.run(SessionStore(db_path).list(session_key))
    assert len(remaining) == 1


def test_sessions_prune_isolates_cross_session_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sessions prune only mutates the current workspace session_key."""
    db_path = tmp_path / "sessions.db"
    ws_a = tmp_path / "ws-a"
    ws_b = tmp_path / "ws-b"
    ws_a.mkdir()
    ws_b.mkdir()

    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    clock = ControllableClock(now - timedelta(days=30))
    store = SessionStore(db_path, clock=clock)
    asyncio.run(store.initialize())

    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(ws_a))
    key_a = session_key_for(load_config(config_path=Path("/nonexistent/config.yaml")))
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(ws_b))
    key_b = session_key_for(load_config(config_path=Path("/nonexistent/config.yaml")))

    id_a = asyncio.run(
        store.create(
            SessionCreateParams(
                session_key=key_a,
                agent_id="agent-a",
                title="A",
                workspace=str(ws_a.resolve()),
                runtime="local",
            )
        )
    ).id
    id_b = asyncio.run(
        store.create(
            SessionCreateParams(
                session_key=key_b,
                agent_id="agent-b",
                title="B",
                workspace=str(ws_b.resolve()),
                runtime="local",
            )
        )
    ).id

    clock.moment = now
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(ws_a))
    _stub_create_store(monkeypatch, db_path, clock=clock)

    result = CliRunner().invoke(
        app,
        ["sessions", "prune", "--older-than", "7", "--yes"],
    )

    assert result.exit_code == 0, result.output
    assert asyncio.run(SessionStore(db_path).list(key_a)) == []
    surviving = asyncio.run(SessionStore(db_path).list(key_b))
    assert len(surviving) == 1
    assert surviving[0].id == id_b
    assert id_a != id_b
