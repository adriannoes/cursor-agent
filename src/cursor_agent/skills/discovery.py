"""Bounded disk discovery for workspace and user Cursor skills (PRD-009, FR-1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import yaml

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.skills import pack_paths
from cursor_agent.skills.skill_frontmatter import (
    SKILL_FILENAME,
    frontmatter_prefix_byte_length,
    is_safe_skill_file,
    parse_yaml_frontmatter,
    read_frontmatter_text,
    skill_name_from_frontmatter,
)
from cursor_agent.utf8_io import (
    decode_without_split_code_point,
    read_utf8_file_tail,
    truncate_utf8_from_end,
)

SkillSource = Literal["project", "user"]

# WHY: SKILL_FILENAME is imported from skill_frontmatter and re-exported here
# for callers that historically used ``from cursor_agent.skills.discovery import SKILL_FILENAME``.
SKILL_CONTENT_MAX_BYTES: Final[int] = 32 * 1024
_MODULE_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SkillEntry:
    """Discovered skill metadata and bounded file content for invocation."""

    name: str
    description: str
    source: SkillSource
    path: str
    content: str


class SkillDiscovery:
    """Index of discoverable skills with project-over-user precedence.

    Example:
        >>> discovery = SkillDiscovery({})
        >>> discovery.list_skills()
        []
    """

    def __init__(self, entries: dict[str, SkillEntry]) -> None:
        self._entries = entries

    def list_skills(self) -> list[SkillEntry]:
        """Return all skills sorted alphabetically by name."""
        return sorted(self._entries.values(), key=lambda entry: entry.name)

    def get_skill(self, name: str) -> SkillEntry | None:
        """Return the exact, case-sensitive skill entry for ``name``, if present."""
        return self._entries.get(name)


def skill_discovery_from_config(
    config: CursorAgentConfig,
    *,
    override_workspace: Path | None = None,
    override_user_skills: Path | None = None,
    include_content: bool = True,
) -> SkillDiscovery:
    """Build skill discovery from config with optional test/runtime overrides.

    Project skills live under ``{workspace}/.cursor/skills/``. User skills are
    included when ``setting_sources`` contains ``"user"`` and default to
    ``~/.cursor/skills/`` unless ``override_user_skills`` is provided.

    Example:
        >>> from cursor_agent.config.loader import load_config
        >>> discovery = skill_discovery_from_config(load_config())
    """
    setting_sources = config.runtime.local.setting_sources
    workspace = (
        override_workspace
        if override_workspace is not None
        else Path(config.runtime.local.cwd).resolve()
    )
    entries: dict[str, SkillEntry] = {}

    if "user" in setting_sources:
        # WHY: pack_paths is the single source for BYO / seed destinations.
        user_root = (
            override_user_skills
            if override_user_skills is not None
            else pack_paths.user_skills_root(Path.home())
        )
        _merge_skill_entries(
            entries,
            _discover_skills_in_root(
                user_root, "user", include_content=include_content
            ),
        )

    if "project" in setting_sources:
        project_root = pack_paths.project_skills_root(workspace)
        _merge_skill_entries(
            entries,
            _discover_skills_in_root(
                project_root,
                "project",
                include_content=include_content,
            ),
        )

    return SkillDiscovery(entries)


def _merge_skill_entries(
    target: dict[str, SkillEntry],
    discovered: dict[str, SkillEntry],
) -> None:
    target.update(discovered)


def _discover_skills_in_root(
    skills_root: Path,
    source: SkillSource,
    *,
    include_content: bool,
) -> dict[str, SkillEntry]:
    if not skills_root.is_dir():
        return {}

    entries: dict[str, SkillEntry] = {}
    for skill_path in sorted(skills_root.rglob(SKILL_FILENAME)):
        if not is_safe_skill_file(skill_path, skills_root):
            continue
        try:
            entry = _load_skill_entry(
                skill_path,
                skills_root,
                source,
                include_content=include_content,
            )
        except UnicodeDecodeError as exc:
            _MODULE_LOGGER.warning(
                "skipping invalid UTF-8 skill file: path=%s reason=%s",
                skill_path,
                exc,
            )
            continue
        except (OSError, ValueError, yaml.YAMLError) as exc:
            _MODULE_LOGGER.warning(
                "skipping invalid skill file: path=%s reason=%s",
                skill_path,
                exc,
            )
            continue
        if entry.name in entries:
            _MODULE_LOGGER.warning(
                "duplicate skill name in %s source: name=%s existing=%s ignored=%s",
                source,
                entry.name,
                entries[entry.name].path,
                entry.path,
            )
            continue
        entries[entry.name] = entry
    return entries


def _load_skill_entry(
    skill_path: Path,
    skills_root: Path,
    source: SkillSource,
    *,
    include_content: bool,
) -> SkillEntry:
    directory_name = skill_path.parent.name
    frontmatter_text = read_frontmatter_text(skill_path)
    frontmatter = parse_yaml_frontmatter(frontmatter_text)

    name = skill_name_from_frontmatter(frontmatter, directory_name=directory_name)
    description = frontmatter.get("description", "").strip()
    relative_path = skill_path.relative_to(skills_root).as_posix()
    content = _read_bounded_skill_content(skill_path) if include_content else ""

    return SkillEntry(
        name=name,
        description=description,
        source=source,
        path=relative_path,
        content=content,
    )


def _read_bounded_skill_content(skill_path: Path) -> str:
    """Read SKILL.md content within ``SKILL_CONTENT_MAX_BYTES``.

    When the file exceeds the cap, YAML frontmatter is preserved at the start and
    only the body is tail-truncated so late instructions (for example markers at
    the end of the file) remain visible to the agent.
    """
    file_size = skill_path.stat().st_size
    if file_size == 0:
        return ""

    prefix_byte_length = frontmatter_prefix_byte_length(skill_path)
    if file_size <= SKILL_CONTENT_MAX_BYTES:
        text, _ = read_utf8_file_tail(skill_path, SKILL_CONTENT_MAX_BYTES)
        return truncate_utf8_from_end(text, SKILL_CONTENT_MAX_BYTES)

    with skill_path.open("rb") as handle:
        prefix_bytes = handle.read(prefix_byte_length)

    prefix_text = prefix_bytes.decode("utf-8")
    body_size = file_size - prefix_byte_length
    body_budget_bytes = SKILL_CONTENT_MAX_BYTES - len(prefix_bytes)
    if body_budget_bytes <= 0:
        return truncate_utf8_from_end(prefix_text, SKILL_CONTENT_MAX_BYTES)

    body_read_bytes = min(body_size, body_budget_bytes)
    with skill_path.open("rb") as handle:
        handle.seek(prefix_byte_length + body_size - body_read_bytes)
        body_tail_bytes = handle.read(body_read_bytes)

    body_tail = decode_without_split_code_point(body_tail_bytes)
    return truncate_utf8_from_end(
        prefix_text + body_tail,
        SKILL_CONTENT_MAX_BYTES,
    )
