"""Unit tests for SessionStore metadata, title, agent_id, and hygiene APIs.

PRD-002 covers metadata/title/agent_id. PRD-017 FR-4 get/delete/
prune_workspace_sessions APIs are implemented (Wave 4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cursor_agent.sessions.models import (
    SessionCreateParams,
    SessionRecord,
    build_cli_session_key,
)
from cursor_agent.sessions.store import SessionStore
from tests.unit.session_store_test_fakes import (
    ControllableClock,
    SteppingClock,
    initialized_store,
)


@pytest.mark.asyncio
async def test_session_store_metadata_merge_preserves_existing_keys(
    tmp_path: Path,
) -> None:
    """update_metadata(..., merge=True) shallow-merges into stored metadata."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.update_title(missing_id, "orphan")


@pytest.mark.asyncio
async def test_session_store_update_metadata_raises_for_missing_session(
    tmp_path: Path,
) -> None:
    """update_metadata raises when session_id does not exist."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.update_metadata(missing_id, {"status": "idle"}, merge=True)


@pytest.mark.asyncio
async def test_session_store_update_agent_id_replaces_agent_id(tmp_path: Path) -> None:
    """update_agent_id(session_id, agent_id) swaps SDK agent id on the same row."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([t0]))
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
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    missing_id = str(uuid.uuid4())

    with pytest.raises(ValueError, match="session not found"):
        await store.update_agent_id(missing_id, "agent-orphan")


# --- PRD-017 FR-4: get / delete / prune_workspace_sessions (Wave 4) ------------


async def _create_workspace_session(
    store: SessionStore,
    *,
    session_key: str,
    workspace: Path,
    agent_id: str,
    title: str | None = None,
) -> SessionRecord:
    """Create one workspace session row; returns the SessionRecord."""
    return await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            title=title,
            workspace=str(workspace.resolve()),
            runtime="local",
        )
    )


@pytest.mark.asyncio
async def test_session_store_resolve_with_id_returns_scoped_record(
    tmp_path: Path,
) -> None:
    """resolve(session_key, session_id) returns the row when scoped to session_key."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)
    created = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-get",
        title="Visible",
    )

    found = await store.resolve(session_key, created.id)

    assert found is not None
    assert found.id == created.id
    assert found.title == "Visible"
    assert found.session_key == session_key


@pytest.mark.asyncio
async def test_session_store_resolve_with_id_returns_none_for_wrong_session_key(
    tmp_path: Path,
) -> None:
    """resolve with session_id must not leak a row belonging to another session_key."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0, t0]))
    key_a = build_cli_session_key(tmp_path / "ws-a")
    key_b = build_cli_session_key(tmp_path / "ws-b")
    (tmp_path / "ws-a").mkdir()
    (tmp_path / "ws-b").mkdir()
    created = await _create_workspace_session(
        store,
        session_key=key_a,
        workspace=tmp_path / "ws-a",
        agent_id="agent-a",
    )

    assert await store.resolve(key_b, created.id) is None


@pytest.mark.asyncio
async def test_session_store_resolve_with_id_returns_none_for_missing_id(
    tmp_path: Path,
) -> None:
    """resolve returns None when session_id does not exist under the key."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    session_key = build_cli_session_key(tmp_path)
    missing_id = str(uuid.uuid4())

    assert await store.resolve(session_key, missing_id) is None


@pytest.mark.asyncio
async def test_session_store_delete_removes_scoped_row(tmp_path: Path) -> None:
    """delete(session_key, session_id) removes the row and returns True."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0]))
    session_key = build_cli_session_key(tmp_path)
    created = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-del",
    )

    deleted = await store.delete(session_key, created.id)

    assert deleted is True
    assert await store.resolve(session_key, created.id) is None
    assert await store.list(session_key) == []


@pytest.mark.asyncio
async def test_session_store_delete_returns_false_for_wrong_session_key(
    tmp_path: Path,
) -> None:
    """delete scoped to another session_key must not mutate the row."""
    t0 = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(tmp_path, SteppingClock([t0, t0]))
    (tmp_path / "ws-a").mkdir()
    (tmp_path / "ws-b").mkdir()
    key_a = build_cli_session_key(tmp_path / "ws-a")
    key_b = build_cli_session_key(tmp_path / "ws-b")
    created = await _create_workspace_session(
        store,
        session_key=key_a,
        workspace=tmp_path / "ws-a",
        agent_id="agent-a",
    )

    deleted = await store.delete(key_b, created.id)

    assert deleted is False
    surviving = await store.resolve(key_a, created.id)
    assert surviving is not None
    assert surviving.id == created.id


@pytest.mark.asyncio
async def test_session_store_delete_returns_false_for_missing_id(
    tmp_path: Path,
) -> None:
    """delete returns False when session_id is absent."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    session_key = build_cli_session_key(tmp_path)
    missing_id = str(uuid.uuid4())

    assert await store.delete(session_key, missing_id) is False


@pytest.mark.asyncio
async def test_prune_workspace_sessions_or_caveat_deletes_all_old_keep_window(
    tmp_path: Path,
) -> None:
    """OR caveat: --older-than 7 --keep 5 deletes all 5 when all are >7 days old.

    ``keep_last`` is not a protection guarantee: rows matching older_than are
    deleted even when they sit inside the newest-N window (PRD-017 Q3).
    """
    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    thirty_days_ago = now - timedelta(days=30)
    clock = ControllableClock(thirty_days_ago)
    store = await initialized_store(tmp_path, clock)
    session_key = build_cli_session_key(tmp_path)

    created_ids: list[str] = []
    for index in range(5):
        record = await _create_workspace_session(
            store,
            session_key=session_key,
            workspace=tmp_path,
            agent_id=f"agent-old-{index}",
            title=f"Old {index}",
        )
        created_ids.append(record.id)

    clock.moment = now
    deleted_ids = await store.prune_workspace_sessions(
        session_key,
        older_than_days=7,
        keep_last=5,
    )

    assert set(deleted_ids) == set(created_ids)
    assert len(deleted_ids) == 5
    assert await store.list(session_key) == []


@pytest.mark.asyncio
async def test_prune_workspace_sessions_keep_last_retains_newest(
    tmp_path: Path,
) -> None:
    """keep_last alone retains the N most recently updated rows (updated_at DESC, id)."""
    t0 = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    times = [t0 + timedelta(hours=i) for i in range(4)]
    store = await initialized_store(tmp_path, SteppingClock(times))
    session_key = build_cli_session_key(tmp_path)

    created = [
        await _create_workspace_session(
            store,
            session_key=session_key,
            workspace=tmp_path,
            agent_id=f"agent-{i}",
            title=f"S{i}",
        )
        for i in range(4)
    ]
    newest_two = {created[3].id, created[2].id}

    deleted_ids = await store.prune_workspace_sessions(
        session_key,
        keep_last=2,
    )

    assert len(deleted_ids) == 2
    remaining = await store.list(session_key)
    assert {row.id for row in remaining} == newest_two
    assert set(deleted_ids).isdisjoint(newest_two)


@pytest.mark.asyncio
async def test_prune_workspace_sessions_older_than_deletes_stale_only(
    tmp_path: Path,
) -> None:
    """older_than_days alone deletes rows whose updated_at is older than the cutoff."""
    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    clock = ControllableClock(now - timedelta(days=30))
    store = await initialized_store(tmp_path, clock)
    session_key = build_cli_session_key(tmp_path)

    stale = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-stale",
        title="Stale",
    )
    clock.moment = now - timedelta(days=2)
    fresh = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-fresh",
        title="Fresh",
    )

    clock.moment = now
    deleted_ids = await store.prune_workspace_sessions(
        session_key,
        older_than_days=7,
    )

    assert deleted_ids == [stale.id]
    remaining = await store.list(session_key)
    assert len(remaining) == 1
    assert remaining[0].id == fresh.id


@pytest.mark.asyncio
async def test_prune_workspace_sessions_isolates_session_key(
    tmp_path: Path,
) -> None:
    """prune_workspace_sessions must not delete rows under another session_key."""
    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    clock = ControllableClock(now - timedelta(days=30))
    store = await initialized_store(tmp_path, clock)
    (tmp_path / "ws-a").mkdir()
    (tmp_path / "ws-b").mkdir()
    key_a = build_cli_session_key(tmp_path / "ws-a")
    key_b = build_cli_session_key(tmp_path / "ws-b")

    row_a = await _create_workspace_session(
        store,
        session_key=key_a,
        workspace=tmp_path / "ws-a",
        agent_id="agent-a",
    )
    row_b = await _create_workspace_session(
        store,
        session_key=key_b,
        workspace=tmp_path / "ws-b",
        agent_id="agent-b",
    )

    clock.moment = now
    deleted_ids = await store.prune_workspace_sessions(
        key_a,
        older_than_days=7,
    )

    assert deleted_ids == [row_a.id]
    surviving = await store.resolve(key_b, row_b.id)
    assert surviving is not None
    assert surviving.id == row_b.id


@pytest.mark.asyncio
async def test_prune_workspace_sessions_requires_at_least_one_criterion(
    tmp_path: Path,
) -> None:
    """Calling prune with neither older_than_days nor keep_last raises ValueError."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    session_key = build_cli_session_key(tmp_path)

    with pytest.raises(ValueError, match="older_than_days|keep_last"):
        await store.prune_workspace_sessions(session_key)


@pytest.mark.asyncio
async def test_prune_workspace_sessions_rejects_negative_older_than(
    tmp_path: Path,
) -> None:
    """older_than_days < 0 raises ValueError with the offending value."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    session_key = build_cli_session_key(tmp_path)

    with pytest.raises(ValueError, match="older_than_days.*-1"):
        await store.prune_workspace_sessions(session_key, older_than_days=-1)


@pytest.mark.asyncio
async def test_prune_workspace_sessions_rejects_negative_keep_last(
    tmp_path: Path,
) -> None:
    """keep_last < 0 raises ValueError with the offending value."""
    store = await initialized_store(tmp_path, SteppingClock([datetime.now(tz=UTC)]))
    session_key = build_cli_session_key(tmp_path)

    with pytest.raises(ValueError, match="keep_last.*-1"):
        await store.prune_workspace_sessions(session_key, keep_last=-1)


@pytest.mark.asyncio
async def test_prune_workspace_sessions_or_mixed_fresh_and_stale(
    tmp_path: Path,
) -> None:
    """OR mixed fixture: stale inside keep window deleted; fresh outside kept out.

    Three rows ordered newest→oldest by updated_at: fresh, stale-in-window,
    stale-outside. With --older-than 7 --keep 2, delete both stale rows (age)
    and the outside-keep stale; keep only the fresh newest.
    """
    now = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    clock = ControllableClock(now - timedelta(days=30))
    store = await initialized_store(tmp_path, clock)
    session_key = build_cli_session_key(tmp_path)

    stale_outside = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-stale-out",
        title="Stale outside keep",
    )
    clock.moment = now - timedelta(days=20)
    stale_inside = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-stale-in",
        title="Stale inside keep",
    )
    clock.moment = now - timedelta(days=1)
    fresh = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-fresh",
        title="Fresh",
    )

    clock.moment = now
    deleted_ids = await store.prune_workspace_sessions(
        session_key,
        older_than_days=7,
        keep_last=2,
    )

    assert set(deleted_ids) == {stale_outside.id, stale_inside.id}
    remaining = await store.list(session_key)
    assert [row.id for row in remaining] == [fresh.id]


@pytest.mark.asyncio
async def test_session_store_list_tiebreaks_by_id_desc(tmp_path: Path) -> None:
    """list orders by updated_at DESC, id DESC — same tie-break as prune keep."""
    same_moment = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    store = await initialized_store(
        tmp_path,
        SteppingClock([same_moment, same_moment, same_moment]),
    )
    session_key = build_cli_session_key(tmp_path)
    first = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-a",
        title="A",
    )
    second = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-b",
        title="B",
    )
    third = await _create_workspace_session(
        store,
        session_key=session_key,
        workspace=tmp_path,
        agent_id="agent-c",
        title="C",
    )

    listed = await store.list(session_key)
    listed_ids = [row.id for row in listed]
    # Lexicographic id DESC among equal timestamps.
    assert listed_ids == sorted([first.id, second.id, third.id], reverse=True)
