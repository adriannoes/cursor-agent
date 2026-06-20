"""Unit tests for config loader (PRD-002 FR-9, FR-10, ADR-007)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import BaseSettings

from cursor_agent.config import CursorAgentConfig, load_config
from cursor_agent.cli.startup import load_cwd_dotenv
from cursor_agent.errors import ConfigError


def test_defaults_model_is_composer_2_5() -> None:
    """FR-10: default model matches STRATEGY §8 minimal config."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    assert config.model == "composer-2.5"


def test_defaults_tool_profile_is_coding() -> None:
    """FR-10: default tool profile is coding for dev CLI."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    assert config.tool_profile == "coding"


def test_defaults_runtime_mode_is_local() -> None:
    """FR-10: default runtime mode is local."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    assert config.runtime.mode == "local"


def test_defaults_runtime_local_cwd_is_dot() -> None:
    """FR-10: default local cwd is the current directory marker."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    assert config.runtime.local.cwd == "."


def test_defaults_runtime_local_setting_sources() -> None:
    """FR-10: default setting_sources loads project and user rules."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    assert config.runtime.local.setting_sources == ["project", "user"]


def test_cursor_agent_config_is_pydantic_model() -> None:
    """Public config type is a validated Pydantic model."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    assert isinstance(config, CursorAgentConfig)


def test_cursor_agent_config_uses_pydantic_settings() -> None:
    """FR-9 / ADR-007: config model participates in pydantic-settings v2."""
    assert issubclass(CursorAgentConfig, BaseSettings)


def test_yaml_file_values_are_loaded(tmp_path: Path) -> None:
    """ADR-007: YAML at config_path supplies field values."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "model: gpt-5\n"
        "tool_profile: messaging\n"
        "runtime:\n"
        "  mode: local\n"
        "  local:\n"
        "    cwd: /tmp/workspace\n"
        "    setting_sources:\n"
        "      - project\n",
        encoding="utf-8",
    )
    config = load_config(config_path=config_file)
    assert config.model == "gpt-5"
    assert config.tool_profile == "messaging"
    assert config.runtime.local.cwd == "/tmp/workspace"
    assert config.runtime.local.setting_sources == ["project"]


def test_yaml_expandvars_replaces_env_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-007: ${VAR} in YAML is expanded via os.path.expandvars."""
    monkeypatch.setenv("CURSOR_AGENT_TEST_CWD", "/expanded/path")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "runtime:\n  local:\n    cwd: ${CURSOR_AGENT_TEST_CWD}\n",
        encoding="utf-8",
    )
    config = load_config(config_path=config_file)
    assert config.runtime.local.cwd == "/expanded/path"


def test_yaml_invalid_top_level_shape_raises_config_error(tmp_path: Path) -> None:
    """Invalid YAML root (non-mapping) raises ConfigError with context."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(config_path=config_file)


def test_precedence_yaml_over_defaults(tmp_path: Path) -> None:
    """YAML overrides defaults but not higher-priority sources."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model: from-yaml\n", encoding="utf-8")
    config = load_config(config_path=config_file)
    assert config.model == "from-yaml"
    assert config.tool_profile == "coding"


def test_precedence_env_over_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env CURSOR_AGENT__* overrides YAML values."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model: from-yaml\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_AGENT__MODEL", "from-env")
    config = load_config(config_path=config_file)
    assert config.model == "from-env"


def test_precedence_cli_over_env_and_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI overrides beat env and YAML (ADR-007)."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model: from-yaml\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_AGENT__MODEL", "from-env")
    cli_overrides: dict[str, Any] = {"model": "from-cli"}
    config = load_config(config_path=config_file, cli_overrides=cli_overrides)
    assert config.model == "from-cli"


def test_precedence_nested_runtime_local_env_over_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested env keys override nested YAML runtime.local fields."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "runtime:\n  local:\n    cwd: /from/yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", "/from/env")
    config = load_config(config_path=config_file)
    assert config.runtime.local.cwd == "/from/env"


def test_precedence_nested_runtime_local_cli_over_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nested CLI overrides beat env and YAML for runtime.local.cwd."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "runtime:\n  local:\n    cwd: /from/yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", "/from/env")
    cli_overrides: dict[str, Any] = {
        "runtime": {"local": {"cwd": "/from/cli"}},
    }
    config = load_config(config_path=config_file, cli_overrides=cli_overrides)
    assert config.runtime.local.cwd == "/from/cli"


def test_precedence_cli_tool_profile_over_env_and_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI tool_profile override beats env and YAML (ADR-007)."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("tool_profile: coding\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_AGENT__TOOL_PROFILE", "coding")
    cli_overrides: dict[str, Any] = {"tool_profile": "messaging"}
    config = load_config(config_path=config_file, cli_overrides=cli_overrides)
    assert config.tool_profile == "messaging"


def test_omitted_cli_tool_profile_preserves_env_over_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without CLI tool_profile override, env still wins over YAML."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("tool_profile: coding\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_AGENT__TOOL_PROFILE", "messaging")
    config = load_config(config_path=config_file)
    assert config.tool_profile == "messaging"


def test_omitted_cli_tool_profile_preserves_yaml_over_default(
    tmp_path: Path,
) -> None:
    """Without CLI tool_profile override, YAML still wins over defaults."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("tool_profile: messaging\n", encoding="utf-8")
    config = load_config(config_path=config_file)
    assert config.tool_profile == "messaging"


def test_memory_root_defaults_to_none(tmp_path: Path) -> None:
    """Memory root is optional and defaults to unset (home directory at runtime)."""
    config = load_config(config_path=tmp_path / "missing.yaml")
    assert config.memory_root is None


def test_precedence_env_memory_root_over_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env CURSOR_AGENT__MEMORY_ROOT overrides YAML memory_root."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("memory_root: /from/yaml\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_AGENT__MEMORY_ROOT", "/from/env")
    config = load_config(config_path=config_file)
    assert config.memory_root == "/from/env"


# --- PRD-012 Task 1.1: advertised env / dotenv regressions ---


def test_unsupported_cursor_agent_workspace_env_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy flat CURSOR_AGENT_WORKSPACE from .env.example must not set workspace cwd."""
    monkeypatch.setenv("CURSOR_AGENT_WORKSPACE", "/from/unsupported-flat")
    monkeypatch.delenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", raising=False)
    config = load_config(config_path=tmp_path / "missing.yaml")
    assert config.runtime.local.cwd == "."


def test_unsupported_cursor_agent_config_env_does_not_redirect_yaml_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy flat CURSOR_AGENT_CONFIG must not replace the explicit config_path argument."""
    alt_yaml = tmp_path / "alt.yaml"
    alt_yaml.write_text("model: from-alt-yaml\n", encoding="utf-8")
    explicit_yaml = tmp_path / "explicit.yaml"
    explicit_yaml.write_text("model: from-explicit-yaml\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_AGENT_CONFIG", str(alt_yaml))
    config = load_config(config_path=explicit_yaml)
    assert config.model == "from-explicit-yaml"


def test_dotenv_runtime_local_cwd_is_canonical_workspace_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD-012: CWD .env uses CURSOR_AGENT__RUNTIME__LOCAL__CWD as workspace override."""
    workspace = tmp_path / "dotenv-workspace"
    workspace.mkdir()
    (tmp_path / ".env").write_text(
        f"CURSOR_AGENT__RUNTIME__LOCAL__CWD={workspace}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", raising=False)
    monkeypatch.chdir(tmp_path)
    load_cwd_dotenv()
    config = load_config(config_path=tmp_path / "missing.yaml")
    assert config.runtime.local.cwd == str(workspace)


def test_dotenv_memory_root_applies_when_os_environ_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PRD-012: CWD .env supplies CURSOR_AGENT__MEMORY_ROOT when shell env is unset."""
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (tmp_path / ".env").write_text(
        f"CURSOR_AGENT__MEMORY_ROOT={memory_root}\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CURSOR_AGENT__MEMORY_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    load_cwd_dotenv()
    config = load_config(config_path=tmp_path / "missing.yaml")
    assert config.memory_root == str(memory_root)


def test_dotenv_precedence_over_yaml_and_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dotenv values beat YAML and defaults but lose to exported env and CLI."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model: from-yaml\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "CURSOR_AGENT__MODEL=from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.delenv("CURSOR_AGENT__MODEL", raising=False)
    monkeypatch.chdir(tmp_path)
    load_cwd_dotenv()
    config = load_config(config_path=config_file)
    assert config.model == "from-dotenv"


def test_dotenv_does_not_override_exported_os_environ(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exported shell env wins over CWD .env (python-dotenv override=False semantics)."""
    (tmp_path / ".env").write_text(
        "CURSOR_AGENT__MODEL=from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.setenv("CURSOR_AGENT__MODEL", "from-shell")
    monkeypatch.chdir(tmp_path)
    load_cwd_dotenv()
    config = load_config(config_path=tmp_path / "missing.yaml")
    assert config.model == "from-shell"


def test_precedence_cli_over_dotenv_yaml_and_exported_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI overrides beat exported env, dotenv, and YAML (ADR-007 + PRD-012)."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("model: from-yaml\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "CURSOR_AGENT__MODEL=from-dotenv\n", encoding="utf-8"
    )
    monkeypatch.setenv("CURSOR_AGENT__MODEL", "from-shell")
    monkeypatch.chdir(tmp_path)
    load_cwd_dotenv()
    cli_overrides: dict[str, Any] = {"model": "from-cli"}
    config = load_config(config_path=config_file, cli_overrides=cli_overrides)
    assert config.model == "from-cli"
