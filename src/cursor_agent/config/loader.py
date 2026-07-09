"""Typed configuration loader for cursor-agent (PRD-002 FR-9, ADR-007).

Precedence (highest to lowest): CLI overrides > env ``CURSOR_AGENT__*`` >
``~/.cursor-agent/config.yaml`` > model defaults.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
from pydantic_settings.sources import InitSettingsSource

from cursor_agent.config.yaml_io import expand_vars, load_yaml_dict, normalize_keys
from cursor_agent.errors import ConfigError
from cursor_agent.first_party_models import DEFAULT_AGENT_MODEL
from cursor_agent.mcp_registry import (
    ALLOWED_GITHUB_TRANSPORTS,
    CURATED_MCP_SERVER_IDS,
    GithubTransport as GithubTransport,
)

DEFAULT_CONFIG_PATH = Path.home() / ".cursor-agent" / "config.yaml"
_ENV_PREFIX = "CURSOR_AGENT__"

RuntimeMode = Literal["local", "cloud"]
ToolProfile = Literal["coding", "messaging", "full"]


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


class McpFullConfig(BaseModel):
    """Allowlist and github transport for curated MCP under ``tool_profile: full``.

    ``servers=None`` means enable every curated id. Unknown ids raise with the
    received value and the allowed set from ``CURATED_MCP_SERVER_IDS``.
    ``github_transport`` defaults to official remote HTTP; ``stdio`` selects
    Docker (Wave 5 / ADR-029).

    Example:
        >>> McpFullConfig(servers=["github", "playwright"]).servers
        ['github', 'playwright']
        >>> McpFullConfig().github_transport
        'http'
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    servers: list[str] | None = None
    github_transport: GithubTransport = "http"

    @field_validator("servers")
    @classmethod
    def _reject_unknown_curated_server_ids(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        """Reject allowlist entries outside the curated registry."""
        if value is None:
            return None
        allowed = sorted(CURATED_MCP_SERVER_IDS)
        for server_id in value:
            if server_id not in CURATED_MCP_SERVER_IDS:
                raise ValueError(
                    f"unknown mcp.full.servers id: received {server_id!r}, "
                    f"expected one of {allowed!r}",
                )
        return value

    @field_validator("github_transport", mode="before")
    @classmethod
    def _reject_invalid_github_transport(cls, value: object) -> object:
        """Normalize case then reject transports outside {http, stdio}."""
        # Operators often type HTTP/STDIO; lowercase before the allowlist check.
        normalized: object = value.lower() if isinstance(value, str) else value
        if normalized not in ALLOWED_GITHUB_TRANSPORTS:
            allowed = ", ".join(sorted(ALLOWED_GITHUB_TRANSPORTS))
            raise ValueError(
                f"invalid mcp.full.github_transport: received {value!r}, "
                f"expected one of {{{allowed}}}",
            )
        return normalized


class McpConfig(BaseModel):
    """Nested MCP configuration block (required under ``extra='forbid'``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    full: McpFullConfig = Field(default_factory=McpFullConfig)


class CursorAgentConfig(BaseSettings):
    """Validated cursor-agent configuration (FR-10 minimal fields).

    Loaded via pydantic-settings v2 with ADR-007 source precedence.

    Example:
        >>> config = load_config(config_path=Path("/tmp/missing.yaml"))
        >>> config.model
        'grok-4.5'
    """

    model_config = SettingsConfigDict(
        env_prefix=_ENV_PREFIX,
        env_nested_delimiter="__",
        env_file=None,
        extra="forbid",
        frozen=True,
        nested_model_default_partial_update=True,
    )

    model: str = DEFAULT_AGENT_MODEL
    tool_profile: ToolProfile = "coding"
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    memory_root: str | None = None
    mcp: McpConfig = Field(default_factory=McpConfig)

    @model_validator(mode="before")
    @classmethod
    def _expand_environment_placeholders(cls, data: Any) -> Any:
        """Expand ``${VAR}`` placeholders after all settings sources merge (ADR-007)."""
        return expand_vars(data)


class YamlSettingsSource(InitSettingsSource):
    """YAML file settings source with ADR-007 shape validation and key normalization."""

    def __init__(self, settings_cls: type[BaseSettings], config_path: Path) -> None:
        yaml_data = load_yaml_dict(config_path, config_label="config")
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
    init_kwargs = normalize_keys(dict(cli_overrides)) if cli_overrides else {}

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
