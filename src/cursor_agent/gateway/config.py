"""Gateway YAML configuration models and loader (ADR-007)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cursor_agent.config.loader import (
    CursorAgentConfig,
    LocalRuntimeConfig,
    RuntimeConfig,
    RuntimeMode,
    ToolProfile,
)
from cursor_agent.config.yaml_io import expand_vars, load_yaml_dict
from cursor_agent.errors import ConfigError

DEFAULT_GATEWAY_CONFIG_PATH = Path.home() / ".cursor-agent" / "gateway.yaml"
MESSAGING_TOOL_PROFILE: ToolProfile = "messaging"

_DEFAULT_SETTING_SOURCES: list[str] = ["project", "user"]
_DEFAULT_MODEL = "composer-2.5"
_DEFAULT_RUNTIME_MODE: RuntimeMode = "local"


class TelegramPlatformConfig(BaseModel):
    """Telegram platform block in gateway.yaml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    bot_token: str = ""
    allowed_users: list[int] = Field(default_factory=list)


class PlatformsConfig(BaseModel):
    """Per-platform configuration blocks under ``platforms``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    telegram: TelegramPlatformConfig = Field(default_factory=TelegramPlatformConfig)


class GatewayConfig(BaseModel):
    """Validated gateway YAML configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace: str
    tool_profile: ToolProfile
    platforms: PlatformsConfig = Field(default_factory=PlatformsConfig)


def load_gateway_config(config_path: Path | None = None) -> GatewayConfig:
    """Load and validate gateway configuration from YAML."""
    path = config_path if config_path is not None else DEFAULT_GATEWAY_CONFIG_PATH
    data = expand_vars(load_yaml_dict(path, config_label="gateway config"))
    try:
        return GatewayConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(
            f"invalid gateway configuration: {exc.errors(include_url=False)!r}, "
            f"received data {data!r}",
        ) from exc


def to_cursor_agent_config(gateway_config: GatewayConfig) -> CursorAgentConfig:
    """Convert gateway config into ``CursorAgentConfig`` for CLI stack reuse.

    Uses package defaults only — ignores ``CURSOR_AGENT__*`` and
    ``~/.cursor-agent/config.yaml`` so ``gateway.yaml`` stays the sole surface.
    """
    return CursorAgentConfig(
        model=_DEFAULT_MODEL,
        tool_profile=gateway_config.tool_profile,
        runtime=RuntimeConfig(
            mode=_DEFAULT_RUNTIME_MODE,
            local=LocalRuntimeConfig(
                cwd=gateway_config.workspace,
                setting_sources=list(_DEFAULT_SETTING_SOURCES),
            ),
        ),
    )


def resolve_gateway_startup_config(gateway_config: GatewayConfig) -> CursorAgentConfig:
    """Validate messaging profile and convert gateway config for CLI stack reuse."""
    if gateway_config.tool_profile != MESSAGING_TOOL_PROFILE:
        raise ConfigError(
            f"invalid gateway tool_profile: received {gateway_config.tool_profile!r}, "
            f"expected {MESSAGING_TOOL_PROFILE!r}",
        )
    return to_cursor_agent_config(gateway_config)
