"""Bounded UTF-8 file I/O helpers shared by memory and skills."""

from __future__ import annotations

from pathlib import Path
from typing import Final

# Max UTF-8 code unit length minus one — read slack so tail decode never splits a code point.
UTF8_TAIL_SLACK_BYTES: Final[int] = 4


def read_utf8_file_tail(path: Path, max_tail_bytes: int) -> tuple[str, int]:
    """Read at most ``max_tail_bytes`` UTF-8 bytes from the end of ``path``.

    Returns decoded text and the on-disk file size in bytes. Only the tail is
    loaded into memory, avoiding unbounded reads for prompt-bound local files.

    Example:
        >>> read_utf8_file_tail(Path("USER.md"), 4096)
        ('prefer dark mode', 18)
    """
    file_size = path.stat().st_size
    if file_size == 0:
        return "", 0

    read_size = min(file_size, max_tail_bytes + UTF8_TAIL_SLACK_BYTES)
    with path.open("rb") as handle:
        handle.seek(file_size - read_size)
        raw = handle.read(read_size)

    if read_size == file_size:
        return raw.decode("utf-8"), file_size

    return decode_without_split_code_point(raw), file_size


def truncate_utf8_from_end(text: str, max_bytes: int) -> str:
    """Keep the tail of ``text`` within ``max_bytes`` UTF-8 bytes."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated_bytes = encoded[-max_bytes:]
    return decode_without_split_code_point(truncated_bytes)


def decode_without_split_code_point(byte_slice: bytes) -> str:
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
