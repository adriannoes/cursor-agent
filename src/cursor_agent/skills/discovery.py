"""Bounded disk discovery for workspace and user Cursor skills (PRD-009, FR-1)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.utf8_io import (
    decode_without_split_code_point,
    read_utf8_file_tail,
    truncate_utf8_from_end,
)

SkillSource = Literal["project", "user"]

SKILL_FILENAME: Final[str] = "SKILL.md"
SKILL_CONTENT_MAX_BYTES: Final[int] = 32 * 1024
_FRONTMATTER_MAX_BYTES: Final[int] = 8192
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
        user_root = (
            override_user_skills
            if override_user_skills is not None
            else Path.home() / ".cursor" / "skills"
        )
        _merge_skill_entries(
            entries,
            _discover_skills_in_root(
                user_root, "user", include_content=include_content
            ),
        )

    if "project" in setting_sources:
        project_root = workspace / ".cursor" / "skills"
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
        if not _is_safe_skill_file(skill_path, skills_root):
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


def _is_safe_skill_file(skill_path: Path, skills_root: Path) -> bool:
    """Return True only for regular SKILL.md files contained by the skills root."""
    if skill_path.is_symlink():
        return False
    try:
        resolved_root = skills_root.resolve(strict=True)
        resolved_skill_path = skill_path.resolve(strict=True)
    except OSError:
        return False
    return resolved_skill_path.is_file() and resolved_skill_path.is_relative_to(
        resolved_root
    )


def _load_skill_entry(
    skill_path: Path,
    skills_root: Path,
    source: SkillSource,
    *,
    include_content: bool,
) -> SkillEntry:
    directory_name = skill_path.parent.name
    frontmatter_text = _read_frontmatter_text(skill_path)
    frontmatter = _parse_yaml_frontmatter(frontmatter_text)

    name = frontmatter.get("name", "").strip() or directory_name
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

    prefix_byte_length = _frontmatter_prefix_byte_length(skill_path)
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


def _frontmatter_prefix_byte_length(skill_path: Path) -> int:
    """Return the UTF-8 byte length of YAML frontmatter plus its body separator."""
    with skill_path.open("rb") as handle:
        head_bytes = handle.read(_FRONTMATTER_MAX_BYTES)

    if not head_bytes.startswith(b"---"):
        return 0

    closing_marker = b"\n---\n"
    closing_index = head_bytes.find(closing_marker, 3)
    if closing_index == -1:
        return 0

    prefix_end = closing_index + len(closing_marker)
    while prefix_end < len(head_bytes) and head_bytes[prefix_end : prefix_end + 1] in {
        b"\n",
        b"\r",
    }:
        prefix_end += 1
    return prefix_end


def _read_frontmatter_text(path: Path) -> str:
    """Read and decode only the YAML frontmatter block, if present."""
    prefix_byte_length = _frontmatter_prefix_byte_length(path)
    if prefix_byte_length == 0:
        return ""
    with path.open("rb") as handle:
        raw = handle.read(prefix_byte_length)
    return raw.decode("utf-8")


def _parse_yaml_frontmatter(text: str) -> dict[str, str]:
    """Parse supported string fields from YAML frontmatter."""
    if not text.startswith("---"):
        return {}

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    closing_index = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        ),
        None,
    )
    if closing_index is None:
        return {}

    loaded = yaml.safe_load("\n".join(lines[1:closing_index]))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"invalid frontmatter: received {loaded!r}, expected mapping"
        raise ValueError(msg)
    return _string_frontmatter_fields(loaded)


def _string_frontmatter_fields(frontmatter: dict[Any, Any]) -> dict[str, str]:
    """Return normalized string-only frontmatter fields used by skills."""
    fields: dict[str, str] = {}
    for key in ("name", "description"):
        value = frontmatter.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            msg = (
                f"invalid frontmatter field {key!r}: received {value!r}, "
                "expected string"
            )
            raise ValueError(msg)
        fields[key] = value
    return fields
