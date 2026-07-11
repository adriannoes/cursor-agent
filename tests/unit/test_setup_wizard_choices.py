"""Unit tests for Proposal B numbered model/tool-profile wizard choices."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.unit.setup_cli_test_fakes import run_wizard_choices

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


# --- Wave G3 / Task 1.9: Proposal B choices ----------------------------------


@pytest.mark.parametrize(
    ("field", "choice", "expected"),
    [
        ("model", "1", "model: grok-4.5"),
        ("model", "2", "model: composer-2.5"),
        ("model", "some-other-model", "model: some-other-model"),
        ("tool_profile", "1", "tool_profile: coding"),
        ("tool_profile", "2", "tool_profile: messaging"),
        ("tool_profile", "3", "tool_profile: full"),
    ],
)
def test_wizard_resolves_numbered_model_and_tool_profile_choices(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    field: str,
    choice: str,
    expected: str,
) -> None:
    """Proposal B indexes and soft non-catalog model ids persist unchanged."""
    kwargs = {field: choice}
    result, config_path, _, _ = run_wizard_choices(
        tmp_path,
        monkeypatch,
        **kwargs,
    )
    assert result.exit_code == 0, result.output
    assert expected in config_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("field", ["model", "tool_profile"])
def test_wizard_rejects_invalid_numeric_choice_nine(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    field: str,
) -> None:
    """Out-of-range model/profile index fails before any writes."""
    kwargs = {field: "9"}
    result, config_path, env_file, _ = run_wizard_choices(
        tmp_path,
        monkeypatch,
        **kwargs,
    )
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert result.exit_code != 0
    assert "9" in combined and "expected" in combined.lower()
    expected_indexes = (
        ("'1'", "'2'", "'3'") if field == "tool_profile" else ("'1'", "'2'")
    )
    assert all(index in combined for index in expected_indexes)
    assert not config_path.exists() and not env_file.exists()
