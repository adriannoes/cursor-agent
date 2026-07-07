"""Effective config view with source attribution and redaction (PRD-013, ADR-028).

Builds a typed snapshot of resolved settings after ADR-007 merge, attributing
each field to ``shell`` / ``env`` / ``yaml`` / ``default`` via membership probes.
Secrets are never returned raw — only a redaction token for display.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Iterator, Literal

from dotenv import dotenv_values

from cursor_agent.config.loader import ToolProfile, load_config
from cursor_agent.config.yaml_io import load_yaml_dict

ConfigSourceLabel = Literal["shell", "env", "yaml", "default"]

REDACTION_TOKEN: Final[str] = "***"
_DEFAULT_SESSIONS_DB: Final[Path] = Path.home() / ".cursor-agent" / "sessions.db"

_ENV_KEY_MODEL: Final[str] = "CURSOR_AGENT__MODEL"
_ENV_KEY_TOOL_PROFILE: Final[str] = "CURSOR_AGENT__TOOL_PROFILE"
_ENV_KEY_MEMORY_ROOT: Final[str] = "CURSOR_AGENT__MEMORY_ROOT"
_ENV_KEY_WORKSPACE: Final[str] = "CURSOR_AGENT__RUNTIME__LOCAL__CWD"
_ENV_KEY_API_KEY: Final[str] = "CURSOR_API_KEY"
_ENV_KEY_SESSIONS_DB: Final[str] = "CURSOR_AGENT_SESSIONS_DB"


@dataclass(frozen=True, slots=True)
class EffectiveConfigView:
    """Typed effective settings with per-field provenance for ``setup show``.

    Example:
        >>> # view = build_effective_config(config_path=..., environ={}, dotenv_path=...)
        >>> # view.sources["api_key"]
        'env'
    """

    workspace: str
    model: str
    tool_profile: ToolProfile
    api_key_present: bool
    api_key_redacted: str | None
    memory_root: str | None
    sessions_db: str
    sources: Mapping[str, ConfigSourceLabel]


def build_effective_config(
    *,
    config_path: Path,
    environ: Mapping[str, str],
    dotenv_path: Path | None = None,
) -> EffectiveConfigView:
    """Resolve effective config with source labels using injectable env and paths.

    Applies CWD ``.env`` semantics (``override=False``: process env wins) into a
    temporary environ, then calls ``load_config`` so ADR-007 precedence is reused.
    Source attribution probes shell / dotenv / YAML membership — it does not
    reimplement merge.

    Args:
        config_path: YAML path (missing file treated as empty, same as loader).
        environ: Process environment mapping (injectable; never read real secrets).
        dotenv_path: Optional ``.env`` path; missing file is treated as empty.

    Returns:
        Frozen ``EffectiveConfigView`` with redacted API key and source map.

    Example:
        >>> # build_effective_config(config_path=Path("c.yaml"), environ={}, dotenv_path=Path(".env"))
    """
    process_environ = {str(key): str(value) for key, value in environ.items()}
    dotenv_map = _read_dotenv_map(dotenv_path)
    merged = _merge_environ_override_false(process_environ, dotenv_map)
    yaml_data = load_yaml_dict(config_path, config_label="config")

    with _temporary_environ(merged):
        config = load_config(config_path=config_path)

    api_key_present = bool(merged.get(_ENV_KEY_API_KEY, "").strip())
    sessions_override = merged.get(_ENV_KEY_SESSIONS_DB, "").strip()
    sessions_db = (
        str(Path(sessions_override).expanduser())
        if sessions_override
        else str(_DEFAULT_SESSIONS_DB)
    )

    sources: dict[str, ConfigSourceLabel] = {
        "model": _attribute_agent_field_source(
            env_key=_ENV_KEY_MODEL,
            yaml_has="model" in yaml_data,
            process_environ=process_environ,
            dotenv_keys=dotenv_map,
        ),
        "tool_profile": _attribute_agent_field_source(
            env_key=_ENV_KEY_TOOL_PROFILE,
            yaml_has="tool_profile" in yaml_data,
            process_environ=process_environ,
            dotenv_keys=dotenv_map,
        ),
        "workspace": _attribute_agent_field_source(
            env_key=_ENV_KEY_WORKSPACE,
            yaml_has=_yaml_has_runtime_local_cwd(yaml_data),
            process_environ=process_environ,
            dotenv_keys=dotenv_map,
        ),
        "memory_root": _attribute_agent_field_source(
            env_key=_ENV_KEY_MEMORY_ROOT,
            yaml_has="memory_root" in yaml_data,
            process_environ=process_environ,
            dotenv_keys=dotenv_map,
        ),
        "api_key": _attribute_flat_env_source(
            env_key=_ENV_KEY_API_KEY,
            process_environ=process_environ,
            dotenv_keys=dotenv_map,
        ),
        "sessions_db": _attribute_flat_env_source(
            env_key=_ENV_KEY_SESSIONS_DB,
            process_environ=process_environ,
            dotenv_keys=dotenv_map,
        ),
    }

    return EffectiveConfigView(
        workspace=config.runtime.local.cwd,
        model=config.model,
        tool_profile=config.tool_profile,
        api_key_present=api_key_present,
        api_key_redacted=REDACTION_TOKEN if api_key_present else None,
        memory_root=config.memory_root,
        sessions_db=sessions_db,
        sources=sources,
    )


def render_effective_config_redacted(view: EffectiveConfigView) -> str:
    """Format an effective config view for CLI stdout with secrets redacted.

    Args:
        view: Result of ``build_effective_config``.

    Returns:
        Multi-line English summary safe for display (API key never raw).

    Example:
        >>> # print(render_effective_config_redacted(view))
    """
    api_key_display = view.api_key_redacted if view.api_key_present else "(unset)"
    memory_display = view.memory_root if view.memory_root is not None else "(unset)"
    lines = [
        "Effective configuration",
        f"  model: {view.model} (source: {view.sources['model']})",
        f"  tool_profile: {view.tool_profile} (source: {view.sources['tool_profile']})",
        f"  workspace: {view.workspace} (source: {view.sources['workspace']})",
        f"  memory_root: {memory_display} (source: {view.sources['memory_root']})",
        f"  sessions_db: {view.sessions_db} (source: {view.sources['sessions_db']})",
        f"  api_key: {api_key_display} (source: {view.sources['api_key']})",
    ]
    return "\n".join(lines) + "\n"


def _read_dotenv_map(dotenv_path: Path | None) -> dict[str, str]:
    """Parse a ``.env`` file into a string map without mutating ``os.environ``."""
    if dotenv_path is None or not dotenv_path.is_file():
        return {}
    raw = dotenv_values(dotenv_path)
    return {
        str(key): str(value)
        for key, value in raw.items()
        if key is not None and value is not None
    }


def _merge_environ_override_false(
    process_environ: Mapping[str, str],
    dotenv_map: Mapping[str, str],
) -> dict[str, str]:
    """Merge dotenv into process env with ``load_dotenv(..., override=False)`` semantics."""
    merged = dict(process_environ)
    for key, value in dotenv_map.items():
        if key not in merged:
            merged[key] = value
    return merged


@contextmanager
def _temporary_environ(environ: Mapping[str, str]) -> Iterator[None]:
    """Replace ``os.environ`` for the duration of ``load_config`` (test isolation)."""
    previous = os.environ.copy()
    os.environ.clear()
    os.environ.update(environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _yaml_has_runtime_local_cwd(yaml_data: Mapping[str, object]) -> bool:
    """Return True when YAML defines ``runtime.local.cwd``."""
    runtime = yaml_data.get("runtime")
    if not isinstance(runtime, dict):
        return False
    local = runtime.get("local")
    if not isinstance(local, dict):
        return False
    return "cwd" in local


def _attribute_agent_field_source(
    *,
    env_key: str,
    yaml_has: bool,
    process_environ: Mapping[str, str],
    dotenv_keys: Collection[str],
) -> ConfigSourceLabel:
    """Attribute a ``CURSOR_AGENT__*`` field: shell > env > yaml > default."""
    if env_key in process_environ:
        return "shell"
    if env_key in dotenv_keys:
        return "env"
    if yaml_has:
        return "yaml"
    return "default"


def _attribute_flat_env_source(
    *,
    env_key: str,
    process_environ: Mapping[str, str],
    dotenv_keys: Collection[str],
) -> ConfigSourceLabel:
    """Attribute a flat env-only field (API key / sessions db): shell > env > default."""
    if env_key in process_environ:
        return "shell"
    if env_key in dotenv_keys:
        return "env"
    return "default"
