"""Local-file memory loader and effective payload builder (PRD-008, ADR-010)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from cursor_agent.config.loader import CursorAgentConfig

USER_FILENAME: Final[str] = "USER.md"
MEMORY_FILENAME: Final[str] = "MEMORY.md"
TOTAL_MEMORY_BUDGET_BYTES: Final[int] = 8192
USER_MEMORY_BUDGET_BYTES: Final[int] = 4096
USER_MEMORY_SECTION_MARKER: Final[str] = "## User memory"
MEMORY_SECTION_MARKER: Final[str] = "## Memory"
# Max UTF-8 code unit length minus one — read slack so tail decode never splits a code point.
_UTF8_TAIL_SLACK_BYTES: Final[int] = 4

_DEFAULT_MEMORY_ROOT = Path.home() / ".cursor-agent"


@dataclass(frozen=True, slots=True)
class LoadedMemorySection:
    """Raw section content read from disk."""

    filename: str
    text: str
    byte_length: int
    missing: bool


@dataclass(frozen=True, slots=True)
class EffectiveMemorySection:
    """Section content after quota and truncation rules are applied."""

    filename: str
    original_text: str
    original_bytes: int
    effective_text: str
    effective_bytes: int
    budget_bytes: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class EffectiveMemoryPayload:
    """Deterministic Memory v1 payload consumed by injection and ``/memory show``."""

    user: EffectiveMemorySection
    memory: EffectiveMemorySection
    total_effective_bytes: int


class LocalMemoryStore:
    """Read ``USER.md`` and ``MEMORY.md`` from a local memory root.

    Example:
        >>> store = LocalMemoryStore(root=Path("/tmp/memory-fixture"))
        >>> payload = store.build_effective_payload()
        >>> payload.total_effective_bytes
        0
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root if root is not None else _DEFAULT_MEMORY_ROOT

    @property
    def root(self) -> Path:
        """Configured memory root directory."""
        return self._root

    def build_effective_payload(self) -> EffectiveMemoryPayload:
        """Load memory files and apply ADR-010 quota and truncation rules."""
        user_loaded = self._read_section(
            USER_FILENAME,
            max_tail_bytes=USER_MEMORY_BUDGET_BYTES,
        )
        memory_loaded = self._read_section(
            MEMORY_FILENAME,
            max_tail_bytes=TOTAL_MEMORY_BUDGET_BYTES,
        )

        user_effective = _apply_section_budget(
            filename=USER_FILENAME,
            text=user_loaded.text,
            original_bytes=user_loaded.byte_length,
            budget_bytes=USER_MEMORY_BUDGET_BYTES,
        )
        memory_budget = TOTAL_MEMORY_BUDGET_BYTES - user_effective.effective_bytes
        memory_effective = _apply_section_budget(
            filename=MEMORY_FILENAME,
            text=memory_loaded.text,
            original_bytes=memory_loaded.byte_length,
            budget_bytes=memory_budget,
        )
        total_effective_bytes = (
            user_effective.effective_bytes + memory_effective.effective_bytes
        )
        return EffectiveMemoryPayload(
            user=user_effective,
            memory=memory_effective,
            total_effective_bytes=total_effective_bytes,
        )

    def _read_section(
        self, filename: str, *, max_tail_bytes: int
    ) -> LoadedMemorySection:
        path = self._root / filename
        if not self._root.exists():
            return LoadedMemorySection(
                filename=filename,
                text="",
                byte_length=0,
                missing=True,
            )
        if not self._root.is_dir():
            raise ValueError(
                f"invalid memory root: {self._root!r} is not a directory, "
                f"expected existing directory containing UTF-8 {filename}"
            )
        if not path.is_file():
            return LoadedMemorySection(
                filename=filename,
                text="",
                byte_length=0,
                missing=True,
            )
        try:
            text, file_byte_length = _read_utf8_file_tail(path, max_tail_bytes)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"invalid memory file: {path!r} is not valid UTF-8 text, "
                f"expected UTF-8 encoded {filename}"
            ) from exc
        return LoadedMemorySection(
            filename=filename,
            text=text,
            byte_length=file_byte_length,
            missing=False,
        )


def memory_store_from_config(
    config: CursorAgentConfig,
    *,
    override_root: Path | None = None,
) -> LocalMemoryStore:
    """Build a ``LocalMemoryStore`` from config with an optional runtime override.

    ``override_root`` wins for tests and REPL injection; otherwise
    ``config.memory_root`` (``CURSOR_AGENT__MEMORY_ROOT`` / YAML) is used;
    when unset, the default ``~/.cursor-agent`` directory applies.

    Example:
        >>> from cursor_agent.config.loader import load_config
        >>> store = memory_store_from_config(load_config())
    """
    if override_root is not None:
        return LocalMemoryStore(root=override_root)
    configured_root = config.memory_root
    if configured_root is not None and configured_root.strip():
        return LocalMemoryStore(root=Path(configured_root.strip()))
    return LocalMemoryStore()


def format_memory_injection_message(
    payload: EffectiveMemoryPayload,
    user_message: str,
) -> str:
    """Prepend effective memory sections to the outgoing user turn.

    Example:
        >>> store = LocalMemoryStore(root=Path("/tmp/memory-fixture"))
        >>> message = format_memory_injection_message(
        ...     store.build_effective_payload(),
        ...     "hello",
        ... )
    """
    sections: list[str] = []
    if payload.user.effective_text:
        sections.append(f"{USER_MEMORY_SECTION_MARKER}\n{payload.user.effective_text}")
    if payload.memory.effective_text:
        sections.append(f"{MEMORY_SECTION_MARKER}\n{payload.memory.effective_text}")
    if not sections:
        return user_message
    memory_block = "\n\n".join(sections)
    return f"{memory_block}\n\n{user_message}"


def _apply_section_budget(
    *,
    filename: str,
    text: str,
    original_bytes: int,
    budget_bytes: int,
) -> EffectiveMemorySection:
    if budget_bytes <= 0 or original_bytes == 0:
        return EffectiveMemorySection(
            filename=filename,
            original_text=text,
            original_bytes=original_bytes,
            effective_text="",
            effective_bytes=0,
            budget_bytes=max(budget_bytes, 0),
            truncated=False,
        )
    if original_bytes <= budget_bytes:
        return EffectiveMemorySection(
            filename=filename,
            original_text=text,
            original_bytes=original_bytes,
            effective_text=text,
            effective_bytes=original_bytes,
            budget_bytes=budget_bytes,
            truncated=False,
        )
    effective_text = _truncate_utf8_from_end(text, budget_bytes)
    effective_bytes = len(effective_text.encode("utf-8"))
    return EffectiveMemorySection(
        filename=filename,
        original_text=text,
        original_bytes=original_bytes,
        effective_text=effective_text,
        effective_bytes=effective_bytes,
        budget_bytes=budget_bytes,
        truncated=True,
    )


def _read_utf8_file_tail(path: Path, max_tail_bytes: int) -> tuple[str, int]:
    """Read at most ``max_tail_bytes`` UTF-8 bytes from the end of ``path``.

    Returns decoded text and the on-disk file size in bytes. Only the tail is
    loaded into memory — enough for ADR-010 truncation while avoiding unbounded
    reads when a memory file is accidentally very large.

    Example:
        >>> _read_utf8_file_tail(Path("USER.md"), 4096)
        ('prefer dark mode', 18)
    """
    file_size = path.stat().st_size
    if file_size == 0:
        return "", 0

    read_size = min(file_size, max_tail_bytes + _UTF8_TAIL_SLACK_BYTES)
    with path.open("rb") as handle:
        handle.seek(file_size - read_size)
        raw = handle.read(read_size)

    if read_size == file_size:
        return raw.decode("utf-8"), file_size

    return _decode_without_split_code_point(raw), file_size


def _truncate_utf8_from_end(text: str, max_bytes: int) -> str:
    """Keep the tail of ``text`` within ``max_bytes`` UTF-8 bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated_bytes = encoded[-max_bytes:]
    return _decode_without_split_code_point(truncated_bytes)


def _decode_without_split_code_point(byte_slice: bytes) -> str:
    """Decode a byte tail, dropping a leading partial UTF-8 code point if needed."""
    for skip in range(4):
        candidate = byte_slice[skip:]
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
    raise ValueError(
        f"invalid UTF-8 tail: could not decode {byte_slice!r}, "
        "expected valid UTF-8 text fragment"
    )
