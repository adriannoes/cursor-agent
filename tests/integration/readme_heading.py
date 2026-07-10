"""Pure helpers for README heading phrases used by SDK smoke asserts.

No ``cursor_sdk`` import — unit-testable without an API key.
"""

from __future__ import annotations

from pathlib import Path


def first_readme_heading_phrase(readme_path: Path) -> str:
    """Return normalized phrase from the first markdown heading line.

    Strips leading ``#`` markers, then applies the same normalize as the
    smoke assert: ``.lower().replace("-", " ")``.

    Raises ValueError with path + reason if no heading line exists.

    Example:
        >>> # doctest: +SKIP
        >>> first_readme_heading_phrase(Path("README.md"))
        'what it provides'
    """
    text = readme_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        phrase = stripped.lstrip("#").strip()
        if not phrase:
            continue
        return phrase.lower().replace("-", " ")
    raise ValueError(
        f"no markdown heading line found in {readme_path}: "
        "expected at least one line starting with '#'"
    )
