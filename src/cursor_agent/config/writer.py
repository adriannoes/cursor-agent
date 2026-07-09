"""Atomic config YAML and ``.env`` merge writers (PRD-013, ADR-028).

Secrets never land in YAML. Persistence uses temp file in the same parent
directory plus ``os.replace`` — matching ``first_run_marker`` / cron store.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import yaml

from cursor_agent.config.loader import ToolProfile
from cursor_agent.errors import ConfigError

CONFIG_HOME_MODE: Final[int] = 0o700
ENV_FILE_MODE: Final[int] = 0o600
_ALLOWED_ENV_KEYS: Final[frozenset[str]] = frozenset(
    {
        "CURSOR_API_KEY",
        "CURSOR_AGENT_SESSIONS_DB",
    }
)
_VALID_TOOL_PROFILES: Final[frozenset[str]] = frozenset({"coding", "messaging", "full"})
_MEMORY_PLACEHOLDER_FILES: Final[tuple[str, ...]] = ("USER.md", "MEMORY.md")
_ENV_KEY_LINE_PATTERN = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=)(.*)$")


@dataclass(frozen=True, slots=True)
class WriteConfigResult:
    """Outcome of a config YAML or ``.env`` write attempt.

    Example:
        >>> WriteConfigResult(changed=False, path=Path("/tmp/config.yaml"))
        WriteConfigResult(changed=False, path=PosixPath('/tmp/config.yaml'), backup_path=None)
    """

    changed: bool
    path: Path
    backup_path: Path | None = None


def write_config_yaml(
    path: Path,
    updates: Mapping[str, object],
) -> WriteConfigResult:
    """Merge-update YAML config on disk with an atomic replace.

    Supported top-level keys: ``model``, ``memory_root``, ``tool_profile``,
    and nested ``runtime.local.cwd``. Creates the parent directory with mode
    ``0o700`` when missing. Idempotent when persisted state already matches.

    Args:
        path: Destination YAML path (injectable; default home is caller's choice).
        updates: Partial mapping of config fields to set.

    Returns:
        ``WriteConfigResult`` with ``changed=False`` when content already matches.

    Raises:
        ConfigError: Invalid paths, tool profile, or I/O failure.

    Example:
        >>> # write_config_yaml(Path("/tmp/c.yaml"), {"model": "composer-2.5"})
    """
    validated = _validate_yaml_updates(updates)
    parent = path.parent
    _ensure_config_home(parent)

    existing = _load_existing_yaml(path)
    merged = _deep_merge_mappings(existing, validated)

    if path.is_file() and _yaml_content_matches(path, merged):
        return WriteConfigResult(changed=False, path=path)

    serialized = yaml.safe_dump(
        merged,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    _atomic_replace_text(path, serialized)
    return WriteConfigResult(changed=True, path=path)


def merge_env_file(
    path: Path,
    updates: Mapping[str, str],
    *,
    force: bool = False,
) -> WriteConfigResult:
    """Merge allowlisted keys into a ``.env`` file with refuse/force/backup.

    Only ``CURSOR_API_KEY`` and ``CURSOR_AGENT_SESSIONS_DB`` are accepted.
    Updates the first matching ``KEY=`` line; appends when absent. Differing
    values refuse without ``force=True``; with force, creates one timestamped
    ``.env.bak.{YYYYMMDD-HHMMSS}`` before mutation.

    Args:
        path: Destination ``.env`` path.
        updates: Key/value pairs to merge (values never logged).
        force: When ``True``, overwrite differing values after backup.

    Returns:
        ``WriteConfigResult`` including optional ``backup_path``.

    Raises:
        ConfigError: Disallowed key, empty API key, refuse-without-force, or I/O.

    Example:
        >>> # merge_env_file(Path("/tmp/.env"), {"CURSOR_API_KEY": "sk-test"})
    """
    allowlisted = _validate_env_updates(updates)
    existing_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    planned, needs_backup = _plan_env_merge(
        existing_text,
        allowlisted,
        force=force,
        env_path=path,
    )
    if planned is None:
        return WriteConfigResult(changed=False, path=path)

    backup_path: Path | None = None
    if needs_backup:
        backup_path = _write_env_backup(path, existing_text)

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_replace_text(path, planned)
    _chmod_best_effort(path, ENV_FILE_MODE)
    return WriteConfigResult(changed=True, path=path, backup_path=backup_path)


def check_env_merge_allowed(
    path: Path,
    updates: Mapping[str, str],
    *,
    force: bool = False,
) -> None:
    """Raise ``ConfigError`` when ``merge_env_file`` would refuse; no FS writes.

    Used by setup apply to preflight refuse-without-force before YAML mutation
    so a refused env overwrite cannot leave orphan ``config.yaml`` / memory files.

    Args:
        path: Destination ``.env`` path (read-only probe).
        updates: Key/value pairs that would be merged.
        force: Same semantics as ``merge_env_file``.

    Raises:
        ConfigError: Disallowed key, empty API key, or refuse-without-force.

    Example:
        >>> # check_env_merge_allowed(Path("/tmp/.env"), {"CURSOR_API_KEY": "sk"})
    """
    allowlisted = _validate_env_updates(updates)
    existing_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    _plan_env_merge(
        existing_text,
        allowlisted,
        force=force,
        env_path=path,
    )


def _validate_yaml_updates(updates: Mapping[str, object]) -> dict[str, object]:
    """Validate and normalize YAML field updates before merge."""
    if not updates:
        raise ConfigError(
            f"invalid config updates: received empty mapping {updates!r}, "
            "expected at least one of model, memory_root, tool_profile, "
            "runtime.local.cwd",
        )

    result: dict[str, object] = {}
    for key, value in updates.items():
        if key == "model":
            result["model"] = _require_non_empty_str(value, field_name="model")
        elif key == "memory_root":
            memory_root = _require_non_empty_str(value, field_name="memory_root")
            _ensure_memory_root(Path(memory_root))
            result["memory_root"] = memory_root
        elif key == "tool_profile":
            result["tool_profile"] = _validate_tool_profile(value)
        elif key == "runtime":
            result["runtime"] = _validate_runtime_update(value)
        else:
            raise ConfigError(
                f"unsupported config YAML key: received {key!r}, "
                "expected one of model, memory_root, tool_profile, runtime",
            )
    return result


def _validate_runtime_update(value: object) -> dict[str, object]:
    """Validate nested ``runtime.local.cwd`` and return a mergeable mapping."""
    if not isinstance(value, Mapping):
        raise ConfigError(
            f"invalid runtime update: received {value!r}, expected mapping "
            "with local.cwd",
        )
    local = value.get("local")
    if not isinstance(local, Mapping):
        raise ConfigError(
            f"invalid runtime.local update: received {local!r}, expected mapping "
            "with cwd",
        )
    if "cwd" not in local:
        raise ConfigError(
            f"invalid runtime.local update: received keys {sorted(local)!r}, "
            "expected cwd",
        )
    cwd_raw = _require_non_empty_str(local["cwd"], field_name="runtime.local.cwd")
    cwd_path = Path(cwd_raw)
    if not cwd_path.is_dir():
        raise ConfigError(
            f"invalid workspace path: received {cwd_raw!r}, "
            "expected existing directory",
        )
    return {"local": {"cwd": str(cwd_path)}}


def validate_tool_profile(value: object) -> ToolProfile:
    """Accept ``coding``, ``messaging``, or ``full`` (public for wizard early checks).

    Example:
        >>> validate_tool_profile("coding")
        'coding'
    """
    if not isinstance(value, str) or value not in _VALID_TOOL_PROFILES:
        raise ConfigError(
            f"invalid tool_profile: received {value!r}, "
            "expected 'coding', 'messaging', or 'full'",
        )
    return value  # type: ignore[return-value]


def _validate_tool_profile(value: object) -> ToolProfile:
    """Accept ``coding``, ``messaging``, or ``full``."""
    return validate_tool_profile(value)


def _require_non_empty_str(value: object, *, field_name: str) -> str:
    """Require a non-empty stripped string for a named field."""
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"invalid {field_name}: received {value!r}, expected non-empty string",
        )
    return value.strip()


def _ensure_config_home(config_home: Path) -> None:
    """Create config home with ``0o700`` when missing."""
    if config_home.exists():
        return
    try:
        config_home.mkdir(parents=True, mode=CONFIG_HOME_MODE, exist_ok=True)
        os.chmod(config_home, CONFIG_HOME_MODE)
    except OSError as exc:
        raise ConfigError(
            f"failed to create config home {config_home!s}: {exc}, "
            f"expected writable directory with mode {CONFIG_HOME_MODE:#o}",
        ) from exc


def _ensure_memory_root(memory_root: Path) -> None:
    """Create memory root and touch empty USER.md / MEMORY.md when missing."""
    try:
        memory_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(
            f"failed to create memory_root {memory_root!s}: {exc}, "
            "expected writable directory",
        ) from exc
    for filename in _MEMORY_PLACEHOLDER_FILES:
        placeholder = memory_root / filename
        if placeholder.exists():
            continue
        try:
            placeholder.write_text("", encoding="utf-8")
        except OSError as exc:
            raise ConfigError(
                f"failed to touch memory file {placeholder!s}: {exc}, "
                "expected writable path under memory_root",
            ) from exc


def _load_existing_yaml(path: Path) -> dict[str, object]:
    """Load existing YAML mapping; missing/empty file yields ``{}``."""
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"invalid YAML in config file {path!s}: {exc!s}",
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"invalid config YAML shape: expected top-level mapping, "
            f"received {type(data).__name__!r}",
        )
    return dict(data)


def _deep_merge_mappings(
    base: Mapping[str, object],
    updates: Mapping[str, object],
) -> dict[str, object]:
    """Deep-merge nested dicts; preserve unrelated keys from ``base``."""
    merged: dict[str, object] = dict(base)
    for key, value in updates.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge_mappings(existing, value)
        else:
            merged[key] = value
    return merged


def _yaml_content_matches(path: Path, merged: Mapping[str, object]) -> bool:
    """Return True when on-disk YAML equals the would-be merged mapping."""
    existing = _load_existing_yaml(path)
    return existing == dict(merged)


def _atomic_replace_text(destination: Path, content: str) -> None:
    """Write ``content`` via temp file in the same parent + ``os.replace``."""
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=parent,
    )
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise ConfigError(
            f"failed to write config file {destination!s}: {exc}, "
            "expected atomic replace under the destination parent directory",
        ) from exc


def _validate_env_updates(updates: Mapping[str, str]) -> dict[str, str]:
    """Validate allowlisted env keys and non-empty API key when present."""
    if not updates:
        raise ConfigError(
            f"invalid env updates: received empty mapping {updates!r}, "
            f"expected at least one of {sorted(_ALLOWED_ENV_KEYS)!r}",
        )
    validated: dict[str, str] = {}
    for key, value in updates.items():
        if key not in _ALLOWED_ENV_KEYS:
            raise ConfigError(
                f"unsupported env key for setup writer: received {key!r}, "
                f"expected one of {sorted(_ALLOWED_ENV_KEYS)!r}",
            )
        if not isinstance(value, str):
            raise ConfigError(
                f"invalid env value for {key}: received {value!r}, expected string",
            )
        if key == "CURSOR_API_KEY" and not value.strip():
            raise ConfigError(
                f"invalid CURSOR_API_KEY: received {value!r}, "
                "expected non-empty string",
            )
        validated[key] = value
    return validated


def _plan_env_merge(
    existing_text: str,
    updates: Mapping[str, str],
    *,
    force: bool,
    env_path: Path,
) -> tuple[str | None, bool]:
    """Plan merged ``.env`` text; return ``(None, False)`` when idempotent.

    Raises:
        ConfigError: Differing value without ``force``.
    """
    lines = existing_text.splitlines(keepends=True)
    first_index_by_key = _first_env_key_indices(lines)
    needs_backup = False
    changed = False

    for key, new_value in updates.items():
        if key in first_index_by_key:
            idx = first_index_by_key[key]
            current = _env_value_at_line(lines[idx])
            if current == new_value:
                continue
            if not force:
                raise ConfigError(
                    f"env key {key} already set to a different value in "
                    f"{env_path!s}: refuse overwrite without force=True; "
                    "run `cursor-agent setup show` to inspect effective config",
                )
            needs_backup = True
            lines[idx] = _replace_env_line_value(lines[idx], key, new_value)
            changed = True
        else:
            append_line = f"{key}={new_value}\n"
            if lines and not lines[-1].endswith("\n"):
                lines[-1] = f"{lines[-1]}\n"
            lines.append(append_line)
            first_index_by_key[key] = len(lines) - 1
            changed = True

    if not changed:
        return None, False
    return "".join(lines), needs_backup


def _first_env_key_indices(lines: list[str]) -> dict[str, int]:
    """Map env keys to the index of their first ``KEY=`` line."""
    indices: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = _ENV_KEY_LINE_PATTERN.match(line.rstrip("\n"))
        if match is None:
            continue
        key = match.group(2)
        if key not in indices:
            indices[key] = index
    return indices


def _env_value_at_line(line: str) -> str:
    """Extract the value portion of a ``KEY=value`` line."""
    stripped = line.rstrip("\n")
    match = _ENV_KEY_LINE_PATTERN.match(stripped)
    if match is None:
        return ""
    return match.group(4)


def _replace_env_line_value(line: str, key: str, new_value: str) -> str:
    """Replace value on the first matching KEY= line; keep leading whitespace."""
    newline = "\n" if line.endswith("\n") else ""
    stripped = line.rstrip("\n")
    match = _ENV_KEY_LINE_PATTERN.match(stripped)
    if match is None:
        return f"{key}={new_value}{newline}"
    prefix = match.group(1)
    equals = match.group(3)
    return f"{prefix}{key}{equals}{new_value}{newline}"


def _write_env_backup(path: Path, content: str) -> Path:
    """Create one timestamped ``.env.bak.{YYYYMMDD-HHMMSS}`` beside ``path``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak.{stamp}")
    try:
        backup_path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"failed to create env backup {backup_path!s}: {exc}, "
            "expected writable directory beside the env file",
        ) from exc
    _chmod_best_effort(backup_path, ENV_FILE_MODE)
    return backup_path


def _chmod_best_effort(path: Path, mode: int) -> None:
    """Best-effort chmod; ignore platforms or FS that reject the mode."""
    try:
        os.chmod(path, mode)
    except OSError:
        return
