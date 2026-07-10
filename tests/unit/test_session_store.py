"""Unit tests for SessionStore create/resolve/list/touch and session helpers (PRD-002)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cursor_agent.sessions.models import (
    SessionCreateParams,
    build_cli_session_key,
    title_from_first_user_message,
)
from tests.unit.session_store_test_fakes import (
    FrozenClock,
    SteppingClock,
    initialized_store,
    iso_utc,
)


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


@pytest.mark.asyncio
async def test_session_store_create_persists_row(tmp_path: Path) -> None:
    """create() stores UUID id, agent_id, workspace, runtime, and tool_profile."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    assert row.created_at == iso_utc(t0)
    assert row.updated_at == iso_utc(t0)
    assert row.metadata == {}


@pytest.mark.asyncio
async def test_session_store_resolve_returns_latest_by_updated_at(
    tmp_path: Path,
) -> None:
    """resolve(session_key) returns the row with greatest updated_at."""
    t1 = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 16, 11, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t1, t2]))
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
async def test_session_store_resolve_tiebreaks_equal_updated_at_by_rowid(
    tmp_path: Path,
) -> None:
    """resolve(session_key) picks the most recently inserted row when updated_at ties."""
    frozen = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, FrozenClock(frozen))
    session_key = build_cli_session_key(tmp_path)

    first = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-first",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )
    second = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id="agent-second",
            workspace=str(tmp_path.resolve()),
            runtime="local",
        )
    )

    resolved = await store.resolve(session_key)
    assert resolved is not None
    assert resolved.id == second.id
    assert resolved.agent_id == "agent-second"
    assert resolved.id != first.id


@pytest.mark.asyncio
async def test_session_store_resolve_by_session_id(tmp_path: Path) -> None:
    """resolve(session_key, session_id) returns the specific row."""
    t1 = datetime(2026, 6, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 6, 16, 11, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t1, t2]))
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
    store = await initialized_store(tmp_path, SteppingClock([t1, t2, t3]))
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
    store = await initialized_store(
        tmp_path,
        SteppingClock([t_create, t_touch]),
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
    assert created.updated_at == iso_utc(t_create)

    touched = await store.touch(created.id)
    assert touched.updated_at == iso_utc(t_touch)
    assert touched.created_at == iso_utc(t_create)

    reloaded = await store.resolve(session_key, created.id)
    assert reloaded is not None
    assert reloaded.updated_at == iso_utc(t_touch)


@pytest.mark.asyncio
async def test_session_store_touch_raises_for_missing_session(tmp_path: Path) -> None:
    """touch raises when session_id does not exist."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.touch(missing_id)
