"""Async SQLite session persistence (PRD-002 FR-1, FR-3)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from cursor_agent.sessions.models import SessionCreateParams, SessionRecord

_SESSIONS_DDL = """
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

_IDX_SESSIONS_KEY_DDL = """
CREATE INDEX IF NOT EXISTS idx_sessions_key
ON sessions(session_key, updated_at DESC)
"""

_SELECT_COLUMNS = """
    id, session_key, agent_id, title, workspace, runtime,
    tool_profile, created_at, updated_at, metadata
"""


def _timestamp_iso(moment: datetime) -> str:
    """Format a datetime as UTC ISO-8601."""
    return moment.astimezone(UTC).isoformat()


def _metadata_to_json(metadata: Mapping[str, object]) -> str:
    """Serialize metadata dict to JSON text."""
    try:
        return json.dumps(dict(metadata))
    except TypeError as exc:
        raise ValueError(
            f"invalid metadata: received {metadata!r}, expected JSON-serializable dict"
        ) from exc


def _metadata_from_json(raw: str | None) -> dict[str, object]:
    """Deserialize metadata JSON column to a dict."""
    if raw is None:
        return {}
    parsed: object = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(
            f"invalid metadata JSON: received {raw!r}, expected JSON object"
        )
    return dict(parsed)


def _row_to_session_record(row: aiosqlite.Row) -> SessionRecord:
    """Map a SQLite row to SessionRecord."""
    return SessionRecord(
        id=str(row["id"]),
        session_key=str(row["session_key"]),
        agent_id=str(row["agent_id"]),
        title=str(row["title"]) if row["title"] is not None else None,
        workspace=str(row["workspace"]),
        runtime=str(row["runtime"]),
        tool_profile=str(row["tool_profile"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        metadata=_metadata_from_json(
            str(row["metadata"]) if row["metadata"] is not None else None
        ),
    )


class SessionStore:
    """Persist session metadata in a local SQLite database."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create a store bound to ``db_path``.

        Args:
            db_path: Filesystem path to the SQLite database file.
            clock: Optional UTC clock for deterministic timestamps in tests.
        """
        self._db_path = Path(db_path)
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def initialize(self) -> None:
        """Create schema and indexes idempotently."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_SESSIONS_DDL)
            await db.execute(_IDX_SESSIONS_KEY_DDL)
            await db.commit()

    async def create(self, params: SessionCreateParams) -> SessionRecord:
        """Insert a new session row and return the persisted record."""
        session_id = str(uuid.uuid4())
        now = self._clock()
        timestamp = _timestamp_iso(now)
        metadata = params.metadata or {}
        metadata_json = _metadata_to_json(metadata)

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO sessions (
                    id, session_key, agent_id, title, workspace, runtime,
                    tool_profile, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    params.session_key,
                    params.agent_id,
                    params.title,
                    params.workspace,
                    params.runtime,
                    params.tool_profile,
                    timestamp,
                    timestamp,
                    metadata_json,
                ),
            )
            await db.commit()

        return SessionRecord(
            id=session_id,
            session_key=params.session_key,
            agent_id=params.agent_id,
            title=params.title,
            workspace=params.workspace,
            runtime=params.runtime,
            tool_profile=params.tool_profile,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=dict(metadata),
        )

    async def resolve(
        self,
        session_key: str,
        session_id: str | None = None,
    ) -> SessionRecord | None:
        """Return a session for ``session_key``, optionally filtered by ``session_id``."""
        if session_id is None:
            sql = f"""
                SELECT {_SELECT_COLUMNS}
                FROM sessions
                WHERE session_key = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """
            query_params: tuple[Any, ...] = (session_key,)
        else:
            sql = f"""
                SELECT {_SELECT_COLUMNS}
                FROM sessions
                WHERE session_key = ? AND id = ?
                """
            query_params = (session_key, session_id)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, query_params)
            row = await cursor.fetchone()

        if row is None:
            return None
        return _row_to_session_record(row)

    async def list(self, session_key: str) -> list[SessionRecord]:
        """List sessions for ``session_key`` ordered by ``updated_at`` descending."""
        sql = f"""
            SELECT {_SELECT_COLUMNS}
            FROM sessions
            WHERE session_key = ?
            ORDER BY updated_at DESC
            """

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, (session_key,))
            rows = await cursor.fetchall()

        return [_row_to_session_record(row) for row in rows]

    async def touch(self, session_id: str) -> SessionRecord:
        """Update ``updated_at`` for ``session_id`` and return the refreshed row."""
        timestamp = _timestamp_iso(self._clock())

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                UPDATE sessions
                SET updated_at = ?
                WHERE id = ?
                """,
                (timestamp, session_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"session not found: received session_id={session_id!r}, "
                    "expected existing session UUID"
                )
            await db.commit()
            cursor = await db.execute(
                f"SELECT {_SELECT_COLUMNS} FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            raise ValueError(
                f"session not found after touch: received session_id={session_id!r}, "
                "expected existing session UUID"
            )
        return _row_to_session_record(row)

    async def _fetch_by_id(self, session_id: str) -> SessionRecord | None:
        """Load a session row by primary key."""
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"SELECT {_SELECT_COLUMNS} FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            return None
        return _row_to_session_record(row)

    async def update_title(self, session_id: str, title: str) -> SessionRecord:
        """Set session title and return the refreshed row."""
        if not title:
            raise ValueError(
                f"invalid title: received {title!r}, expected non-empty string"
            )

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                UPDATE sessions
                SET title = ?
                WHERE id = ?
                """,
                (title, session_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(
                    f"session not found: received session_id={session_id!r}, "
                    "expected existing session UUID"
                )
            await db.commit()
            cursor = await db.execute(
                f"SELECT {_SELECT_COLUMNS} FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()

        if row is None:
            raise ValueError(
                f"session not found after title update: received session_id={session_id!r}, "
                "expected existing session UUID"
            )
        return _row_to_session_record(row)

    async def update_metadata(
        self,
        session_id: str,
        metadata: Mapping[str, object],
        *,
        merge: bool = True,
    ) -> SessionRecord:
        """Update session metadata, optionally merging with the stored payload."""
        _metadata_to_json(metadata)
        payload = dict(metadata)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                f"SELECT {_SELECT_COLUMNS} FROM sessions WHERE id = ?",
                (session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                raise ValueError(
                    f"session not found: received session_id={session_id!r}, "
                    "expected existing session UUID"
                )

            existing = _row_to_session_record(row)
            if merge:
                merged: dict[str, object] = {**existing.metadata, **payload}
            else:
                merged = payload

            merged_json = _metadata_to_json(merged)
            cursor = await db.execute(
                """
                UPDATE sessions
                SET metadata = ?
                WHERE id = ?
                """,
                (merged_json, session_id),
            )
            if cursor.rowcount == 0:
                await db.rollback()
                raise ValueError(
                    f"session not found: received session_id={session_id!r}, "
                    "expected existing session UUID"
                )
            await db.commit()
            cursor = await db.execute(
                f"SELECT {_SELECT_COLUMNS} FROM sessions WHERE id = ?",
                (session_id,),
            )
            updated_row = await cursor.fetchone()

        if updated_row is None:
            raise ValueError(
                f"session not found after metadata update: "
                f"received session_id={session_id!r}, expected existing session UUID"
            )
        return _row_to_session_record(updated_row)
