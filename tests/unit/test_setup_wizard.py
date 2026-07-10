"""Unit tests for interactive ``cursor-agent setup`` wizard (PRD-013 FR-10)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from tests.unit.setup_cli_test_fakes import (
    PLACEHOLDER_API_KEY,
    patch_tty_not_ci,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from click.testing import Result


# --- Interactive wizard entry / FR-10 ---------------------------------------


def test_tty_without_flags_runs_interactive_wizard_not_deferred_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """TTY without value flags enters the wizard (FR-10), not the deferred-error branch."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    answers = iter(
        [
            str(workspace),  # workspace
            "",  # memory root skip
            "",  # sessions db skip
            "",  # model skip
            "",  # tool profile skip
            "y",  # confirm
        ]
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_wizard._getpass_fn",
        lambda _prompt="": PLACEHOLDER_API_KEY,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_wizard._input_fn",
        lambda _prompt="": next(answers),
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert "not available yet" not in combined.lower()
    assert env_file.is_file()
    assert PLACEHOLDER_API_KEY in env_file.read_text(encoding="utf-8")
    assert PLACEHOLDER_API_KEY not in combined


# --- Task 5.1 / 5.3: interactive wizard (FR-10) -------------------------------


def _patch_wizard_io(
    monkeypatch: MonkeyPatch,
    *,
    api_key: str,
    input_answers: list[str],
) -> list[str]:
    """Inject getpass/input for wizard tests; return list of prompts seen by input_fn."""
    prompts_seen: list[str] = []
    answers = iter(input_answers)

    def fake_getpass(prompt: str = "") -> str:
        prompts_seen.append(prompt)
        return api_key

    def fake_input(prompt: str = "") -> str:
        prompts_seen.append(prompt)
        try:
            return next(answers)
        except StopIteration as exc:
            raise AssertionError(
                f"wizard requested more input than provided; "
                f"last prompt={prompt!r}, prompts_seen={prompts_seen!r}"
            ) from exc

    monkeypatch.setattr("cursor_agent.cli.setup_wizard._getpass_fn", fake_getpass)
    monkeypatch.setattr("cursor_agent.cli.setup_wizard._input_fn", fake_input)
    return prompts_seen


def _run_wizard_choices(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    model: str = "",
    tool_profile: str = "",
    api_key: str = PLACEHOLDER_API_KEY,
) -> tuple[Result, Path, Path, list[str]]:
    """Run one isolated wizard case with optional model/profile choices."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    prompts = _patch_wizard_io(
        monkeypatch,
        api_key=api_key,
        input_answers=[str(workspace), "", "", model, tool_profile, "y"],
    )
    result = CliRunner().invoke(
        app,
        ["setup", "--config-path", str(config_path), "--env-file", str(env_file)],
    )
    return result, config_path, env_file, prompts


def test_wizard_applies_on_confirm_y_and_never_echoes_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy path locks G3 chrome/defaults while keeping the API key secret."""
    secret = "sk-wizard-secret-key-never-echo"
    result, config_path, env_file, prompts = _run_wizard_choices(
        tmp_path,
        monkeypatch,
        api_key=secret,
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    prompt_text = "\n".join(prompts)
    transcript = f"{combined}\n{prompt_text}"
    assert secret not in combined
    assert all(glyph in transcript for glyph in ("◆", "│", "◇", "●", "○", "✓"))
    assert "└" in prompt_text
    assert all(
        token in prompt_text
        for token in ("[1 / 2 / id]", "[1 / 2 / 3 / name]", "[y / N]")
    )
    assert "Grok 4.5" in transcript and "composer-2.5" in transcript
    assert all(profile in transcript for profile in ("coding", "messaging", "full"))
    assert all(
        line in combined
        for line in (
            "│  ● 1  Grok 4.5      grok-4.5         (recommended)",
            "│  ○ 2  Composer 2.5  composer-2.5",
            "│  ○    Other — type a Cursor SDK model id",
            "│  ● 1  coding     Local development (default)",
            "│  ○ 2  messaging  Gateways / bots — read-only posture",
            "│  ○ 3  full       Coding + curated MCP servers",
        )
    )
    assert "model: (default: grok-4.5)" in combined
    assert "tool_profile: (default: coding)" in combined
    assert "memory_root: (skipped → ~/.cursor-agent)" in combined
    assert "sessions_db: (skipped → ~/.cursor-agent/sessions.db)" in combined
    assert "cursor-agent setup check" in combined and len(prompts) <= 7
    assert f"│  env: {env_file}" in combined
    assert f"│  yaml: {config_path}" in combined
    assert env_file.is_file()
    assert secret in env_file.read_text(encoding="utf-8")
    assert config_path.is_file()
    yaml_text = config_path.read_text(encoding="utf-8")
    assert secret not in yaml_text
    assert "model:" not in yaml_text and "tool_profile:" not in yaml_text


def test_wizard_force_overwrite_surfaces_backup_path_in_success_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Interactive ``--force`` reports its generated env backup path."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")
    _patch_wizard_io(
        monkeypatch,
        api_key=PLACEHOLDER_API_KEY,
        input_answers=[str(workspace), "", "", "", "", "y"],
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--force",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )

    assert result.exit_code == 0, result.output
    backups = list(env_file.parent.glob(f"{env_file.name}.bak.*"))
    assert len(backups) == 1
    assert (
        f"✓  Configuration written.\n"
        f"│  env: {env_file}\n"
        f"│  yaml: {config_path}\n"
        f"│  backup: {backups[0]}"
    ) in result.output
    assert "│  Next: cursor-agent setup check" in result.output


def test_wizard_declines_on_n_without_writes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Confirm N aborts wizard without writing env or YAML files."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=PLACEHOLDER_API_KEY,
        input_answers=[
            str(workspace),
            "",
            "",
            "",
            "",
            "n",
        ],
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code != 0
    assert not config_path.exists()
    assert not env_file.exists()
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert PLACEHOLDER_API_KEY not in combined


def test_wizard_skips_optional_fields_on_empty_enter(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Empty Enter on optional prompts skips them; required api-key + workspace still apply."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=PLACEHOLDER_API_KEY,
        input_answers=[
            str(workspace),
            "",  # memory
            "",  # sessions
            "",  # model
            "",  # profile
            "y",
        ],
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    yaml_text = config_path.read_text(encoding="utf-8")
    assert "memory_root" not in yaml_text
    assert "tool_profile" not in yaml_text
    env_text = env_file.read_text(encoding="utf-8")
    assert "CURSOR_AGENT_SESSIONS_DB" not in env_text
    assert PLACEHOLDER_API_KEY in env_text


def test_wizard_yes_without_flags_still_requires_non_interactive_inputs(
    monkeypatch: MonkeyPatch,
) -> None:
    """``--yes`` without value flags on TTY must not hang — require flags (FR-6)."""
    patch_tty_not_ci(monkeypatch)
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert "--api-key" in combined
    assert "--workspace" in combined


def test_wizard_with_optional_fields_writes_all(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Filled optional wizard fields persist memory/sessions/model/profile."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    sessions_db = tmp_path / "db" / "sessions.db"
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=PLACEHOLDER_API_KEY,
        input_answers=[
            str(workspace),
            str(memory_root),
            str(sessions_db),
            "composer-2.5",
            "messaging",
            "y",
        ],
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    yaml_text = config_path.read_text(encoding="utf-8")
    assert "messaging" in yaml_text
    assert "composer-2.5" in yaml_text
    assert str(memory_root) in yaml_text
    env_text = env_file.read_text(encoding="utf-8")
    assert str(sessions_db) in env_text
    assert PLACEHOLDER_API_KEY not in f"{result.stdout}\n{result.output}"


def test_wizard_invalid_tool_profile_fails_before_confirm(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Invalid wizard tool_profile fails at prompt time with no writes (before confirm)."""
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=PLACEHOLDER_API_KEY,
        input_answers=[
            str(workspace),
            "",
            "",
            "",
            "foo",  # invalid tool_profile — must fail before confirm
        ],
    )

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}".lower()
    assert "tool" in combined and ("coding" in combined or "messaging" in combined)
    assert "foo" in combined
    assert not config_path.exists()
    assert not env_file.exists()


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
    result, config_path, _, _ = _run_wizard_choices(
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
    result, config_path, env_file, _ = _run_wizard_choices(
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
