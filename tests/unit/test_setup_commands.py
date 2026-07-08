"""Unit tests for ``cursor-agent setup`` Typer commands (PRD-013 Wave 2)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cursor_agent.cli import startup as startup_mod
from cursor_agent.cli.app import app, run_default
from cursor_agent.cli.first_run_marker import MARKER_FILENAME
from cursor_agent.config.effective import REDACTION_TOKEN
from cursor_agent.config.loader import CursorAgentConfig

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_PLACEHOLDER_API_KEY = "sk-test-placeholder"
_SETUP_EXAMPLE = "cursor-agent setup"


def _patch_non_interactive(monkeypatch: MonkeyPatch, *, is_ci: bool = False) -> None:
    """Force non-interactive apply guards for CliRunner (non-TTY; optional CI)."""
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: False,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: is_ci,
    )


def _patch_tty_not_ci(monkeypatch: MonkeyPatch) -> None:
    """Simulate interactive TTY with CI disabled (wizard eligibility guard)."""
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: False,
    )


def _apply_args(
    *,
    workspace: Path,
    config_path: Path,
    env_file: Path,
    api_key: str = _PLACEHOLDER_API_KEY,
    extra: list[str] | None = None,
) -> list[str]:
    """Build a headless ``setup`` invocation with injectable paths."""
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


# --- Task 4.1: help / Examples / registration ---------------------------------


def test_setup_help_includes_examples_section() -> None:
    """``setup --help`` exits 0 and includes an Examples section with a real invocation."""
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    combined = f"{result.stdout}\n{result.output}"
    assert "Examples" in combined
    assert _SETUP_EXAMPLE in combined


def test_setup_check_help_includes_examples_section() -> None:
    """``setup check --help`` includes Examples with a real ``cursor-agent setup`` string."""
    result = CliRunner().invoke(app, ["setup", "check", "--help"])
    assert result.exit_code == 0
    combined = f"{result.stdout}\n{result.output}"
    assert "Examples" in combined
    assert _SETUP_EXAMPLE in combined


def test_setup_show_help_includes_examples_section() -> None:
    """``setup show --help`` includes Examples with a real ``cursor-agent setup`` string."""
    result = CliRunner().invoke(app, ["setup", "show", "--help"])
    assert result.exit_code == 0
    combined = f"{result.stdout}\n{result.output}"
    assert "Examples" in combined
    assert _SETUP_EXAMPLE in combined


def test_setup_registered_on_root_help() -> None:
    """Root ``--help`` lists the ``setup`` command group."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "setup" in result.stdout.lower()


# --- Task 4.3: non-interactive apply / dry-run / force / idempotent -----------


def test_non_tty_without_required_flags_exits_nonzero_with_example(
    monkeypatch: MonkeyPatch,
) -> None:
    """Non-TTY apply without required flags exits non-zero with an example invocation."""
    _patch_non_interactive(monkeypatch)
    result = CliRunner().invoke(app, ["setup"])
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert _SETUP_EXAMPLE in combined
    assert "--api-key" in combined
    assert "--workspace" in combined
    assert "--yes" in combined


def test_apply_with_flags_writes_via_injected_paths(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Headless apply writes API key to env file and workspace to YAML under tmp_path."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        _apply_args(workspace=workspace, config_path=config_path, env_file=env_file),
    )
    assert result.exit_code == 0, result.output
    assert env_file.is_file()
    assert _PLACEHOLDER_API_KEY in env_file.read_text(encoding="utf-8")
    assert config_path.is_file()
    yaml_text = config_path.read_text(encoding="utf-8")
    assert str(workspace) in yaml_text
    assert _PLACEHOLDER_API_KEY not in yaml_text


def test_dry_run_prints_plan_without_writes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``--dry-run`` prints planned paths/key names with redacted secrets and no FS writes."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        _apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=["--dry-run"],
        ),
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}"
    assert str(config_path) in combined or "config" in combined.lower()
    assert "CURSOR_API_KEY" in combined
    assert _PLACEHOLDER_API_KEY not in combined
    assert REDACTION_TOKEN in combined or "***" in combined
    assert not config_path.exists()
    assert not env_file.exists()


def test_refuse_overwrite_env_without_force(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Differing existing env value without ``--force`` refuses and mentions setup show."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        _apply_args(workspace=workspace, config_path=config_path, env_file=env_file),
    )
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert "setup show" in combined
    assert (
        "sk-existing-other"
        == env_file.read_text(encoding="utf-8").split("=", 1)[1].strip()
    )
    assert not config_path.exists()


def test_refuse_overwrite_without_force_leaves_no_yaml_or_memory_placeholders(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Env refuse must not leave orphan config.yaml or memory USER.md/MEMORY.md."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")
    memory_root = tmp_path / "memory"

    result = CliRunner().invoke(
        app,
        _apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=["--memory-root", str(memory_root)],
        ),
    )
    assert result.exit_code != 0
    assert not config_path.exists()
    assert not (memory_root / "USER.md").exists()
    assert not (memory_root / "MEMORY.md").exists()
    assert (
        "sk-existing-other"
        == env_file.read_text(encoding="utf-8").split("=", 1)[1].strip()
    )


def test_apply_idempotent_second_run_exits_zero(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Second identical apply prints already-configured messaging and exits 0."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    args = _apply_args(workspace=workspace, config_path=config_path, env_file=env_file)

    first = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.output

    second = CliRunner().invoke(app, args)
    assert second.exit_code == 0, second.output
    combined = f"{second.stdout}\n{second.output}".lower()
    assert "already" in combined and "configur" in combined


def test_tty_without_flags_runs_interactive_wizard_not_deferred_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """TTY without value flags enters the wizard (FR-10), not the deferred-error branch."""
    _patch_tty_not_ci(monkeypatch)
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
        lambda _prompt="": _PLACEHOLDER_API_KEY,
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
    assert _PLACEHOLDER_API_KEY in env_file.read_text(encoding="utf-8")
    assert _PLACEHOLDER_API_KEY not in combined


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


def test_wizard_applies_on_confirm_y_and_never_echoes_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Wizard collects values, confirms with y, writes via same apply path; key never echoed."""
    _patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    secret = "sk-wizard-secret-key-never-echo"

    _patch_wizard_io(
        monkeypatch,
        api_key=secret,
        input_answers=[
            str(workspace),
            "",
            "",
            "",
            "",
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
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert secret not in combined
    assert "***" in combined or "API key" in combined.lower()
    assert "cursor-agent setup check" in combined
    assert env_file.is_file()
    assert secret in env_file.read_text(encoding="utf-8")
    assert config_path.is_file()
    assert secret not in config_path.read_text(encoding="utf-8")


def test_wizard_declines_on_n_without_writes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Confirm N aborts wizard without writing env or YAML files."""
    _patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=_PLACEHOLDER_API_KEY,
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
    assert _PLACEHOLDER_API_KEY not in combined


def test_wizard_skips_optional_fields_on_empty_enter(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Empty Enter on optional prompts skips them; required api-key + workspace still apply."""
    _patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=_PLACEHOLDER_API_KEY,
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
    assert _PLACEHOLDER_API_KEY in env_text


def test_wizard_completes_in_at_most_seven_interactive_steps(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Wizard stays within FR-10 ≤7 interactive prompt/getpass steps."""
    _patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    prompts = _patch_wizard_io(
        monkeypatch,
        api_key=_PLACEHOLDER_API_KEY,
        input_answers=[
            str(workspace),
            "",
            "",
            "",
            "",
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
    # getpass (1) + workspace (1) + ≤4 optionals + confirm (1) ≤ 7 interactive steps
    assert len(prompts) <= 7, f"too many interactive steps: {len(prompts)} {prompts!r}"


def test_wizard_yes_without_flags_still_requires_non_interactive_inputs(
    monkeypatch: MonkeyPatch,
) -> None:
    """``--yes`` without value flags on TTY must not hang — require flags (FR-6)."""
    _patch_tty_not_ci(monkeypatch)
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
    _patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    sessions_db = tmp_path / "db" / "sessions.db"
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=_PLACEHOLDER_API_KEY,
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
    assert _PLACEHOLDER_API_KEY not in f"{result.stdout}\n{result.output}"


def test_wizard_invalid_tool_profile_fails_before_confirm(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Invalid wizard tool_profile fails at prompt time with no writes (before confirm)."""
    _patch_tty_not_ci(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    _patch_wizard_io(
        monkeypatch,
        api_key=_PLACEHOLDER_API_KEY,
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


# --- Task 4.5 / 4.10: check and show ------------------------------------------


def test_check_missing_api_key_exit_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``setup check`` with missing API key prints error: line and exits 1."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: composer-2.5\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "check",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
        env={"CURSOR_API_KEY": ""},
    )
    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.output}"
    assert "error:" in combined
    assert "api" in combined.lower() or "CURSOR_API_KEY" in combined


def test_check_bad_workspace_exit_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``setup check`` with missing workspace directory exits 1 with error: line."""
    missing_ws = tmp_path / "does-not-exist"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "runtime:\n  local:\n    cwd: " + str(missing_ws) + "\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n", encoding="utf-8")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "check",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 1
    assert "error:" in f"{result.stdout}\n{result.output}"
    assert "workspace" in f"{result.stdout}\n{result.output}".lower()


def test_check_all_pass_exit_zero(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``setup check`` happy path prints ok: lines and exits 0."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    sessions_parent = tmp_path / "sessions_parent"
    sessions_parent.mkdir()
    sessions_db = sessions_parent / "sessions.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model: composer-2.5",
                f"memory_root: {memory_root}",
                "runtime:",
                "  local:",
                f"    cwd: {workspace}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
        f"CURSOR_AGENT_SESSIONS_DB={sessions_db}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_AGENT_SESSIONS_DB", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "check",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}"
    assert "ok:" in combined
    assert "error:" not in combined


def test_show_prints_redacted_effective_config(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``setup show`` prints redacted effective config with source labels; never raw key."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model: composer-2.5",
                "runtime:",
                "  local:",
                f"    cwd: {workspace}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n", encoding="utf-8")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "show",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}"
    assert _PLACEHOLDER_API_KEY not in combined
    assert REDACTION_TOKEN in combined or "***" in combined
    assert "source:" in combined
    assert "Effective" in combined or "effective" in combined.lower()


def test_show_attributes_api_key_from_env_file_as_env_not_shell(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """API key only in ``.env`` must show ``source: env``, not ``shell`` (FR-4).

    ``cli_entry`` loads CWD dotenv into ``os.environ`` before show runs; the
    process-environ snapshot for attribution must be taken before that load.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    # Fixture clears this; re-clear after delenv so the first load captures unset.
    startup_mod._PRE_DOTENV_PROCESS_ENVIRON = None
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model: composer-2.5",
                "runtime:",
                "  local:",
                f"    cwd: {workspace}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_only_key = "sk-env-file-only-placeholder"
    env_file.write_text(f"CURSOR_API_KEY={env_only_key}\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "show",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}"
    assert env_only_key not in combined
    assert "api_key:" in combined
    assert "source: env" in combined
    assert "api_key: *** (source: shell)" not in combined
    assert "api_key: *** (source: env)" in combined


def test_check_memory_root_missing_exits_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Missing memory_root path yields error: line and exit 1."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    missing_memory = tmp_path / "no-memory"
    sessions_parent = tmp_path / "sessions_parent"
    sessions_parent.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                f"memory_root: {missing_memory}",
                "runtime:",
                "  local:",
                f"    cwd: {workspace}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
        f"CURSOR_AGENT_SESSIONS_DB={sessions_parent / 'sessions.db'}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_AGENT_SESSIONS_DB", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "check",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.output}".lower()
    assert "error:" in combined
    assert "memory" in combined


def test_check_sessions_db_parent_not_creatable_exits_one(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Sessions-db parent that cannot be created yields error: and exit 1."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    # Point sessions-db under a file path so parent is not a directory.
    blocker = tmp_path / "blocker-file"
    blocker.write_text("not-a-dir", encoding="utf-8")
    sessions_db = blocker / "nested" / "sessions.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "runtime:",
                "  local:",
                f"    cwd: {workspace}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
        f"CURSOR_AGENT_SESSIONS_DB={sessions_db}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_AGENT_SESSIONS_DB", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "check",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.output}".lower()
    assert "error:" in combined
    assert "session" in combined


def test_check_memory_and_sessions_ok_lines(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy path prints ok: for memory root and sessions-db parent checks."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    sessions_parent = tmp_path / "sessions_parent"
    sessions_parent.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                f"memory_root: {memory_root}",
                "runtime:",
                "  local:",
                f"    cwd: {workspace}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
        f"CURSOR_AGENT_SESSIONS_DB={sessions_parent / 'sessions.db'}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_AGENT_SESSIONS_DB", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "setup",
            "check",
            "--config-path",
            str(config_path),
            "--env-file",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}".lower()
    assert "ok:" in combined
    assert "memory" in combined
    assert "session" in combined


# --- Task 4.7: no auto-setup / no first-run marker ----------------------------


def test_run_default_does_not_invoke_setup(monkeypatch: MonkeyPatch) -> None:
    """``run_default`` must not call into setup command helpers (FR-25)."""
    called = {"apply": False}

    def _spy_apply(**_kwargs: object) -> None:
        called["apply"] = True

    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands.run_setup_apply",
        _spy_apply,
    )
    monkeypatch.setattr("cursor_agent.cli.app.render_welcome", lambda *_a, **_k: False)
    monkeypatch.setattr("cursor_agent.cli.app.is_first_run", lambda **_k: False)

    @asynccontextmanager
    async def _fake_runtime(_config: CursorAgentConfig):
        yield object(), object(), object(), object()

    async def _fake_run_repl(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", _fake_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", _fake_run_repl)
    monkeypatch.setattr("cursor_agent.cli.app.RichDisplay", MagicMock)
    monkeypatch.setattr(
        "cursor_agent.cli.app.build_display_stream_callbacks",
        lambda *_a, **_k: None,
    )

    import asyncio

    asyncio.run(
        run_default(
            CursorAgentConfig(),
            no_banner=True,
            is_tty=False,
            is_ci=True,
        )
    )
    assert called["apply"] is False


def test_apply_does_not_write_first_run_marker(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Setup apply must not create ``first_run_complete`` under an injected marker home."""
    _patch_non_interactive(monkeypatch)
    marker_home = tmp_path / "marker_home"
    marker_home.mkdir()
    monkeypatch.setattr(
        "cursor_agent.cli.first_run_marker.default_marker_home",
        lambda: marker_home,
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        _apply_args(workspace=workspace, config_path=config_path, env_file=env_file),
    )
    assert result.exit_code == 0, result.output
    assert not (marker_home / MARKER_FILENAME).exists()


# --- Task 4.9: CI-mode + flag matrix + invalid tool_profile -------------------


def test_ci_mode_forces_non_interactive_even_when_tty(
    monkeypatch: MonkeyPatch,
) -> None:
    """``CI=1`` / ``is_ci=True`` never prompts even if stdout appears TTY."""
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._stdout_is_tty",
        lambda: True,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.setup_commands._is_ci_environment",
        lambda: True,
    )
    result = CliRunner().invoke(app, ["setup"])
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert _SETUP_EXAMPLE in combined
    assert "--api-key" in combined


def test_apply_flag_matrix_memory_model_profile_sessions(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Headless apply covers ``--memory-root``, ``--model``, ``--tool-profile``, ``--sessions-db``."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    sessions_db = tmp_path / "db" / "sessions.db"
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        _apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=[
                "--memory-root",
                str(memory_root),
                "--model",
                "composer-2.5",
                "--tool-profile",
                "messaging",
                "--sessions-db",
                str(sessions_db),
            ],
        ),
    )
    assert result.exit_code == 0, result.output
    yaml_text = config_path.read_text(encoding="utf-8")
    assert "messaging" in yaml_text
    assert "composer-2.5" in yaml_text
    assert str(memory_root) in yaml_text
    env_text = env_file.read_text(encoding="utf-8")
    assert "CURSOR_AGENT_SESSIONS_DB" in env_text
    assert str(sessions_db) in env_text
    assert _PLACEHOLDER_API_KEY not in yaml_text
    assert (memory_root / "USER.md").is_file()
    assert (memory_root / "MEMORY.md").is_file()


def test_invalid_tool_profile_exits_nonzero_without_write(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Invalid ``--tool-profile`` exits non-zero with actionable error and no write."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        _apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=["--tool-profile", "foo"],
        ),
    )
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}".lower()
    assert "tool" in combined and ("coding" in combined or "messaging" in combined)
    assert not config_path.exists()
    assert not env_file.exists()


def test_force_overwrite_surfaces_backup_path_in_success_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``--force`` creating ``.env.bak.*`` prints the backup path on success."""
    _patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        _apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=["--force"],
        ),
    )
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}"
    assert "backup:" in combined
    assert ".bak." in combined
    backups = list(env_file.parent.glob(f"{env_file.name}.bak.*"))
    assert len(backups) == 1
    assert str(backups[0]) in combined
    assert _PLACEHOLDER_API_KEY in env_file.read_text(encoding="utf-8")
