"""Unit tests for CLI /skills command (PRD-009)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from cursor_agent.cli.command_router import BuiltinMatch
from cursor_agent.cli import slash_commands
from cursor_agent.cli.slash_commands import build_repl_command_router
from cursor_agent.cli.startup import session_key_for
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore
from cursor_agent.skills.discovery import SkillDiscovery

from tests.unit.cli_repl_helpers import drive_repl


def _skills_config(
    tmp_path: Path,
    *,
    workspace: Path,
    setting_sources: list[str] | None = None,
) -> CursorAgentConfig:
    """Build config with ``runtime.local.cwd`` pointed at an injectable workspace."""
    local: dict[str, object] = {"cwd": str(workspace)}
    if setting_sources is not None:
        local["setting_sources"] = setting_sources
    return load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={"runtime": {"local": local}},
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
    body: str = "Skill body content.",
    name: str | None = None,
    description: str | None = None,
) -> Path:
    """Create ``relative_dir/SKILL.md`` with YAML frontmatter under a skills root."""
    skill_dir = skills_root / relative_dir
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    frontmatter_lines = ["---"]
    if name is not None:
        frontmatter_lines.append(f"name: {name}")
    if description is not None:
        frontmatter_lines.append(f"description: {description}")
    frontmatter_lines.append("---")
    skill_path.write_text(
        "\n".join(frontmatter_lines) + f"\n\n{body}",
        encoding="utf-8",
    )
    return skill_path


async def _drive_repl_skills(
    *,
    config: CursorAgentConfig,
    tmp_path: Path,
    lines: tuple[str, ...],
    writer: Callable[[str], None],
    user_skills_root: Path | None = None,
    auto_resume: bool = False,
) -> None:
    """Drive the REPL for /skills tests with optional user-root injection."""
    if user_skills_root is not None:
        user_skills_root.mkdir(parents=True, exist_ok=True)

    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    await store.initialize()
    session_key = session_key_for(config)
    pool = SessionAgentPool(store=store, facade=facade, config=config)

    await drive_repl(
        pool,
        session_key,
        store,
        config,
        facade,
        lines=lines,
        writer=writer,
        auto_resume=auto_resume,
        user_skills_root=user_skills_root,
    )


def test_build_repl_command_router_registers_skills_handler() -> None:
    """/skills registers as a built-in command for CLI listing."""
    router = build_repl_command_router()
    resolved = router.resolve("/skills")
    assert isinstance(resolved, BuiltinMatch)
    assert resolved.canonical_name == "skills"
    assert resolved.arg is None


async def test_skills_lists_project_and_user_sources(
    tmp_path: Path,
) -> None:
    """/skills shows name, description, source label, and relative path per source."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "fake-home" / ".cursor" / "skills"

    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "alpha-skill",
        name="alpha-skill",
        description="Alpha project skill.",
        body="Alpha project body.",
    )
    _write_skill_md(
        user_skills_root,
        "beta-skill",
        name="beta-skill",
        description="Beta user skill.",
        body="Beta user body.",
    )

    config = _skills_config(tmp_path, workspace=workspace)
    output: list[str] = []

    await _drive_repl_skills(
        config=config,
        tmp_path=tmp_path,
        lines=("/skills", "/quit"),
        writer=output.append,
        user_skills_root=user_skills_root,
    )

    combined = "\n".join(output)
    assert "alpha-skill" in combined
    assert "Alpha project skill." in combined
    assert "alpha-skill/SKILL.md" in combined
    assert "beta-skill" in combined
    assert "Beta user skill." in combined
    assert "beta-skill/SKILL.md" in combined
    assert "project" in combined.lower()
    assert "user" in combined.lower()
    assert "Command not available yet" not in combined


async def test_skills_collision_shows_only_project_winner(
    tmp_path: Path,
) -> None:
    """When project and user share a name, /skills lists only the project winner."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "fake-home" / ".cursor" / "skills"

    project_root = _project_skills_root(workspace)
    _write_skill_md(
        project_root,
        "shared-name",
        name="shared-skill",
        description="Project copy wins.",
        body="Project skill body.",
    )
    _write_skill_md(
        user_skills_root,
        "shared-name",
        name="shared-skill",
        description="User copy loses.",
        body="User skill body.",
    )

    config = _skills_config(tmp_path, workspace=workspace)
    output: list[str] = []

    await _drive_repl_skills(
        config=config,
        tmp_path=tmp_path,
        lines=("/skills", "/quit"),
        writer=output.append,
        user_skills_root=user_skills_root,
    )

    combined = "\n".join(output)
    assert combined.lower().count("shared-skill") == 1
    assert "Project copy wins." in combined
    assert "User copy loses." not in combined
    assert "User skill body." not in combined
    assert "project" in combined.lower()


async def test_skills_empty_workspace_shows_clear_empty_state(
    tmp_path: Path,
) -> None:
    """/skills with no discovered skills reports a clear empty state, not an error."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_skills_root = tmp_path / "fake-home" / ".cursor" / "skills"
    user_skills_root.mkdir(parents=True, exist_ok=True)

    config = _skills_config(tmp_path, workspace=workspace)
    output: list[str] = []

    await _drive_repl_skills(
        config=config,
        tmp_path=tmp_path,
        lines=("/skills", "/quit"),
        writer=output.append,
        user_skills_root=user_skills_root,
    )

    combined = "\n".join(output)
    lowered = combined.lower()
    assert "command not available yet" not in lowered
    assert "error:" not in lowered
    assert "traceback" not in lowered
    assert "no skill" in lowered or "0 skill" in lowered or "none" in lowered


async def test_help_includes_skills_command(tmp_path: Path) -> None:
    """/help documents /skills once the built-in command ships."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _skills_config(tmp_path, workspace=workspace)
    output: list[str] = []

    await _drive_repl_skills(
        config=config,
        tmp_path=tmp_path,
        lines=("/help", "/quit"),
        writer=output.append,
    )

    help_text = "\n".join(output)
    assert "/skills" in help_text
    assert "Command not available yet" not in help_text


def test_skill_resolver_caches_discovery_per_repl_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown slash resolution should not rescan the skills tree every time."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _skills_config(tmp_path, workspace=workspace)
    calls = 0

    def fake_discovery_from_config(
        config: CursorAgentConfig,
        *,
        override_workspace: Path | None = None,
        override_user_skills: Path | None = None,
        include_content: bool = True,
    ) -> SkillDiscovery:
        nonlocal calls
        _ = config, override_workspace, override_user_skills, include_content
        calls += 1
        return SkillDiscovery({})

    monkeypatch.setattr(
        slash_commands,
        "skill_discovery_from_config",
        fake_discovery_from_config,
    )

    resolver = slash_commands._make_skill_resolver(
        config,
        user_skills_root=tmp_path / "user-skills",
    )

    assert resolver("unknown-one") is None
    assert resolver("unknown-two") is None
    assert calls == 1
