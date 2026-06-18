"""Unit tests for skill content injection through the REPL send path (PRD-009, FR-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.facade_logging import LogContext
from cursor_agent.memory import LocalMemoryStore
from cursor_agent.memory.store import (
    MEMORY_SECTION_MARKER,
    USER_MEMORY_SECTION_MARKER,
    format_memory_injection_message,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, StreamCallbacks
from cursor_agent.skills.discovery import SkillEntry, skill_discovery_from_config
from cursor_agent.skills.injection import format_skill_injection_message
from cursor_agent.sessions.store import SessionStore

from tests.unit.cli_repl_helpers import SendSpyPool, drive_repl, seed_session

_USER_FILENAME = "USER.md"
_MEMORY_FILENAME = "MEMORY.md"


def _skills_config(tmp_path: Path, *, workspace: Path) -> CursorAgentConfig:
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


def _write_skill_md(
    skills_root: Path,
    relative_dir: str,
    *,
    body: str,
    name: str,
    description: str = "Test skill.",
) -> None:
    """Create ``relative_dir/SKILL.md`` with YAML frontmatter under a skills root."""
    skill_dir = skills_root / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


def _write_memory_files(
    memory_root: Path,
    *,
    user_text: str,
    memory_text: str,
) -> None:
    """Write USER.md and MEMORY.md under a temporary memory root."""
    memory_root.mkdir(parents=True, exist_ok=True)
    (memory_root / _USER_FILENAME).write_text(user_text, encoding="utf-8")
    (memory_root / _MEMORY_FILENAME).write_text(memory_text, encoding="utf-8")


def _canvas_entry(*, body: str = "Use the canvas skill playbook.") -> SkillEntry:
    """Return a deterministic canvas skill entry for builder assertions."""
    return SkillEntry(
        name="canvas",
        description="Canvas workflows",
        source="project",
        path="canvas/SKILL.md",
        content=body,
    )


def _expected_skill_message(
    *,
    skill_name: str,
    skill_body: str,
    arg: str | None = None,
) -> str:
    """Build the locked skill injection message shape used in production."""
    base = f"## Skill: {skill_name}\n{skill_body}"
    if arg is None:
        return base
    return f"{base}\n\n{arg}"


class SendCapturingFacade(FakeSdkFacade):
    """FakeSdkFacade that records send keyword arguments."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.send_calls: list[dict[str, object]] = []

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: LogContext | None = None,
    ) -> RunResult:
        """Record send parameters and delegate to the parent fake."""
        self.send_calls.append(
            {
                "agent_id": agent_id,
                "message": message,
                "callbacks": callbacks,
                "log_context": log_context,
            }
        )
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,
        )


def test_format_skill_injection_message_includes_marker_and_body() -> None:
    """Skill builder emits the locked ``## Skill:`` marker and skill body."""
    entry = _canvas_entry()
    message = format_skill_injection_message(entry)

    assert message == _expected_skill_message(
        skill_name="canvas",
        skill_body="Use the canvas skill playbook.",
    )
    assert "## Skill: canvas" in message


def test_format_skill_injection_message_appends_optional_args_after_body() -> None:
    """Optional args after the skill name are appended after the skill body."""
    entry = _canvas_entry()
    message = format_skill_injection_message(entry, "draft the layout")

    assert message == _expected_skill_message(
        skill_name="canvas",
        skill_body="Use the canvas skill playbook.",
        arg="draft the layout",
    )
    assert message.endswith("draft the layout")
    assert message.index("Use the canvas skill playbook.") < message.index(
        "draft the layout"
    )


def _discovered_canvas_entry(
    config: CursorAgentConfig,
    workspace: Path,
) -> SkillEntry:
    """Return the discovered canvas skill entry for an injectable workspace."""
    discovery = skill_discovery_from_config(
        config,
        override_workspace=workspace,
    )
    entry = discovery.get_skill("canvas")
    assert entry is not None
    return entry


@pytest.mark.asyncio
async def test_skill_invocation_sends_composed_message_through_pool(
    tmp_path: Path,
) -> None:
    """``/<skill>`` delivers composed skill content to pool.send, not the slash line."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_body = "Use the canvas skill playbook."
    _write_skill_md(
        _project_skills_root(workspace),
        "canvas",
        name="canvas",
        body=skill_body,
    )
    config = _skills_config(tmp_path, workspace=workspace)
    entry = _discovered_canvas_entry(config, workspace)
    expected = format_skill_injection_message(entry)

    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    session_id = await seed_session(
        store, facade, session_key, workspace=str(workspace)
    )
    pool = SendSpyPool(store=store, facade=facade, config=config)

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=("/canvas", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
    )

    assert len(pool.send_calls) == 1
    assert pool.send_calls[0]["message"] == expected
    assert "## Skill: canvas" in pool.send_calls[0]["message"]
    assert skill_body in pool.send_calls[0]["message"]
    assert pool.send_calls[0]["session_id"] == session_id
    assert pool.send_calls[0]["message"] != "/canvas"


@pytest.mark.asyncio
async def test_skill_invocation_with_args_appends_args_after_skill_body(
    tmp_path: Path,
) -> None:
    """Optional args after the skill name appear after the skill body in pool.send."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_body = "Use the canvas skill playbook."
    user_arg = "draft the layout"
    _write_skill_md(
        _project_skills_root(workspace),
        "canvas",
        name="canvas",
        body=skill_body,
    )
    config = _skills_config(tmp_path, workspace=workspace)
    entry = _discovered_canvas_entry(config, workspace)
    expected = format_skill_injection_message(entry, user_arg)

    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = SendSpyPool(store=store, facade=facade, config=config)

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=(f"/canvas {user_arg}", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
    )

    assert len(pool.send_calls) == 1
    assert pool.send_calls[0]["message"] == expected
    assert pool.send_calls[0]["message"].endswith(user_arg)
    assert pool.send_calls[0]["message"].index(skill_body) < pool.send_calls[0][
        "message"
    ].index(user_arg)


@pytest.mark.asyncio
async def test_first_turn_skill_invocation_prepends_memory_before_skill_block(
    tmp_path: Path,
) -> None:
    """On the first turn with active memory, memory blocks precede ``## Skill:`` and args."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_body = "Use the canvas skill playbook."
    user_arg = "draft the layout"
    _write_skill_md(
        _project_skills_root(workspace),
        "canvas",
        name="canvas",
        body=skill_body,
    )
    config = _skills_config(tmp_path, workspace=workspace)
    entry = _discovered_canvas_entry(config, workspace)

    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv and pytest"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    facade = SendCapturingFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = SessionAgentPool(
        store=store,
        facade=facade,
        config=config,
        memory_store=LocalMemoryStore(root=memory_root),
    )

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=(f"/canvas {user_arg}", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
        memory_root=memory_root,
    )

    skill_message = format_skill_injection_message(entry, user_arg)
    memory_store = LocalMemoryStore(root=memory_root)
    expected = format_memory_injection_message(
        memory_store.build_effective_payload(),
        skill_message,
    )
    assert len(facade.send_calls) == 1
    sent_message = facade.send_calls[0]["message"]
    assert sent_message == expected
    assert sent_message.index(USER_MEMORY_SECTION_MARKER) < sent_message.index(
        MEMORY_SECTION_MARKER
    )
    assert sent_message.index(MEMORY_SECTION_MARKER) < sent_message.index(
        "## Skill: canvas"
    )
    assert sent_message.index("## Skill: canvas") < sent_message.index(skill_body)
    assert sent_message.index(skill_body) < sent_message.index(user_arg)


@pytest.mark.asyncio
async def test_skill_invocation_stores_composed_message_for_retry(
    tmp_path: Path,
) -> None:
    """``/retry`` after a skill invocation resends the composed skill payload."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    skill_body = "Use the canvas skill playbook."
    user_arg = "draft the layout"
    _write_skill_md(
        _project_skills_root(workspace),
        "canvas",
        name="canvas",
        body=skill_body,
    )
    config = _skills_config(tmp_path, workspace=workspace)
    entry = _discovered_canvas_entry(config, workspace)
    composed = format_skill_injection_message(entry, user_arg)

    facade = FakeSdkFacade(scripted_replies={"default": "ok"})
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    await seed_session(store, facade, session_key, workspace=str(workspace))
    pool = SendSpyPool(store=store, facade=facade, config=config)

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=(f"/canvas {user_arg}", "/retry", "/quit"),
        writer=lambda _line: None,
        auto_resume=True,
    )

    assert len(pool.send_calls) == 2
    assert pool.send_calls[0]["message"] == composed
    assert pool.send_calls[1]["message"] == composed
    assert pool.send_calls[1]["message"] != f"/canvas {user_arg}"
