"""Unit tests for ``cursor-agent setup`` Typer apply / help / matrix (PRD-013 Wave 2)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from typer.testing import CliRunner

from cursor_agent.cli.app import app, run_default
from cursor_agent.cli.first_run_marker import MARKER_FILENAME
from cursor_agent.config.effective import REDACTION_TOKEN
from cursor_agent.config.loader import CursorAgentConfig
from tests.unit.setup_cli_test_fakes import (
    PLACEHOLDER_API_KEY,
    SETUP_EXAMPLE,
    apply_args,
    patch_non_interactive,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


# --- Task 4.1: help / Examples / registration ---------------------------------


def test_setup_help_includes_examples_section() -> None:
    """``setup --help`` exits 0 and includes an Examples section with a real invocation."""
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    combined = f"{result.stdout}\n{result.output}"
    assert "Examples" in combined
    assert SETUP_EXAMPLE in combined


def test_setup_check_help_includes_examples_section() -> None:
    """``setup check --help`` includes Examples with a real ``cursor-agent setup`` string."""
    result = CliRunner().invoke(app, ["setup", "check", "--help"])
    assert result.exit_code == 0
    combined = f"{result.stdout}\n{result.output}"
    assert "Examples" in combined
    assert SETUP_EXAMPLE in combined


def test_setup_show_help_includes_examples_section() -> None:
    """``setup show --help`` includes Examples with a real ``cursor-agent setup`` string."""
    result = CliRunner().invoke(app, ["setup", "show", "--help"])
    assert result.exit_code == 0
    combined = f"{result.stdout}\n{result.output}"
    assert "Examples" in combined
    assert SETUP_EXAMPLE in combined


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
    patch_non_interactive(monkeypatch)
    result = CliRunner().invoke(app, ["setup"])
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert SETUP_EXAMPLE in combined
    assert "--api-key" in combined
    assert "--workspace" in combined
    assert "--yes" in combined


def test_apply_with_flags_writes_via_injected_paths(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Headless apply writes API key to env file and workspace to YAML under tmp_path."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        apply_args(workspace=workspace, config_path=config_path, env_file=env_file),
    )
    assert result.exit_code == 0, result.output
    assert env_file.is_file()
    assert PLACEHOLDER_API_KEY in env_file.read_text(encoding="utf-8")
    assert config_path.is_file()
    yaml_text = config_path.read_text(encoding="utf-8")
    assert str(workspace) in yaml_text
    assert PLACEHOLDER_API_KEY not in yaml_text
    combined = f"{result.stdout}\n{result.output}"
    assert "Configuration written." in combined
    assert "cursor-agent setup check" in combined
    assert all(glyph not in combined for glyph in ("◆", "◇", "✓"))


def test_dry_run_prints_plan_without_writes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``--dry-run`` prints planned paths/key names with redacted secrets and no FS writes."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        apply_args(
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
    assert PLACEHOLDER_API_KEY not in combined
    assert REDACTION_TOKEN in combined or "***" in combined
    assert not config_path.exists()
    assert not env_file.exists()


def test_refuse_overwrite_env_without_force(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Differing existing env value without ``--force`` refuses and mentions setup show."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        apply_args(workspace=workspace, config_path=config_path, env_file=env_file),
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
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")
    memory_root = tmp_path / "memory"

    result = CliRunner().invoke(
        app,
        apply_args(
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
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    args = apply_args(workspace=workspace, config_path=config_path, env_file=env_file)

    first = CliRunner().invoke(app, args)
    assert first.exit_code == 0, first.output

    second = CliRunner().invoke(app, args)
    assert second.exit_code == 0, second.output
    combined = f"{second.stdout}\n{second.output}".lower()
    assert "already" in combined and "configur" in combined


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
    patch_non_interactive(monkeypatch)
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
        apply_args(workspace=workspace, config_path=config_path, env_file=env_file),
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
    assert SETUP_EXAMPLE in combined
    assert "--api-key" in combined


def test_apply_flag_matrix_memory_model_profile_sessions(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Headless apply covers ``--memory-root``, ``--model``, ``--tool-profile``, ``--sessions-db``."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    sessions_db = tmp_path / "db" / "sessions.db"
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        apply_args(
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
    assert PLACEHOLDER_API_KEY not in yaml_text
    assert (memory_root / "USER.md").is_file()
    assert (memory_root / "MEMORY.md").is_file()


def test_apply_accepts_tool_profile_full(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """FR-15: headless setup accepts ``--tool-profile full`` (PRD-012)."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=["--tool-profile", "full"],
        ),
    )
    assert result.exit_code == 0, result.output
    assert "tool_profile: full" in config_path.read_text(encoding="utf-8")


def test_invalid_tool_profile_exits_nonzero_without_write(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Invalid ``--tool-profile`` exits non-zero with actionable error and no write."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()

    result = CliRunner().invoke(
        app,
        apply_args(
            workspace=workspace,
            config_path=config_path,
            env_file=env_file,
            extra=["--tool-profile", "foo"],
        ),
    )
    assert result.exit_code != 0
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}".lower()
    assert "tool" in combined and (
        "coding" in combined or "messaging" in combined or "full" in combined
    )
    assert not config_path.exists()
    assert not env_file.exists()


def test_force_overwrite_surfaces_backup_path_in_success_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """``--force`` creating ``.env.bak.*`` prints the backup path on success."""
    patch_non_interactive(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text("CURSOR_API_KEY=sk-existing-other\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        apply_args(
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
    assert PLACEHOLDER_API_KEY in env_file.read_text(encoding="utf-8")
