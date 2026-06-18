"""Unit tests for config loader (PRD-002 FR-9, FR-10, ADR-007)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_settings import BaseSettings

from cursor_agent.config import CursorAgentConfig, load_config
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
