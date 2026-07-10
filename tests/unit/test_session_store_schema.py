"""Unit tests for SessionStore schema initialization and migrations (PRD-002)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from cursor_agent.sessions.models import build_cli_session_key
from cursor_agent.sessions.store import CURRENT_SCHEMA_VERSION, SessionStore
from tests.unit.session_store_test_fakes import iso_utc

_SESSIONS_COLUMNS = frozenset(
    {
        "id",
        "session_key",
        "agent_id",
        "title",
        "workspace",
        "runtime",
        "tool_profile",
        "created_at",
        "updated_at",
        "metadata",
    }
)


async def _fetch_table_info(db_path: Path, table: str) -> list[tuple[str, str]]:
    """Return (name, type) pairs from sqlite_master table_info."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
    return [(str(row[1]), str(row[2])) for row in rows]


async def _fetch_index_sql(db_path: Path, index_name: str) -> str | None:
    """Return CREATE INDEX SQL for a named index."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return str(row[0])


async def _fetch_user_version(db_path: Path) -> int:
    """Return SQLite PRAGMA user_version for schema migration baseline checks."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA user_version")
        row = await cursor.fetchone()
    if row is None:
        return 0
    return int(row[0])


_LEGACY_V0_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    title TEXT,
    workspace TEXT NOT NULL,
    runtime TEXT NOT NULL,
    tool_profile TEXT DEFAULT 'coding',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata JSON
)
"""

_LEGACY_V0_IDX_SESSIONS_KEY_DDL = """
CREATE INDEX IF NOT EXISTS idx_sessions_key
ON sessions(session_key, updated_at DESC)
"""


async def _seed_legacy_v0_database(
    db_path: Path,
    *,
    session_key: str,
    agent_id: str,
    workspace: str,
) -> str:
    """Create a pre-version V0 database with one session row (user_version stays 0)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    session_id = str(uuid.uuid4())
    timestamp = iso_utc(datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC))
    async with aiosqlite.connect(db_path) as db:
        await db.execute(_LEGACY_V0_SESSIONS_DDL)
        await db.execute(_LEGACY_V0_IDX_SESSIONS_KEY_DDL)
        await db.execute(
            """
            INSERT INTO sessions (
                id, session_key, agent_id, title, workspace, runtime,
                tool_profile, created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                session_key,
                agent_id,
                "legacy session",
                workspace,
                "local",
                "coding",
                timestamp,
                timestamp,
                "{}",
            ),
        )
        await db.commit()
    assert await _fetch_user_version(db_path) == 0
    return session_id


@pytest.mark.asyncio
async def test_session_store_schema_initialize_creates_sessions_table(
    tmp_path: Path,
) -> None:
    """initialize() creates sessions table with FR-1 columns."""
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path)
    await store.initialize()

    columns = await _fetch_table_info(db_path, "sessions")
    column_names = {name for name, _type in columns}
    assert column_names == _SESSIONS_COLUMNS


@pytest.mark.asyncio
async def test_session_store_schema_initialize_creates_idx_sessions_key(
    tmp_path: Path,
) -> None:
    """initialize() creates idx_sessions_key on (session_key, updated_at DESC)."""
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path)
    await store.initialize()

    index_sql = await _fetch_index_sql(db_path, "idx_sessions_key")
    assert index_sql is not None
    normalized = index_sql.lower().replace("\n", " ")
    assert "idx_sessions_key" in normalized
    assert "session_key" in normalized
    assert "updated_at" in normalized


@pytest.mark.asyncio
async def test_session_store_schema_initialize_is_idempotent(tmp_path: Path) -> None:
    """Calling initialize() twice does not fail."""
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path)
    await store.initialize()
    await store.initialize()

    columns = await _fetch_table_info(db_path, "sessions")
    assert len(columns) == len(_SESSIONS_COLUMNS)


@pytest.mark.asyncio
async def test_session_store_schema_version_recorded_on_initialize(
    tmp_path: Path,
) -> None:
    """initialize() records PRAGMA user_version at the V1 baseline."""
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path)
    await store.initialize()

    assert await _fetch_user_version(db_path) == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION == 1


@pytest.mark.asyncio
async def test_session_store_schema_reinitialize_preserves_version(
    tmp_path: Path,
) -> None:
    """Calling initialize() twice keeps schema version at the V1 baseline."""
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path)
    await store.initialize()
    await store.initialize()

    assert await _fetch_user_version(db_path) == CURRENT_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_session_store_schema_legacy_v0_upgrades_to_v1_baseline(
    tmp_path: Path,
) -> None:
    """Legacy V0 databases without version metadata upgrade to V1 on initialize."""
    db_path = tmp_path / "sessions.db"
    session_key = build_cli_session_key(tmp_path)
    await _seed_legacy_v0_database(
        db_path,
        session_key=session_key,
        agent_id="agent-legacy",
        workspace=str(tmp_path.resolve()),
    )

    store = SessionStore(db_path)
    await store.initialize()

    assert await _fetch_user_version(db_path) == CURRENT_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_session_store_schema_legacy_v0_rows_remain_readable(
    tmp_path: Path,
) -> None:
    """Baseline migration preserves existing session rows for public APIs."""
    db_path = tmp_path / "sessions.db"
    session_key = build_cli_session_key(tmp_path)
    legacy_id = await _seed_legacy_v0_database(
        db_path,
        session_key=session_key,
        agent_id="agent-legacy-readable",
        workspace=str(tmp_path.resolve()),
    )

    store = SessionStore(db_path)
    await store.initialize()

    resolved = await store.resolve(session_key, legacy_id)
    assert resolved is not None
    assert resolved.id == legacy_id
    assert resolved.agent_id == "agent-legacy-readable"
    assert resolved.title == "legacy session"

    rows = await store.list(session_key)
    assert len(rows) == 1
    assert rows[0].id == legacy_id


@pytest.mark.asyncio
async def test_session_store_schema_rejects_unsupported_future_version(
    tmp_path: Path,
) -> None:
    """initialize() rejects databases with a user_version above the supported baseline."""
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path)
    await store.initialize()

    unsupported_version = CURRENT_SCHEMA_VERSION + 1
    async with aiosqlite.connect(db_path) as db:
        await db.execute(f"PRAGMA user_version = {unsupported_version}")
        await db.commit()

    with pytest.raises(ValueError, match="unsupported schema version"):
        await store.initialize()
