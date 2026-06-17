"""Typed configuration loader for cursor-agent (PRD-002 FR-9, ADR-007).

Precedence (highest to lowest): CLI overrides > env ``CURSOR_AGENT__*`` >
``~/.cursor-agent/config.yaml`` > model defaults.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import InitSettingsSource

from cursor_agent.errors import ConfigError

DEFAULT_CONFIG_PATH = Path.home() / ".cursor-agent" / "config.yaml"
_ENV_PREFIX = "CURSOR_AGENT__"

RuntimeMode = Literal["local", "cloud"]
ToolProfile = Literal["coding", "messaging"]


class LocalRuntimeConfig(BaseModel):
    """Local runtime workspace and SDK setting source paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cwd: str = "."
    setting_sources: list[str] = Field(default_factory=lambda: ["project", "user"])


class RuntimeConfig(BaseModel):
    """Runtime mode and mode-specific settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: RuntimeMode = "local"
    local: LocalRuntimeConfig = Field(default_factory=LocalRuntimeConfig)


class CursorAgentConfig(BaseSettings):
    """Validated cursor-agent configuration (FR-10 minimal fields).

    Loaded via pydantic-settings v2 with ADR-007 source precedence.

    Example:
        >>> config = load_config(config_path=Path("/tmp/missing.yaml"))
        >>> config.model
        'composer-2.5'
    """

    model_config = SettingsConfigDict(
        env_prefix=_ENV_PREFIX,
        env_nested_delimiter="__",
        env_file=None,
        extra="forbid",
        frozen=True,
        nested_model_default_partial_update=True,
    )

    model: str = "composer-2.5"
    tool_profile: ToolProfile = "coding"
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    @model_validator(mode="before")
    @classmethod
    def _expand_environment_placeholders(cls, data: Any) -> Any:
        """Expand ``${VAR}`` placeholders after all settings sources merge (ADR-007)."""
        return _expand_vars(data)


class YamlSettingsSource(InitSettingsSource):
    """YAML file settings source with ADR-007 shape validation and key normalization."""

    def __init__(self, settings_cls: type[BaseSettings], config_path: Path) -> None:
        yaml_data = _load_yaml_dict(config_path)
        super().__init__(settings_cls, init_kwargs=yaml_data)


def load_config(
    config_path: Path | None = None,
    cli_overrides: Mapping[str, object] | None = None,
) -> CursorAgentConfig:
    """Load and validate configuration using ADR-007 precedence.

    Args:
        config_path: YAML file path; absent file is treated as empty mapping.
        cli_overrides: Highest-precedence nested mapping (e.g. Typer flags).

    Returns:
        Frozen ``CursorAgentConfig`` instance.

    Raises:
        ConfigError: YAML shape or validation failed (includes offending value).
    """
    path = config_path if config_path is not None else DEFAULT_CONFIG_PATH
    init_kwargs = _normalize_keys(dict(cli_overrides)) if cli_overrides else {}

    class _BoundCursorAgentConfig(CursorAgentConfig):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            yaml_settings = YamlSettingsSource(settings_cls, path)
            return (init_settings, env_settings, yaml_settings)

    try:
        return _BoundCursorAgentConfig(**init_kwargs)
    except ValidationError as exc:
        raise ConfigError(
            f"invalid configuration: {exc.errors(include_url=False)!r}, "
            f"received init overrides {init_kwargs!r}",
        ) from exc


def _load_yaml_dict(config_path: Path) -> dict[str, Any]:
    """Load YAML mapping from disk; missing file yields empty dict."""
    if not config_path.is_file():
        return {}
    raw = config_path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"invalid YAML in config file {config_path!s}: {exc!s}",
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"invalid config YAML shape: expected top-level mapping, "
            f"received {type(data).__name__!r}",
        )
    normalized = _normalize_keys(data)
    if not isinstance(normalized, dict):
        raise ConfigError(
            f"invalid config YAML shape: expected top-level mapping after "
            f"normalization, received {type(normalized).__name__!r}",
        )
    return normalized


def _normalize_keys(value: object) -> Any:
    """Normalize mapping keys to lowercase for consistent merge."""
    if isinstance(value, dict):
        return {
            (key.lower() if isinstance(key, str) else key): _normalize_keys(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_normalize_keys(item) for item in value]
    return value


def _expand_vars(value: object) -> object:
    """Expand ``${VAR}`` placeholders using ``os.path.expandvars``."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {key: _expand_vars(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_expand_vars(item) for item in value]
    return value
