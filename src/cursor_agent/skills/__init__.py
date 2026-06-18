"""Skill discovery and resolution for cursor-agent (PRD-009)."""

from cursor_agent.skills.discovery import (
    SKILL_CONTENT_MAX_BYTES,
    SkillDiscovery,
    SkillEntry,
    skill_discovery_from_config,
)
from cursor_agent.skills.injection import (
    format_skill_injection_message,
    format_skill_section_marker,
)

__all__ = [
    "SKILL_CONTENT_MAX_BYTES",
    "SkillDiscovery",
    "SkillEntry",
    "format_skill_injection_message",
    "format_skill_section_marker",
    "skill_discovery_from_config",
]
