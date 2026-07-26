"""Gateway YAML configuration models and loader (ADR-007)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

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
from cursor_agent.first_party_models import DEFAULT_AGENT_MODEL

DEFAULT_GATEWAY_CONFIG_PATH = Path.home() / ".cursor-agent" / "gateway.yaml"
MESSAGING_TOOL_PROFILE: ToolProfile = "messaging"

_DEFAULT_SETTING_SOURCES: list[str] = ["project", "user"]
_DEFAULT_RUNTIME_MODE: RuntimeMode = "local"
_REDACTED_SECRET = "[REDACTED]"
_SENSITIVE_PLATFORM_FIELDS = frozenset({"bot_token"})
# WHY: PyYAML YAMLError embeds the offending line (e.g. ``bot_token: "sekret``)
# before Pydantic can sanitize — redact YAML key values in ConfigError text.
_BOT_TOKEN_YAML_VALUE_RE = re.compile(
    r"(?P<prefix>\bbot_token\s*:\s*)(?P<value>\S+)",
    flags=re.IGNORECASE,
)
# Telegram bot tokens look like ``123456789:AAH...``; redact if they leak raw.
_TELEGRAM_BOT_TOKEN_SHAPE_RE = re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{20,}\b")


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
    model: str = DEFAULT_AGENT_MODEL
    memory_root: str | None = None
    platforms: PlatformsConfig = Field(default_factory=PlatformsConfig)


def _loc_includes_sensitive_field(loc: Sequence[object]) -> bool:
    """Return True when a Pydantic error location includes a sensitive field name."""
    return any(
        isinstance(part, str) and part in _SENSITIVE_PLATFORM_FIELDS for part in loc
    )


def _sanitize_validation_error_details(
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Redact secret ``input`` values from Pydantic ValidationError error dicts.

    WHY: ``exc.errors()`` embeds raw ``input`` even when received-data is redacted;
    invalid shapes (lists, nested values) must not leak via ConfigError messages.
    """
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        item = dict(error)
        loc = item.get("loc", ())
        if isinstance(loc, Sequence) and _loc_includes_sensitive_field(loc):
            if "input" in item:
                item["input"] = _REDACTED_SECRET
        sanitized.append(item)
    return sanitized


def _redact_gateway_config_data(data: object) -> object:
    """Return a copy of raw gateway YAML data with secret fields redacted.

    Always redacts sensitive keys when present (including empty / non-string
    nested values) so error payloads never echo secret-looking shapes.
    """
    if isinstance(data, Mapping):
        redacted: dict[str, object] = {}
        for key, value in data.items():
            if key in _SENSITIVE_PLATFORM_FIELDS:
                redacted[key] = _REDACTED_SECRET
            else:
                redacted[key] = _redact_gateway_config_data(value)
        return redacted
    if isinstance(data, list):
        return [_redact_gateway_config_data(item) for item in data]
    return data


def _redact_secrets_in_error_text(message: str) -> str:
    """Redact secret-bearing substrings from gateway ConfigError text.

    Covers YAML parse errors that echo ``bot_token: <value>`` and known
    Telegram bot-token shapes, without altering unrelated YAML diagnostics.

    Example::

        safe = _redact_secrets_in_error_text('bot_token: "sekretTok9')
        assert "sekretTok9" not in safe
    """
    redacted = _BOT_TOKEN_YAML_VALUE_RE.sub(
        rf"\g<prefix>{_REDACTED_SECRET}",
        message,
    )
    return _TELEGRAM_BOT_TOKEN_SHAPE_RE.sub(_REDACTED_SECRET, redacted)


def enabled_platform_names(gateway_config: GatewayConfig) -> list[str]:
    """Return platform names marked ``enabled: true`` in gateway config."""
    names: list[str] = []
    if gateway_config.platforms.telegram.enabled:
        names.append("telegram")
    return names


def load_gateway_config(config_path: Path | None = None) -> GatewayConfig:
    """Load and validate gateway configuration from YAML."""
    path = config_path if config_path is not None else DEFAULT_GATEWAY_CONFIG_PATH
    try:
        data = expand_vars(load_yaml_dict(path, config_label="gateway config"))
    except ConfigError as exc:
        raise ConfigError(_redact_secrets_in_error_text(str(exc))) from exc
    try:
        return GatewayConfig.model_validate(data)
    except ValidationError as exc:
        safe_errors = _sanitize_validation_error_details(exc.errors(include_url=False))
        safe_data = _redact_gateway_config_data(data)
        raise ConfigError(
            _redact_secrets_in_error_text(
                f"invalid gateway configuration: {safe_errors!r}, "
                f"received data {safe_data!r}"
            ),
        ) from exc


def to_cursor_agent_config(gateway_config: GatewayConfig) -> CursorAgentConfig:
    """Convert gateway config into ``CursorAgentConfig`` for CLI stack reuse.

    Honors the ``model`` key from ``gateway.yaml`` (defaulting to the package
    default model) and otherwise uses package defaults only — ignores
    ``CURSOR_AGENT__*`` and ``~/.cursor-agent/config.yaml`` so ``gateway.yaml``
    stays the sole surface.

    Refuses any profile other than ``messaging`` so direct callers cannot bypass
    ``resolve_gateway_startup_config``.
    """
    if gateway_config.tool_profile != MESSAGING_TOOL_PROFILE:
        raise ConfigError(
            f"invalid gateway tool_profile: received {gateway_config.tool_profile!r}, "
            f"expected {MESSAGING_TOOL_PROFILE!r}",
        )
    return CursorAgentConfig(
        model=gateway_config.model,
        tool_profile=gateway_config.tool_profile,
        memory_root=gateway_config.memory_root,
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
    return to_cursor_agent_config(gateway_config)
