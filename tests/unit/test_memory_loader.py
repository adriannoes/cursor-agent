"""Unit tests for Memory v1 local loader and effective payload (PRD-008, ADR-010)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config.loader import load_config
from cursor_agent.memory import (
    MEMORY_SECTION_MARKER,
    TOTAL_MEMORY_BUDGET_BYTES,
    USER_MEMORY_BUDGET_BYTES,
    USER_MEMORY_SECTION_MARKER,
    EffectiveMemoryPayload,
    LocalMemoryStore,
    format_memory_injection_message,
    memory_store_from_config,
)

_USER_FILENAME = "USER.md"
_MEMORY_FILENAME = "MEMORY.md"


def _write_bytes(path: Path, byte_count: int, fill: str = "a") -> None:
    """Write exactly ``byte_count`` UTF-8 bytes using a single-byte fill character."""
    if len(fill.encode("utf-8")) != 1:
        raise ValueError(
            f"fill must be a single UTF-8 byte character, received {fill!r}"
        )
    path.write_text(fill * byte_count, encoding="utf-8")


def test_missing_both_files_returns_empty_sections(tmp_path: Path) -> None:
    """FR-10: absent USER.md and MEMORY.md are treated as empty without error."""
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_text == ""
    assert payload.memory.effective_text == ""
    assert payload.user.effective_bytes == 0
    assert payload.memory.effective_bytes == 0
    assert payload.total_effective_bytes == 0


def test_missing_memory_root_returns_empty_sections(tmp_path: Path) -> None:
    """FR-10: a missing memory root is equivalent to both files being absent."""
    missing_root = tmp_path / "missing-memory-root"
    store = LocalMemoryStore(root=missing_root)
    payload = store.build_effective_payload()

    assert payload.user.effective_text == ""
    assert payload.memory.effective_text == ""
    assert payload.total_effective_bytes == 0


def test_missing_memory_file_returns_empty_memory_section(tmp_path: Path) -> None:
    """FR-10: absent MEMORY.md yields an empty memory section."""
    (tmp_path / _USER_FILENAME).write_text("prefer dark mode", encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_text == "prefer dark mode"
    assert payload.memory.effective_text == ""
    assert payload.memory.effective_bytes == 0


def test_missing_user_file_returns_empty_user_section(tmp_path: Path) -> None:
    """FR-10: absent USER.md yields an empty user section."""
    (tmp_path / _MEMORY_FILENAME).write_text("project uses uv", encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_text == ""
    assert payload.user.effective_bytes == 0
    assert payload.memory.effective_text == "project uses uv"


def test_empty_memory_files_return_zero_effective_bytes(tmp_path: Path) -> None:
    """Empty files on disk produce empty effective sections."""
    (tmp_path / _USER_FILENAME).write_text("", encoding="utf-8")
    (tmp_path / _MEMORY_FILENAME).write_text("", encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_text == ""
    assert payload.memory.effective_text == ""
    assert payload.total_effective_bytes == 0


def test_loader_never_reads_real_home_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected memory root isolates tests from ~/.cursor-agent."""
    (tmp_path / _USER_FILENAME).write_text("only-in-test-root", encoding="utf-8")
    monkeypatch.setattr(
        Path,
        "home",
        classmethod(lambda cls: tmp_path / "must-not-be-used"),
    )

    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_text == "only-in-test-root"
    assert not (tmp_path / "must-not-be-used").exists()


def test_exact_eight_kb_payload_uses_full_budget(tmp_path: Path) -> None:
    """ADR-010: 4 KB USER plus 4 KB MEMORY fills the 8 KB total budget."""
    _write_bytes(tmp_path / _USER_FILENAME, USER_MEMORY_BUDGET_BYTES, fill="u")
    _write_bytes(
        tmp_path / _MEMORY_FILENAME,
        TOTAL_MEMORY_BUDGET_BYTES - USER_MEMORY_BUDGET_BYTES,
        fill="m",
    )
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_bytes == USER_MEMORY_BUDGET_BYTES
    assert (
        payload.memory.effective_bytes
        == TOTAL_MEMORY_BUDGET_BYTES - USER_MEMORY_BUDGET_BYTES
    )
    assert payload.total_effective_bytes == TOTAL_MEMORY_BUDGET_BYTES
    assert payload.user.truncated is False
    assert payload.memory.truncated is False


def test_user_priority_receives_four_kb_before_memory(tmp_path: Path) -> None:
    """ADR-010: USER.md is allocated up to 4 KB before MEMORY.md."""
    _write_bytes(tmp_path / _USER_FILENAME, USER_MEMORY_BUDGET_BYTES, fill="u")
    _write_bytes(tmp_path / _MEMORY_FILENAME, 100, fill="m")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.effective_bytes == USER_MEMORY_BUDGET_BYTES
    assert payload.memory.effective_bytes == 100
    assert (
        payload.memory.budget_bytes
        == TOTAL_MEMORY_BUDGET_BYTES - USER_MEMORY_BUDGET_BYTES
    )


def test_oversized_user_truncates_from_end_preserving_tail(tmp_path: Path) -> None:
    """ADR-010: oversized USER.md keeps the end of the file within its quota."""
    tail = "USER_TAIL_MARKER"
    oversized = ("u" * 5000) + tail
    (tmp_path / _USER_FILENAME).write_text(oversized, encoding="utf-8")
    (tmp_path / _MEMORY_FILENAME).write_text("memory", encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.truncated is True
    assert payload.user.effective_bytes <= USER_MEMORY_BUDGET_BYTES
    assert payload.user.effective_text.endswith(tail)


def test_oversized_memory_truncates_from_end_preserving_tail(tmp_path: Path) -> None:
    """ADR-010: oversized MEMORY.md keeps the end within the remaining budget."""
    (tmp_path / _USER_FILENAME).write_text("user", encoding="utf-8")
    user_bytes = len("user".encode("utf-8"))
    memory_budget = TOTAL_MEMORY_BUDGET_BYTES - user_bytes
    tail = "MEMORY_TAIL_MARKER"
    oversized = ("m" * (memory_budget + 2000)) + tail
    (tmp_path / _MEMORY_FILENAME).write_text(oversized, encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.memory.truncated is True
    assert payload.memory.effective_bytes <= memory_budget
    assert payload.memory.effective_text.endswith(tail)


def test_both_files_oversized_apply_independent_section_caps(tmp_path: Path) -> None:
    """ADR-010: both sections truncate independently under the shared 8 KB cap."""
    user_tail = "USER_END"
    memory_tail = "MEMORY_END"
    (tmp_path / _USER_FILENAME).write_text(("u" * 6000) + user_tail, encoding="utf-8")
    (tmp_path / _MEMORY_FILENAME).write_text(
        ("m" * 6000) + memory_tail, encoding="utf-8"
    )
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.truncated is True
    assert payload.memory.truncated is True
    assert payload.user.effective_bytes == USER_MEMORY_BUDGET_BYTES
    assert (
        payload.memory.effective_bytes
        == TOTAL_MEMORY_BUDGET_BYTES - USER_MEMORY_BUDGET_BYTES
    )
    assert payload.total_effective_bytes == TOTAL_MEMORY_BUDGET_BYTES
    assert payload.user.effective_text.endswith(user_tail)
    assert payload.memory.effective_text.endswith(memory_tail)


def test_utf8_boundary_truncation_keeps_valid_text(tmp_path: Path) -> None:
    """Byte truncation must not split UTF-8 code points at the USER quota boundary."""
    two_byte_char = "é"
    char_bytes = len(two_byte_char.encode("utf-8"))
    assert char_bytes == 2
    repeat_count = (USER_MEMORY_BUDGET_BYTES // char_bytes) + 1
    tail = "UTF8_TAIL"
    content = (two_byte_char * repeat_count) + tail
    (tmp_path / _USER_FILENAME).write_text(content, encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.truncated is True
    assert payload.user.effective_bytes <= USER_MEMORY_BUDGET_BYTES
    assert payload.user.effective_text.endswith(tail)
    # decode round-trip proves no broken surrogate bytes
    payload.user.effective_text.encode("utf-8").decode("utf-8")


def test_effective_payload_type_is_structured(tmp_path: Path) -> None:
    """Public payload type is the structured contract for later injection tasks."""
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()
    assert isinstance(payload, EffectiveMemoryPayload)


def test_invalid_memory_root_raises_when_not_directory(tmp_path: Path) -> None:
    """A memory root that is a regular file raises a clear ValueError."""
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("not a directory", encoding="utf-8")
    store = LocalMemoryStore(root=invalid_root)

    with pytest.raises(ValueError, match="is not a directory"):
        store.build_effective_payload()


def test_oversized_file_uses_bounded_tail_read(tmp_path: Path) -> None:
    """Very large memory files truncate from the tail without loading the full file."""
    tail = "HUGE_FILE_TAIL_MARKER"
    # 2 MiB of filler — far larger than the 8 KB injection budget.
    (tmp_path / _USER_FILENAME).write_bytes(b"x" * (2 * 1024 * 1024) + tail.encode())
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    assert payload.user.truncated is True
    assert payload.user.original_bytes > TOTAL_MEMORY_BUDGET_BYTES
    assert payload.user.effective_text.endswith(tail)
    assert payload.user.effective_bytes <= USER_MEMORY_BUDGET_BYTES


def test_format_memory_injection_omits_empty_user_section(tmp_path: Path) -> None:
    """Injection skips the USER marker when only MEMORY.md has content."""
    (tmp_path / _MEMORY_FILENAME).write_text("project uses uv", encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    message = format_memory_injection_message(payload, "hello")

    assert USER_MEMORY_SECTION_MARKER not in message
    assert MEMORY_SECTION_MARKER in message
    assert "project uses uv" in message
    assert message.endswith("hello")


def test_format_memory_injection_omits_empty_memory_section(tmp_path: Path) -> None:
    """Injection skips the MEMORY marker when only USER.md has content."""
    (tmp_path / _USER_FILENAME).write_text("prefer dark mode", encoding="utf-8")
    store = LocalMemoryStore(root=tmp_path)
    payload = store.build_effective_payload()

    message = format_memory_injection_message(payload, "hello")

    assert USER_MEMORY_SECTION_MARKER in message
    assert MEMORY_SECTION_MARKER not in message
    assert "prefer dark mode" in message
    assert message.endswith("hello")


def test_memory_store_from_config_uses_override_root(tmp_path: Path) -> None:
    """Test-only override_root wins over config.memory_root."""
    override = tmp_path / "override-memory"
    override.mkdir()
    configured = tmp_path / "configured-memory"
    configured.mkdir()
    config = load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={
            "memory_root": str(configured),
        },
    )
    store = memory_store_from_config(config, override_root=override)
    assert store.root == override


def test_memory_store_from_config_uses_env_memory_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CURSOR_AGENT__MEMORY_ROOT selects the memory directory for injection."""
    memory_root = tmp_path / "env-memory-root"
    memory_root.mkdir()
    monkeypatch.setenv("CURSOR_AGENT__MEMORY_ROOT", str(memory_root))
    config = load_config(config_path=tmp_path / "missing.yaml")
    store = memory_store_from_config(config)
    assert store.root == memory_root
