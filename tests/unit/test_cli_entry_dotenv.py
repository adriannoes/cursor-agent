"""Unit tests for CLI dotenv / advertised env regressions (PRD-012 Task 1.1)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.startup import repl_runtime
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.sdk_facade import RunStatus


# --- PRD-012 Task 1.1: advertised env / dotenv regressions ---


def test_cli_startup_loads_dotenv_workspace_into_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default CLI bootstrap loads gitignored CWD .env into load_config workspace cwd."""
    workspace = tmp_path / "cli-dotenv-workspace"
    workspace.mkdir()
    (tmp_path / ".env").write_text(
        f"CURSOR_AGENT__RUNTIME__LOCAL__CWD={workspace}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", raising=False)
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    async def stub_run_default(
        config: CursorAgentConfig,
        *,
        no_banner: bool = False,
    ) -> RunStatus | None:
        _ = no_banner
        captured["cwd"] = config.runtime.local.cwd
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert captured["cwd"] == str(workspace)


def test_cli_dotenv_does_not_override_exported_env_vars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI .env bootstrap must not override variables already exported in the shell."""
    (tmp_path / ".env").write_text(
        "CURSOR_AGENT__MODEL=from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.setenv("CURSOR_AGENT__MODEL", "from-shell")
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    async def stub_run_default(
        config: CursorAgentConfig,
        *,
        no_banner: bool = False,
    ) -> RunStatus | None:
        _ = no_banner
        captured["model"] = config.model
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert captured["model"] == "from-shell"


def test_cli_startup_loads_cursor_api_key_from_dotenv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default CLI path makes CURSOR_API_KEY from CWD .env visible to facade bootstrap."""
    captured_api_keys: list[str | None] = []

    class RecordingSdkFacade:
        """Capture api_key for the production facade constructor during CLI startup."""

        def __init__(
            self,
            *,
            api_key: str | None = None,
            local_setting_sources: list[str] | None = None,
            **kwargs: object,
        ) -> None:
            _ = (local_setting_sources, kwargs)
            captured_api_keys.append(api_key)

        async def __aenter__(self) -> RecordingSdkFacade:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    (tmp_path / ".env").write_text("CURSOR_API_KEY=from-dotenv-key\n", encoding="utf-8")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cursor_agent.cli.startup.AsyncSdkFacade", RecordingSdkFacade)

    @asynccontextmanager
    async def real_repl_runtime(cfg: CursorAgentConfig):
        # Top-level import of startup.repl_runtime keeps the real function after
        # monkeypatching cursor_agent.cli.app.repl_runtime (no-inline-imports rule).
        async with repl_runtime(cfg) as runtime:
            yield runtime

    async def stub_run_repl(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("cursor_agent.cli.app.repl_runtime", real_repl_runtime)
    monkeypatch.setattr("cursor_agent.cli.app.run_repl", stub_run_repl)
    monkeypatch.setattr(
        "cursor_agent.cli.app.render_welcome",
        lambda *_args, **_kwargs: False,
    )

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert captured_api_keys == ["from-dotenv-key"]
