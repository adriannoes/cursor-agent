"""Unit tests for ``cursor-agent setup check`` and ``setup show`` (PRD-013)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from cursor_agent.cli import startup as startup_mod
from cursor_agent.cli.app import app
from cursor_agent.config.effective import REDACTION_TOKEN
from tests.unit.setup_cli_test_fakes import PLACEHOLDER_API_KEY

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


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
    env_file.write_text(f"CURSOR_API_KEY={PLACEHOLDER_API_KEY}\n", encoding="utf-8")
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
        f"CURSOR_API_KEY={PLACEHOLDER_API_KEY}\n"
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
    env_file.write_text(f"CURSOR_API_KEY={PLACEHOLDER_API_KEY}\n", encoding="utf-8")
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
    assert PLACEHOLDER_API_KEY not in combined
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
        f"CURSOR_API_KEY={PLACEHOLDER_API_KEY}\n"
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
        f"CURSOR_API_KEY={PLACEHOLDER_API_KEY}\n"
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
        f"CURSOR_API_KEY={PLACEHOLDER_API_KEY}\n"
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
