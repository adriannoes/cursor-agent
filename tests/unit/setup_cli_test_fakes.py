"""Shared helpers for ``cursor-agent setup`` CLI unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from cursor_agent.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from click.testing import Result

PLACEHOLDER_API_KEY = "sk-test-placeholder"
SETUP_EXAMPLE = "cursor-agent setup"


def patch_non_interactive(monkeypatch: MonkeyPatch, *, is_ci: bool = False) -> None:
    """Force non-interactive apply guards for CliRunner (non-TTY; optional CI).

    Example:
        >>> patch_non_interactive(monkeypatch)
    """
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: False,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: is_ci,
    )


def patch_tty_not_ci(monkeypatch: MonkeyPatch) -> None:
    """Simulate interactive TTY with CI disabled (wizard eligibility guard).

    Example:
        >>> patch_tty_not_ci(monkeypatch)
    """
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: False,
    )


def apply_args(
    *,
    workspace: Path,
    config_path: Path,
    env_file: Path,
    api_key: str = PLACEHOLDER_API_KEY,
    extra: list[str] | None = None,
) -> list[str]:
    """Build a headless ``setup`` invocation with injectable paths.

    Example:
        >>> apply_args(workspace=ws, config_path=cfg, env_file=env)
        ['setup', '--api-key', '...', ...]
    """
    args = [
        "setup",
        "--api-key",
        api_key,
        "--workspace",
        str(workspace),
        "--config-path",
        str(config_path),
        "--env-file",
        str(env_file),
        "--yes",
    ]
    if extra:
        args.extend(extra)
    return args


def patch_wizard_io(
    monkeypatch: MonkeyPatch,
    *,
    api_key: str,
    input_answers: list[str],
) -> list[str]:
    """Inject getpass/input for wizard tests; return prompts seen by input_fn.

    Example:
        >>> patch_wizard_io(monkeypatch, api_key="sk-x", input_answers=["y"])
    """
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


def run_wizard_choices(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    model: str = "",
    tool_profile: str = "",
    api_key: str = PLACEHOLDER_API_KEY,
) -> tuple[Result, Path, Path, list[str]]:
    """Run one isolated wizard case with optional model/profile choices.

    Example:
        >>> run_wizard_choices(tmp_path, monkeypatch, model="1")
    """
    patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    prompts = patch_wizard_io(
        monkeypatch,
        api_key=api_key,
        input_answers=[str(workspace), "", "", model, tool_profile, "y"],
    )
    result = CliRunner().invoke(
        app,
        ["setup", "--config-path", str(config_path), "--env-file", str(env_file)],
    )
    return result, config_path, env_file, prompts
