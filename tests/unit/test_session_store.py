"""Unit tests for SessionStore and session helpers (PRD-002)."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from cursor_agent.sessions.models import (
    SessionCreateParams,
    build_cli_session_key,
    title_from_first_user_message,
)
from cursor_agent.sessions.store import SessionStore


def _expected_workspace_hash(cwd: Path | str) -> str:
    """Compute workspace_hash per ADR-004."""
    absolute = str(Path(cwd).resolve())
    return hashlib.sha256(absolute.encode()).hexdigest()[:8]


def test_build_cli_session_key_default_profile(tmp_path: Path) -> None:
    """session_key uses cli:{profile}:{sha256(abs(cwd))[:8]} with default profile."""
    workspace_hash = _expected_workspace_hash(tmp_path)
    key = build_cli_session_key(tmp_path)
    assert key == f"cli:default:{workspace_hash}"


def test_build_cli_session_key_custom_profile(tmp_path: Path) -> None:
    """Custom profile is embedded in session_key."""
    workspace_hash = _expected_workspace_hash(tmp_path)
    key = build_cli_session_key(tmp_path, profile="work")
    assert key == f"cli:work:{workspace_hash}"


def test_build_cli_session_key_accepts_str_path(tmp_path: Path) -> None:
    """session_key builder accepts cwd as str."""
    workspace_hash = _expected_workspace_hash(str(tmp_path))
    key = build_cli_session_key(str(tmp_path))
    assert key == f"cli:default:{workspace_hash}"


def test_build_cli_session_key_different_cwd_different_hash(
    tmp_path: Path,
) -> None:
    """Different absolute cwd values produce different session keys."""
    other = tmp_path / "other"
    other.mkdir()
    assert build_cli_session_key(tmp_path) != build_cli_session_key(other)


def test_build_cli_session_key_rejects_empty_profile(tmp_path: Path) -> None:
    """Empty profile raises ValueError with offending value."""
    with pytest.raises(ValueError, match="profile"):
        build_cli_session_key(tmp_path, profile="")


def test_title_from_first_user_message_strips_whitespace() -> None:
    """Title strips leading and trailing whitespace."""
    assert title_from_first_user_message("  hello world  ") == "hello world"


def test_title_from_first_user_message_short_unchanged() -> None:
    """Messages up to 60 characters are returned after strip."""
    message = "a" * 60
    assert title_from_first_user_message(message) == message


def test_title_from_first_user_message_truncates_with_ellipsis() -> None:
    """Messages longer than 60 chars truncate to 57 plus ellipsis."""
    message = "b" * 70
    title = title_from_first_user_message(message)
    assert len(title) == 60
    assert title.endswith("...")
    assert title == ("b" * 57) + "..."


def test_title_from_first_user_message_rejects_empty() -> None:
    """Whitespace-only message raises ValueError."""
    with pytest.raises(ValueError, match="message"):
        title_from_first_user_message("   ")


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


class _SteppingClock:
    """Return predetermined UTC timestamps for deterministic store tests."""

    def __init__(self, times: list[datetime]) -> None:
        self._times: Iterator[datetime] = iter(times)

    def __call__(self) -> datetime:
        return next(self._times)


def _iso(dt: datetime) -> str:
    """Format datetime as UTC ISO-8601."""
    return dt.astimezone(UTC).isoformat()


async def _initialized_store(
    tmp_path: Path,
    clock: _SteppingClock,
) -> SessionStore:
    """Return an initialized SessionStore with injected clock."""
    store = SessionStore(tmp_path / "sessions.db", clock=clock)
    await store.initialize()
    return store


@pytest.mark.asyncio
async def test_session_store_create_persists_row(tmp_path: Path) -> None:
    """create() stores UUID id, agent_id, workspace, runtime, and tool_profile."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    row = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-123",
            workspace=str(tmp_path.resolve()),
            runtime="local",
            tool_profile="coding",
            title="first task",
        )
    )

    assert uuid.UUID(row.id)
    assert row.session_key == session_key
    assert row.agent_id == "agent-123"
    assert row.workspace == str(tmp_path.resolve())
    assert row.runtime == "local"
    assert row.tool_profile == "coding"
    assert row.title == "first task"
    assert row.created_at == _iso(t0)
    assert row.updated_at == _iso(t0)
    assert row.metadata == {}


@pytest.mark.asyncio
async def test_session_store_resolve_returns_latest_by_updated_at(
    tmp_path: Path,
) -> None:
    """resolve(session_key) returns the row with greatest updated_at."""
    t1 = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 16, 11, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t1, t2]))
    session_key = build_cli_session_key(tmp_path)

    older = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-old",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )
    newer = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-new",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    resolved = await store.resolve(session_key)
    assert resolved is not None
    assert resolved.id == newer.id
    assert resolved.agent_id == "agent-new"
    assert resolved.id != older.id


@pytest.mark.asyncio
async def test_session_store_resolve_by_session_id(tmp_path: Path) -> None:
    """resolve(session_key, session_id) returns the specific row."""
    t1 = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 16, 11, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t1, t2]))
    session_key = build_cli_session_key(tmp_path)

    older = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-old",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )
    await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-new",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    resolved = await store.resolve(session_key, older.id)
    assert resolved is not None
    assert resolved.id == older.id
    assert resolved.agent_id == "agent-old"


@pytest.mark.asyncio
async def test_session_store_list_sorted_most_recent_first(tmp_path: Path) -> None:
    """list(session_key) returns rows ordered by updated_at descending."""
    t1 = datetime(2026, 6, 16, 9, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
    t3 = datetime(2026, 6, 16, 11, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t1, t2, t3]))
    session_key = build_cli_session_key(tmp_path)

    first = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-1",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )
    second = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-2",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )
    third = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-3",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    rows = await store.list(session_key)
    assert [row.id for row in rows] == [third.id, second.id, first.id]


@pytest.mark.asyncio
async def test_session_store_touch_updates_updated_at(tmp_path: Path) -> None:
    """touch(session_id) bumps updated_at using the injected clock."""
    t_create = datetime(2026, 6, 16, 8, 0, 0, tzinfo=UTC)
    t_touch = datetime(2026, 6, 16, 12, 30, 0, tzinfo=UTC)
    store = await _initialized_store(
        tmp_path,
        _SteppingClock([t_create, t_touch]),
    )
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-touch",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )
    assert created.updated_at == _iso(t_create)

    touched = await store.touch(created.id)
    assert touched.updated_at == _iso(t_touch)
    assert touched.created_at == _iso(t_create)

    reloaded = await store.resolve(session_key, created.id)
    assert reloaded is not None
    assert reloaded.updated_at == _iso(t_touch)


@pytest.mark.asyncio
async def test_session_store_metadata_merge_preserves_existing_keys(
    tmp_path: Path,
) -> None:
    """update_metadata(..., merge=True) shallow-merges into stored metadata."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-meta",
            workspace=str(tmp_path.resolve()),
            runtime="local",
            metadata={"memory_injected": False},
        )
    )

    updated = await store.update_metadata(
        created.id,
        {"status": "idle", "last_run_id": "run-1"},
        merge=True,
    )
    assert updated.metadata == {
        "memory_injected": False,
        "status": "idle",
        "last_run_id": "run-1",
    }


@pytest.mark.asyncio
async def test_session_store_metadata_replace_overwrites_payload(
    tmp_path: Path,
) -> None:
    """update_metadata(..., merge=False) replaces metadata entirely."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-meta",
            workspace=str(tmp_path.resolve()),
            runtime="local",
            metadata={"memory_injected": True, "status": "busy"},
        )
    )

    updated = await store.update_metadata(
        created.id,
        {"last_status": "finished"},
        merge=False,
    )
    assert updated.metadata == {"last_status": "finished"}


@pytest.mark.asyncio
async def test_session_store_metadata_persists_pool_fields(tmp_path: Path) -> None:
    """Metadata round-trips pool fields like last_run_id and last_status."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-meta",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    payload = {
        "memory_injected": True,
        "status": "running",
        "last_run_id": "run-abc",
        "last_status": "error",
    }
    await store.update_metadata(created.id, payload, merge=True)

    reloaded = await store.resolve(session_key, created.id)
    assert reloaded is not None
    assert reloaded.metadata == payload


@pytest.mark.asyncio
async def test_session_store_metadata_rejects_non_serializable_payload(
    tmp_path: Path,
) -> None:
    """Non-JSON-serializable metadata raises ValueError with offending payload."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-meta",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    bad_payload: dict[str, object] = {"handler": object()}
    with pytest.raises(ValueError, match="metadata"):
        await store.update_metadata(created.id, bad_payload, merge=True)


@pytest.mark.asyncio
async def test_session_store_update_title_sets_title(tmp_path: Path) -> None:
    """update_title(session_id, title) persists a non-empty title."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-title",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    updated = await store.update_title(created.id, "Renamed session")
    assert updated.title == "Renamed session"

    reloaded = await store.resolve(session_key, created.id)
    assert reloaded is not None
    assert reloaded.title == "Renamed session"


@pytest.mark.asyncio
async def test_session_store_update_title_rejects_empty_title(tmp_path: Path) -> None:
    """update_title rejects empty titles before touching the database."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-title",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    with pytest.raises(ValueError, match="title"):
        await store.update_title(created.id, "")


@pytest.mark.asyncio
async def test_session_store_update_title_raises_for_missing_session(
    tmp_path: Path,
) -> None:
    """update_title raises when session_id does not exist."""
    store = await _initialized_store(tmp_path, _SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.update_title(missing_id, "orphan")


@pytest.mark.asyncio
async def test_session_store_update_metadata_raises_for_missing_session(
    tmp_path: Path,
) -> None:
    """update_metadata raises when session_id does not exist."""
    store = await _initialized_store(tmp_path, _SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.update_metadata(missing_id, {"status": "idle"}, merge=True)


@pytest.mark.asyncio
async def test_session_store_touch_raises_for_missing_session(tmp_path: Path) -> None:
    """touch raises when session_id does not exist."""
    store = await _initialized_store(tmp_path, _SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.touch(missing_id)


@pytest.mark.asyncio
async def test_session_store_update_agent_id_replaces_agent_id(tmp_path: Path) -> None:
    """update_agent_id(session_id, agent_id) swaps SDK agent id on the same row."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-before-compress",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    updated = await store.update_agent_id(created.id, "agent-after-compress")
    assert updated.id == created.id
    assert updated.agent_id == "agent-after-compress"
    assert updated.session_key == created.session_key

    reloaded = await store.resolve(session_key, created.id)
    assert reloaded is not None
    assert reloaded.id == created.id
    assert reloaded.agent_id == "agent-after-compress"


@pytest.mark.asyncio
async def test_session_store_update_agent_id_rejects_empty_agent_id(
    tmp_path: Path,
) -> None:
    """update_agent_id rejects empty agent_id before touching the database."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await _initialized_store(tmp_path, _SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)

    created = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-valid",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    with pytest.raises(ValueError, match="agent_id"):
        await store.update_agent_id(created.id, "")


@pytest.mark.asyncio
async def test_session_store_update_agent_id_raises_for_missing_session(
    tmp_path: Path,
) -> None:
    """update_agent_id raises when session_id does not exist."""
    store = await _initialized_store(tmp_path, _SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.update_agent_id(missing_id, "agent-orphan")
