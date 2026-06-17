"""Unit tests for gateway YAML configuration (PRD-006, ADR-007)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from cursor_agent.config import CursorAgentConfig
from cursor_agent.errors import ConfigError
from cursor_agent.gateway import (
    DEFAULT_GATEWAY_CONFIG_PATH,
    GatewayConfig,
    TelegramPlatformConfig,
    load_gateway_config,
    resolve_gateway_startup_config,
    to_cursor_agent_config,
)

_EXAMPLE_GATEWAY_CONFIG = (
    Path(__file__).resolve().parents[2] / "examples" / "gateway.yaml.example"
)


def _write_gateway_yaml(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _minimal_gateway_yaml(
    *,
    workspace: str = "/tmp/gateway-workspace",
    tool_profile: str = "messaging",
    telegram_enabled: bool = True,
    bot_token: str = "placeholder-token",
    allowed_users: str = "123456789",
) -> str:
    return (
        f"workspace: {workspace}\n"
        f"tool_profile: {tool_profile}\n"
        "platforms:\n"
        "  telegram:\n"
        f"    enabled: {str(telegram_enabled).lower()}\n"
        f"    bot_token: {bot_token}\n"
        f"    allowed_users:\n"
        f"      - {allowed_users}\n"
    )


def test_gateway_package_exports_config_symbols() -> None:
    """Gateway package exposes stable config symbols without runner side effects."""
    from cursor_agent import gateway

    assert gateway.DEFAULT_GATEWAY_CONFIG_PATH == DEFAULT_GATEWAY_CONFIG_PATH
    assert gateway.GatewayConfig is GatewayConfig
    assert gateway.load_gateway_config is load_gateway_config
    assert gateway.to_cursor_agent_config is to_cursor_agent_config
    assert gateway.resolve_gateway_startup_config is resolve_gateway_startup_config


def test_gateway_config_models_are_pydantic() -> None:
    """Gateway config types are frozen Pydantic v2 models."""
    config = GatewayConfig.model_validate(
        {
            "workspace": "/tmp/ws",
            "tool_profile": "messaging",
            "platforms": {"telegram": {"enabled": False}},
        },
    )
    assert isinstance(config, GatewayConfig)
    assert isinstance(config.platforms.telegram, TelegramPlatformConfig)
    assert issubclass(GatewayConfig, BaseModel)


def test_default_gateway_config_path() -> None:
    """Default gateway config path is ~/.cursor-agent/gateway.yaml."""
    assert DEFAULT_GATEWAY_CONFIG_PATH == (
        Path.home() / ".cursor-agent" / "gateway.yaml"
    )


def test_load_gateway_config_uses_default_path_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing default file yields validation error for required workspace."""
    monkeypatch.setattr(
        "cursor_agent.gateway.config.DEFAULT_GATEWAY_CONFIG_PATH",
        Path("/nonexistent/gateway.yaml"),
    )
    with pytest.raises(ConfigError, match="workspace"):
        load_gateway_config()


def test_load_gateway_config_explicit_path(tmp_path: Path) -> None:
    """Explicit config_path loads YAML from the given file."""
    config_file = tmp_path / "custom-gateway.yaml"
    _write_gateway_yaml(config_file, _minimal_gateway_yaml(workspace="/explicit/ws"))
    config = load_gateway_config(config_path=config_file)
    assert config.workspace == "/explicit/ws"
    assert config.tool_profile == "messaging"


def test_load_gateway_config_invalid_top_level_shape_raises_config_error(
    tmp_path: Path,
) -> None:
    """Invalid YAML root (non-mapping) raises ConfigError with context."""
    config_file = tmp_path / "gateway.yaml"
    config_file.write_text("- not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_gateway_config(config_path=config_file)


def test_load_gateway_config_unknown_field_raises_config_error(
    tmp_path: Path,
) -> None:
    """Unknown top-level fields are rejected (extra=forbid)."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml() + "unexpected_field: true\n",
    )
    with pytest.raises(ConfigError, match="unexpected_field|extra"):
        load_gateway_config(config_path=config_file)


def test_load_gateway_config_missing_workspace_raises_config_error(
    tmp_path: Path,
) -> None:
    """Workspace is required for gateway startup."""
    config_file = tmp_path / "gateway.yaml"
    config_file.write_text(
        "tool_profile: messaging\nplatforms:\n  telegram:\n    enabled: false\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="workspace"):
        load_gateway_config(config_path=config_file)


def test_load_gateway_config_unknown_platform_field_raises_config_error(
    tmp_path: Path,
) -> None:
    """Unknown telegram platform fields are rejected."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml() + "    unknown_telegram_field: true\n",
    )
    with pytest.raises(ConfigError, match="unknown_telegram_field|extra"):
        load_gateway_config(config_path=config_file)


def test_load_gateway_config_expands_env_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """${VAR} placeholders in YAML strings expand via os.path.expandvars."""
    monkeypatch.setenv("GATEWAY_TEST_BOT_TOKEN", "expanded-token-value")
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml(bot_token="${GATEWAY_TEST_BOT_TOKEN}"),
    )
    config = load_gateway_config(config_path=config_file)
    assert config.platforms.telegram.bot_token == "expanded-token-value"


def test_load_gateway_config_expands_workspace_env_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace path supports ${VAR} expansion."""
    monkeypatch.setenv("GATEWAY_TEST_WORKSPACE", "/expanded/workspace")
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml(workspace="${GATEWAY_TEST_WORKSPACE}"),
    )
    config = load_gateway_config(config_path=config_file)
    assert config.workspace == "/expanded/workspace"


def test_load_gateway_config_telegram_shape(tmp_path: Path) -> None:
    """Telegram platform block exposes enabled, bot_token, and allowed_users."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml(
            bot_token="test-bot-token",
            allowed_users="987654321",
        ),
    )
    config = load_gateway_config(config_path=config_file)
    telegram = config.platforms.telegram
    assert telegram.enabled is True
    assert telegram.bot_token == "test-bot-token"
    assert telegram.allowed_users == [987654321]


def test_load_gateway_config_tool_profile_messaging(tmp_path: Path) -> None:
    """Gateway config accepts tool_profile messaging."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(config_file, _minimal_gateway_yaml(tool_profile="messaging"))
    config = load_gateway_config(config_path=config_file)
    assert config.tool_profile == "messaging"


def test_load_gateway_config_tool_profile_coding(tmp_path: Path) -> None:
    """Gateway config accepts tool_profile coding for runner fail-fast tests."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(config_file, _minimal_gateway_yaml(tool_profile="coding"))
    config = load_gateway_config(config_path=config_file)
    assert config.tool_profile == "coding"


def test_load_gateway_config_invalid_tool_profile_raises_config_error(
    tmp_path: Path,
) -> None:
    """Invalid tool_profile values raise ConfigError."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(config_file, _minimal_gateway_yaml(tool_profile="full"))
    with pytest.raises(ConfigError, match="tool_profile|full"):
        load_gateway_config(config_path=config_file)


def test_to_cursor_agent_config_maps_workspace_and_profile(tmp_path: Path) -> None:
    """Bridge maps workspace to runtime.local.cwd and carries tool_profile."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml(workspace="/bridge/workspace", tool_profile="messaging"),
    )
    gateway_config = load_gateway_config(config_path=config_file)
    agent_config = to_cursor_agent_config(gateway_config)

    assert isinstance(agent_config, CursorAgentConfig)
    assert agent_config.runtime.local.cwd == "/bridge/workspace"
    assert agent_config.tool_profile == "messaging"


def test_to_cursor_agent_config_preserves_cli_compatible_defaults(
    tmp_path: Path,
) -> None:
    """Bridge leaves model and runtime defaults compatible with the CLI stack."""
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(config_file, _minimal_gateway_yaml())
    gateway_config_loaded = load_gateway_config(config_path=config_file)
    agent_config = to_cursor_agent_config(gateway_config_loaded)

    assert agent_config.model == "composer-2.5"
    assert agent_config.runtime.mode == "local"
    assert agent_config.runtime.local.setting_sources == ["project", "user"]


def test_to_cursor_agent_config_ignores_cursor_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Gateway bridge uses package defaults only, not CURSOR_AGENT__* overrides."""
    monkeypatch.setenv("CURSOR_AGENT__MODEL", "env-overridden-model")
    monkeypatch.setenv("CURSOR_AGENT__TOOL_PROFILE", "coding")
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(config_file, _minimal_gateway_yaml(tool_profile="messaging"))
    gateway_config_loaded = load_gateway_config(config_path=config_file)
    agent_config = to_cursor_agent_config(gateway_config_loaded)

    assert agent_config.model == "composer-2.5"
    assert agent_config.tool_profile == "messaging"


def test_example_gateway_config_parses() -> None:
    """Documented example gateway.yaml.example loads and validates."""
    assert _EXAMPLE_GATEWAY_CONFIG.is_file(), (
        f"missing example config: {_EXAMPLE_GATEWAY_CONFIG}"
    )
    config = load_gateway_config(config_path=_EXAMPLE_GATEWAY_CONFIG)
    assert config.tool_profile == "messaging"
    assert config.platforms.telegram.enabled is True
    assert config.platforms.telegram.allowed_users


def test_load_gateway_config_error_redacts_bot_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation errors must not echo expanded bot_token values."""
    monkeypatch.setenv("GATEWAY_TEST_BOT_TOKEN", "super-secret-token-value")
    config_file = tmp_path / "gateway.yaml"
    _write_gateway_yaml(
        config_file,
        _minimal_gateway_yaml(bot_token="${GATEWAY_TEST_BOT_TOKEN}")
        + "    allowed_users: not-a-list\n",
    )
    with pytest.raises(ConfigError) as exc_info:
        load_gateway_config(config_path=config_file)

    message = str(exc_info.value)
    assert "super-secret-token-value" not in message
    assert "[REDACTED]" in message
