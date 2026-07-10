"""Unit tests for README first-heading phrase helper (PR #49 / Wave G5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.integration.readme_heading import first_readme_heading_phrase


def test_first_h2_returns_normalized_phrase(tmp_path: Path) -> None:
    """First H2 heading is stripped and normalized like the smoke assert."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "Intro paragraph.\n\n## What it provides\n\nBody.\n",
        encoding="utf-8",
    )
    assert first_readme_heading_phrase(readme) == "what it provides"


def test_first_h1_wins_when_present_before_h2(tmp_path: Path) -> None:
    """First heading line wins even when an H2 follows later."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Product Name\n\n## What it provides\n",
        encoding="utf-8",
    )
    assert first_readme_heading_phrase(readme) == "product name"


def test_no_heading_raises_value_error_mentioning_path(tmp_path: Path) -> None:
    """Missing heading raises ValueError that cites the README path."""
    readme = tmp_path / "README.md"
    readme.write_text("No headings here.\nJust prose.\n", encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(str(readme))) as exc_info:
        first_readme_heading_phrase(readme)
    message = str(exc_info.value)
    assert "heading" in message.lower()
