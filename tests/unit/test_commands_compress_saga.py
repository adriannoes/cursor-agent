"""Unit tests for run_compress_session saga (PRD-004 FR-6, FR-7 / ADR-011)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.cli.compress import load_compress_prompt, run_compress_session
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.errors import ConfigError
from cursor_agent.memory.store import (
    MEMORY_FILENAME,
    MEMORY_SECTION_MARKER,
    USER_FILENAME,
    USER_MEMORY_SECTION_MARKER,
)
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.skills.discovery import skill_discovery_from_config
from cursor_agent.skills.injection import format_skill_section_marker
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import SendSpyPool, drive_repl, seed_session
from tests.unit.command_handler_fakes import _CompressSendSpyFacade, _SUMMARY_REPLY

_COMPRESS_TEST_USER_MEMORY = "compress-no-reinject-user-preference-unique"
_COMPRESS_TEST_MEMORY_FACT = "compress-no-reinject-memory-fact-unique"
_COMPRESS_TEST_SKILL_BODY = "compress-no-reinject-skill-body-unique-playbook-content"
_COMPRESS_TEST_SKILL_NAME = "canvas"


def _compress_skills_config(tmp_path: Path, *, workspace: Path) -> CursorAgentConfig:
    """Build config with ``runtime.local.cwd`` pointed at an injectable workspace."""
    return load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={"runtime": {"local": {"cwd": str(workspace)}}},
    )


def _project_skills_root(workspace: Path) -> Path:
    """Return ``{workspace}/.cursor/skills``, creating parent dirs when needed."""
    root = workspace / ".cursor" / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_compress_skill_fixture(
    skills_root: Path,
    *,
    body: str,
    name: str = _COMPRESS_TEST_SKILL_NAME,
) -> None:
    """Create a canvas skill SKILL.md with YAML frontmatter under a skills root."""
    skill_dir = skills_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                "description: Compress regression skill fixture.",
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


def _write_compress_memory_fixtures(memory_root: Path) -> None:
    """Write distinctive USER.md and MEMORY.md under a temporary memory root."""
    memory_root.mkdir(parents=True, exist_ok=True)
    (memory_root / USER_FILENAME).write_text(
        _COMPRESS_TEST_USER_MEMORY,
        encoding="utf-8",
    )
    (memory_root / MEMORY_FILENAME).write_text(
        _COMPRESS_TEST_MEMORY_FACT,
        encoding="utf-8",
    )


async def _seed_session_with_memory_injected(
    store: SessionStore,
    facade: FakeSdkFacade,
    session_key: str,
    *,
    workspace: str,
) -> str:
    """Create a session row that already has durable memory injection metadata."""
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=workspace,
    )
    await store.update_metadata(
        session_id,
        {
            "memory_injected": True,
            "last_run_id": "compress-memory-regression-run",
            "last_status": "finished",
        },
    )
    return session_id


async def test_compress_session_happy_path_updates_same_row(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Successful /compress sets compressing status, swaps agent_id, and seeds summary."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-happy"
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    facade._status_session_id = session_id
    row_before = await store.resolve(session_key, session_id=session_id)
    assert row_before is not None
    previous_agent_id = row_before.agent_id
    compress_prompt = load_compress_prompt()

    result = await run_compress_session(
        store=store,
        facade=facade,
        config=config,
        session_key=session_key,
        session_id=session_id,
    )

    assert result.session_id == session_id
    assert result.previous_agent_id == previous_agent_id
    assert result.new_agent_id != previous_agent_id

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.id == session_id
    assert row_after.agent_id == result.new_agent_id
    assert "status" not in row_after.metadata

    assert len(facade.create_agent_calls) == 2
    assert facade.send_calls[0]["agent_id"] == previous_agent_id
    assert facade.send_calls[0]["message"] == compress_prompt
    assert facade.send_calls[1]["agent_id"] == result.new_agent_id
    assert facade.send_calls[1]["message"] == _SUMMARY_REPLY

    new_agent_messages = facade.messages_for(result.new_agent_id)
    assert new_agent_messages[0]["role"] == "user"
    assert new_agent_messages[0]["content"] == _SUMMARY_REPLY


async def test_compress_session_rollback_on_summary_delivery_failure(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Mid-flight failure restores previous agent_id and clears compressing status."""
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        fail_on_summary_delivery=True,
    )
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-rollback"
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    row_before = await store.resolve(session_key, session_id=session_id)
    assert row_before is not None
    previous_agent_id = row_before.agent_id

    with pytest.raises(ConfigError, match="summary delivery"):
        await run_compress_session(
            store=store,
            facade=facade,
            config=config,
            session_key=session_key,
            session_id=session_id,
        )

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.id == session_id
    assert row_after.agent_id == previous_agent_id
    assert "status" not in row_after.metadata

    assert len(facade.create_agent_calls) == 2
    assert len(facade.send_calls) == 2
    assert len(facade.cancel_calls) == 1
    assert facade.cancel_calls[0] != previous_agent_id


async def test_compress_session_preserves_memory_injected_metadata(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Successful /compress keeps memory_injected on the same session row."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-memory-preserve"
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await _seed_session_with_memory_injected(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    facade._status_session_id = session_id
    _write_compress_memory_fixtures(tmp_path / "memory")

    result = await run_compress_session(
        store=store,
        facade=facade,
        config=config,
        session_key=session_key,
        session_id=session_id,
    )

    row_after = await store.resolve(session_key, session_id=result.session_id)
    assert row_after is not None
    assert row_after.metadata.get("memory_injected") is True
    assert row_after.metadata.get("last_run_id") == "compress-memory-regression-run"
    assert row_after.metadata.get("last_status") == "finished"
    assert "status" not in row_after.metadata
    assert facade.metadata_at_send
    assert facade.metadata_at_send[0].get("memory_injected") is True


async def test_compress_session_summary_seed_does_not_reinject_memory(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Summary delivery to the new agent must not prepend Memory v1 payload."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-no-reinject"
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await _seed_session_with_memory_injected(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    facade._status_session_id = session_id
    _write_compress_memory_fixtures(tmp_path / "memory")

    result = await run_compress_session(
        store=store,
        facade=facade,
        config=config,
        session_key=session_key,
        session_id=session_id,
    )

    assert len(facade.send_calls) == 2
    summary_seed = facade.send_calls[1]
    assert summary_seed["agent_id"] == result.new_agent_id
    assert summary_seed["message"] == _SUMMARY_REPLY
    assert USER_MEMORY_SECTION_MARKER not in summary_seed["message"]
    assert MEMORY_SECTION_MARKER not in summary_seed["message"]
    assert _COMPRESS_TEST_USER_MEMORY not in summary_seed["message"]
    assert _COMPRESS_TEST_MEMORY_FACT not in summary_seed["message"]


async def test_compress_session_rollback_preserves_memory_injected_metadata(
    config: CursorAgentConfig,
    tmp_path: Path,
) -> None:
    """Failed /compress rollback restores agent_id and keeps memory_injected."""
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = "cli:default:compress-memory-rollback"
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        fail_on_summary_delivery=True,
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await _seed_session_with_memory_injected(
        store,
        facade,
        session_key,
        workspace=str(tmp_path),
    )
    facade._status_session_id = session_id
    row_before = await store.resolve(session_key, session_id=session_id)
    assert row_before is not None
    previous_agent_id = row_before.agent_id

    with pytest.raises(ConfigError, match="summary delivery"):
        await run_compress_session(
            store=store,
            facade=facade,
            config=config,
            session_key=session_key,
            session_id=session_id,
        )

    row_after = await store.resolve(session_key, session_id=session_id)
    assert row_after is not None
    assert row_after.agent_id == previous_agent_id
    assert row_after.metadata.get("memory_injected") is True
    assert row_after.metadata.get("last_run_id") == "compress-memory-regression-run"
    assert row_after.metadata.get("last_status") == "finished"
    assert "status" not in row_after.metadata


async def test_compress_session_summary_seed_does_not_reinject_skill_after_invocation(
    tmp_path: Path,
) -> None:
    """Summary delivery after prior skill invocation must not prepend a fresh skill block."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_compress_skill_fixture(
        _project_skills_root(workspace),
        body=_COMPRESS_TEST_SKILL_BODY,
    )
    config = _compress_skills_config(tmp_path, workspace=workspace)
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    facade = _CompressSendSpyFacade(
        scripted_replies={"default": _SUMMARY_REPLY},
        store=store,
        session_key=session_key,
        session_id=None,
    )
    session_id = await seed_session(
        store,
        facade,
        session_key,
        workspace=str(workspace),
    )
    pool = SendSpyPool(store=store, facade=facade, config=config)

    discovery_calls_before_compress = 0

    def _counting_skill_discovery(*args: object, **kwargs: object) -> object:
        nonlocal discovery_calls_before_compress
        discovery_calls_before_compress += 1
        return skill_discovery_from_config(*args, **kwargs)  # type: ignore[arg-type]

    with patch(
        "cursor_agent.cli.slash_commands.skill_discovery_from_config",
        side_effect=_counting_skill_discovery,
    ):
        await drive_repl(
            pool,
            session_key,
            store,
            config,
            facade,
            lines=(f"/{_COMPRESS_TEST_SKILL_NAME}", "/quit"),
            writer=lambda _line: None,
            auto_resume=True,
        )
        discovery_calls_after_skill = discovery_calls_before_compress
        assert discovery_calls_after_skill > 0

        facade._status_session_id = session_id
        result = await run_compress_session(
            store=store,
            facade=facade,
            config=config,
            session_key=session_key,
            session_id=session_id,
        )

    assert discovery_calls_before_compress == discovery_calls_after_skill

    assert len(pool.send_calls) == 1
    skill_send = pool.send_calls[0]["message"]
    assert isinstance(skill_send, str)
    assert format_skill_section_marker(_COMPRESS_TEST_SKILL_NAME) in skill_send
    assert _COMPRESS_TEST_SKILL_BODY in skill_send

    assert len(facade.send_calls) == 3
    summary_seed = facade.send_calls[2]
    assert summary_seed["agent_id"] == result.new_agent_id
    assert summary_seed["message"] == _SUMMARY_REPLY
    assert "## Skill:" not in summary_seed["message"]
    assert (
        format_skill_section_marker(_COMPRESS_TEST_SKILL_NAME)
        not in summary_seed["message"]
    )
    assert _COMPRESS_TEST_SKILL_BODY not in summary_seed["message"]
