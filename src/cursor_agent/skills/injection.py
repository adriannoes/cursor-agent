"""Compose skill content for REPL injection before pool.send (PRD-009, FR-2)."""

from __future__ import annotations

from cursor_agent.skills.discovery import SkillEntry


def format_skill_section_marker(skill_name: str) -> str:
    """Return the locked skill injection section header for ``skill_name``.

    Example:
        >>> format_skill_section_marker("canvas")
        '## Skill: canvas'
    """
    return f"## Skill: {skill_name}"


def format_skill_injection_message(
    entry: SkillEntry,
    arg: str | None = None,
) -> str:
    """Build the outgoing user turn for a resolved skill invocation.

    The skill marker and body are always included. Optional user args that
    followed the slash command are appended after the skill body.

    Example:
        >>> entry = SkillEntry(
        ...     name="canvas",
        ...     description="",
        ...     source="project",
        ...     path="canvas/SKILL.md",
        ...     content="Use the canvas playbook.",
        ... )
        >>> format_skill_injection_message(entry, "draft layout")
        '## Skill: canvas\\nUse the canvas playbook.\\n\\ndraft layout'
    """
    message = f"{format_skill_section_marker(entry.name)}\n{entry.content}"
    if arg is None:
        return message
    return f"{message}\n\n{arg}"
