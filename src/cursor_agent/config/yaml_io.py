"""Shared YAML load, key normalization, and env expansion (ADR-007)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from cursor_agent.errors import ConfigError


def load_yaml_dict(
    config_path: Path, *, config_label: str = "config"
) -> dict[str, Any]:
    """Load a YAML mapping from disk; missing or empty files yield ``{}``.

    Args:
        config_path: Path to the YAML file.
        config_label: Human-readable label for error messages (for example
            ``"gateway config"``).

    Returns:
        Normalized top-level mapping.

    Raises:
        ConfigError: YAML syntax or shape is invalid.
    """
    if not config_path.is_file():
        return {}
    raw = config_path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"invalid YAML in {config_label} file {config_path!s}: {exc!s}",
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"invalid {config_label} YAML shape: expected top-level mapping, "
            f"received {type(data).__name__!r}",
        )
    normalized = normalize_keys(data)
    if not isinstance(normalized, dict):
        raise ConfigError(
            f"invalid {config_label} YAML shape: expected top-level mapping after "
            f"normalization, received {type(normalized).__name__!r}",
        )
    return normalized


def normalize_keys(value: object) -> Any:
    """Normalize mapping keys to lowercase for consistent merge."""
    if isinstance(value, dict):
        return {
            (key.lower() if isinstance(key, str) else key): normalize_keys(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [normalize_keys(item) for item in value]
    return value


def expand_vars(value: object) -> object:
    """Expand ``${VAR}`` placeholders using ``os.path.expandvars``."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {key: expand_vars(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [expand_vars(item) for item in value]
    return value
