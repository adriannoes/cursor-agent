"""Rich-backed display adapter for CLI streaming (PRD-004)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.text import Text

from cursor_agent.memory import (
    TOTAL_MEMORY_BUDGET_BYTES,
    EffectiveMemoryPayload,
    EffectiveMemorySection,
)
from cursor_agent.sdk_facade import StreamCallbacks
from cursor_agent.skills.discovery import SkillEntry

DISPLAY_MEMORY_ROOT = "~/.cursor-agent/"
_EMPTY_CONTENT_LABEL = "(empty)"


def _format_tool_badge(tool_name: str, state: str) -> Text:
    """Return a Rich text badge that omits tool args and payloads."""
    state_style = "green" if state == "done" else "yellow"
    return Text.assemble(
        ("[tool]", "cyan"),
        f" {tool_name} ",
        (state, state_style),
    )


def _format_memory_section_block(
    section: EffectiveMemorySection,
    *,
    missing: bool,
) -> list[str]:
    """Format one memory section for ``/memory show`` output."""
    display_path = f"{DISPLAY_MEMORY_ROOT}{section.filename}"
    status = "missing" if missing else "present"
    lines = [
        f"--- {section.filename} ({display_path}) ---",
        f"Status: {status}",
        f"Quota: {section.budget_bytes} bytes",
        f"Effective: {section.effective_bytes} bytes",
    ]
    if section.truncated:
        lines.append(
            f"Truncated: yes (original {section.original_bytes} bytes, "
            f"kept tail within quota)"
        )
    else:
        lines.append("Truncated: no")
    content = section.effective_text if section.effective_text else _EMPTY_CONTENT_LABEL
    lines.append("Content:")
    lines.append(content)
    return lines


def format_memory_show_output(
    payload: EffectiveMemoryPayload,
    *,
    user_missing: bool,
    memory_missing: bool,
) -> str:
    """Format the effective Memory v1 payload for operator inspection.

    Example:
        >>> from cursor_agent.memory import LocalMemoryStore
        >>> store = LocalMemoryStore(root=Path("/tmp/memory"))
        >>> print(format_memory_show_output(
        ...     store.build_effective_payload(),
        ...     user_missing=True,
        ...     memory_missing=True,
        ... ))
    """
    lines = [
        "Memory effective payload",
        "",
        *_format_memory_section_block(payload.user, missing=user_missing),
        "",
        *_format_memory_section_block(payload.memory, missing=memory_missing),
        "",
        (
            "Total effective: "
            f"{payload.total_effective_bytes} / {TOTAL_MEMORY_BUDGET_BYTES} bytes"
        ),
    ]
    return "\n".join(lines)


def format_skills_list_output(skills: list[SkillEntry]) -> str:
    """Format discovered skills for ``/skills`` terminal output.

    Example:
        >>> from cursor_agent.skills.discovery import SkillEntry
        >>> entry = SkillEntry(
        ...     name="canvas",
        ...     description="Canvas workflows",
        ...     source="project",
        ...     path="canvas/SKILL.md",
        ...     content="",
        ... )
        >>> print(format_skills_list_output([entry]))
    """
    if not skills:
        return "No skills discovered in the configured workspace and user paths."

    lines = [f"Skills ({len(skills)}):", ""]
    for skill in skills:
        description = skill.description if skill.description else "(none)"
        lines.extend(
            [
                skill.name,
                f"  Description: {description}",
                f"  Source: {skill.source}",
                f"  Path: {skill.path}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


class RichDisplay:
    """Display boundary for assistant streaming and tool badges.

    Keeps Rich ``Console`` usage inside this module so ``repl_session.py`` does not
    import Rich directly. ``stream_writer`` receives inline assistant deltas;
    ``status_writer`` receives line-oriented status such as tool badge updates
    (PRD-003 two-sink contract).

    Example:
        display = RichDisplay(stream_writer=print, status_writer=print)
        callbacks = display.build_stream_callbacks()
    """

    def __init__(
        self,
        *,
        stream_writer: Callable[[str], None],
        status_writer: Callable[[str], None],
        console: Console | None = None,
    ) -> None:
        self._stream_writer = stream_writer
        self._status_writer = status_writer
        self._console = console if console is not None else Console()
        self._last_tool_badge: tuple[str, str] | None = None

    def build_stream_callbacks(self) -> StreamCallbacks:
        """Build SDK stream callbacks wired to this display boundary."""
        display = self

        async def on_assistant_text(delta: str) -> None:
            display._stream_writer(delta)

        async def on_tool_start(tool_name: str, _args: dict[str, Any]) -> None:
            display._write_tool_badge(tool_name, "running")

        async def on_tool_end(tool_name: str, _payload: dict[str, Any]) -> None:
            display._write_tool_badge(tool_name, "done")

        return StreamCallbacks(
            on_assistant_text=on_assistant_text,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
        )

    def _write_tool_badge(self, tool_name: str, state: str) -> None:
        """Render a Rich badge and forward the captured line to the status sink."""
        badge_key = (tool_name, state)
        if self._last_tool_badge == badge_key:
            return
        self._last_tool_badge = badge_key
        with self._console.capture() as capture:
            self._console.print(_format_tool_badge(tool_name, state), end="")
        self._status_writer(capture.get())
