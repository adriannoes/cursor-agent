"""Unit tests for CommandRouter skill precedence (PRD-009 FR-3, ADR-013)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from cursor_agent.cli.command_router import (
    BuiltinMatch,
    CommandRouter,
    SkillMatch,
    UnknownSlashCommand,
)

SkillSource = Literal["project", "user"]


@dataclass(frozen=True)
class _FakeSkillEntry:
    """Minimal skill record for router tests before discovery wiring lands."""

    name: str
    content: str
    description: str = ""
    source: SkillSource = "project"
    path: str = "canvas/SKILL.md"


SkillResolver = Callable[[str], _FakeSkillEntry | None]


def _canvas_skill() -> _FakeSkillEntry:
    """Return a deterministic canvas skill entry."""
    return _FakeSkillEntry(
        name="canvas",
        content="Use the canvas skill playbook.",
        description="Canvas workflows",
        path="canvas/SKILL.md",
    )


def _help_skill() -> _FakeSkillEntry:
    """Return a skill that collides with the reserved built-in name ``help``."""
    return _FakeSkillEntry(
        name="help",
        content="Custom help skill body.",
        description="Shadow help",
        path="help/SKILL.md",
    )


def _skills_list_skill() -> _FakeSkillEntry:
    """Return a skill that collides with the reserved built-in name ``skills``."""
    return _FakeSkillEntry(
        name="skills",
        content="Custom skills listing playbook.",
        description="Shadow skills",
        path="skills/SKILL.md",
    )


def _resolver_for(*entries: _FakeSkillEntry) -> SkillResolver:
    """Build a name-indexed resolver from fake skill entries."""
    by_name = {entry.name: entry for entry in entries}

    def resolve_skill(name: str) -> _FakeSkillEntry | None:
        return by_name.get(name)

    return resolve_skill


def _router_with_skills(skill_resolver: SkillResolver) -> CommandRouter:
    """Create a router with an injectable skill resolver."""
    return CommandRouter(skill_resolver=skill_resolver)


def test_help_builtin_wins_over_same_named_skill_when_handler_registered() -> None:
    """ADR-013: registered ``/help`` beats a skill also named ``help``."""
    help_handler = object()
    router = _router_with_skills(_resolver_for(_help_skill()))
    router.register("help", help_handler)  # type: ignore[arg-type]

    result = router.resolve("/help")

    assert isinstance(result, BuiltinMatch)
    assert result.canonical_name == "help"
    assert result.handler is help_handler


def test_help_reserved_builtin_wins_without_handler_over_same_named_skill() -> None:
    """ADR-013: reserved ``help`` never resolves as a skill even if discovery finds one."""
    router = _router_with_skills(_resolver_for(_help_skill()))

    result = router.resolve("/help")

    assert isinstance(result, UnknownSlashCommand)
    assert "not available" in result.message.lower()


def test_skills_builtin_wins_over_same_named_skill_when_handler_registered() -> None:
    """ADR-013: registered ``/skills`` beats a skill also named ``skills``."""
    skills_handler = object()
    router = _router_with_skills(_resolver_for(_skills_list_skill()))
    router.register("skills", skills_handler)  # type: ignore[arg-type]

    result = router.resolve("/skills")

    assert isinstance(result, BuiltinMatch)
    assert result.canonical_name == "skills"
    assert result.handler is skills_handler


def test_canvas_resolves_to_skill_match_when_present() -> None:
    """Non-reserved slash names with a discovery hit return ``SkillMatch``."""
    canvas = _canvas_skill()
    router = _router_with_skills(_resolver_for(canvas))

    result = router.resolve("/canvas")

    assert isinstance(result, SkillMatch)
    assert result.skill_name == "canvas"
    assert result.arg is None
    assert result.entry is canvas


def test_canvas_skill_match_preserves_trailing_arguments() -> None:
    """Skill resolution keeps optional args after the skill name."""
    canvas = _canvas_skill()
    router = _router_with_skills(_resolver_for(canvas))

    result = router.resolve("/canvas draft the layout")

    assert isinstance(result, SkillMatch)
    assert result.skill_name == "canvas"
    assert result.arg == "draft the layout"
    assert result.entry is canvas


def test_unknown_slash_without_skill_falls_through_as_free_text() -> None:
    """ADR-013: unknown slash with no skill match returns ``None`` for agent free text."""
    router = _router_with_skills(_resolver_for())

    assert router.resolve("/unknown") is None


def test_unknown_slash_with_args_falls_through_as_free_text() -> None:
    """Free-text fallthrough preserves the full slash-prefixed line for the REPL send path."""
    router = _router_with_skills(_resolver_for())

    assert router.resolve("/unknown extra args") is None


def test_skill_match_does_not_raise_runtime_error() -> None:
    """Regression: resolving a real skill must return SkillMatch, not raise."""
    router = _router_with_skills(_resolver_for(_canvas_skill()))

    result = router.resolve("/canvas")

    assert isinstance(result, SkillMatch)
    assert result.skill_name == "canvas"


def test_non_slash_line_still_returns_none() -> None:
    """Plain user text bypasses slash resolution unchanged."""
    router = _router_with_skills(_resolver_for(_canvas_skill()))

    assert router.resolve("hello agent") is None
