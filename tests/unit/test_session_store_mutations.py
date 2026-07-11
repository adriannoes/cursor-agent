"""Unit tests for SessionStore metadata, title, and agent_id mutations (PRD-002)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cursor_agent.sessions.models import SessionCreateParams, build_cli_session_key
from tests.unit.session_store_test_fakes import SteppingClock, initialized_store


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
