"""Unit tests for config writer (PRD-013 Task 2.0, ADR-028).

Uses ``tmp_path`` only — never the real ``~/.cursor-agent``.
API key fixtures use placeholders such as ``sk-test-placeholder``.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from cursor_agent.config.writer import (
    WriteConfigResult,
    check_env_merge_allowed,
    merge_env_file,
    write_config_yaml,
)
from cursor_agent.errors import ConfigError

_PLACEHOLDER_API_KEY = "sk-test-placeholder"
_BACKUP_NAME_PATTERN = re.compile(r"^\.env\.bak\.\d{8}-\d{6}$")


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from disk for assertions."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_write_config_yaml_creates_file_with_expected_keys(tmp_path: Path) -> None:
    """FR-12: minimal YAML write includes model, runtime.local.cwd, tool_profile."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config_path = tmp_path / "config-home" / "config.yaml"

    result = write_config_yaml(
        config_path,
        {
            "model": "composer-2.5",
            "tool_profile": "coding",
            "runtime": {"local": {"cwd": str(workspace)}},
        },
    )

    assert isinstance(result, WriteConfigResult)
    assert result.changed is True
    assert result.path == config_path
    assert config_path.is_file()
    data = _load_yaml(config_path)
    assert data["model"] == "composer-2.5"
    assert data["tool_profile"] == "coding"
    assert data["runtime"]["local"]["cwd"] == str(workspace)


def test_write_config_yaml_creates_parent_dir_with_0o700(tmp_path: Path) -> None:
    """ADR-028 §3: config home is created with mode 0o700 when missing."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_home = tmp_path / "new-home"
    config_path = config_home / "config.yaml"

    write_config_yaml(
        config_path,
        {
            "model": "composer-2.5",
            "tool_profile": "coding",
            "runtime": {"local": {"cwd": str(workspace)}},
        },
    )

    assert config_home.is_dir()
    mode = stat.S_IMODE(config_home.stat().st_mode)
    assert mode == 0o700


def test_write_config_yaml_idempotent_second_write_changed_false(
    tmp_path: Path,
) -> None:
    """FR-17 / ADR-028 §4: identical YAML content returns changed=False."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    updates: dict[str, object] = {
        "model": "composer-2.5",
        "tool_profile": "messaging",
        "runtime": {"local": {"cwd": str(workspace)}},
    }

    first = write_config_yaml(config_path, updates)
    second = write_config_yaml(config_path, updates)

    assert first.changed is True
    assert second.changed is False
    assert _load_yaml(config_path)["tool_profile"] == "messaging"


def test_write_config_yaml_atomic_replace_failure_leaves_no_truncated_file(
    tmp_path: Path,
) -> None:
    """ADR-028 §2: failed os.replace cleans temp; existing content is preserved."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    original = (
        "model: original-model\n"
        "tool_profile: coding\n"
        "runtime:\n"
        "  local:\n"
        f"    cwd: {workspace}\n"
    )
    config_path.parent.mkdir(mode=0o700)
    config_path.write_text(original, encoding="utf-8")

    def _failing_replace(
        src: str | os.PathLike[str],
        dst: str | os.PathLike[str],
    ) -> None:
        raise OSError("simulated replace failure")

    with (
        patch("cursor_agent.config.writer.os.replace", side_effect=_failing_replace),
        pytest.raises(ConfigError, match="simulated replace failure"),
    ):
        write_config_yaml(
            config_path,
            {
                "model": "replaced-model",
                "tool_profile": "coding",
                "runtime": {"local": {"cwd": str(workspace)}},
            },
        )

    assert config_path.read_text(encoding="utf-8") == original
    leftovers = list(config_path.parent.glob(".config.yaml.*.tmp"))
    assert leftovers == []


# --- Task 2.3 / 2.4: .env merge, refuse, force backup ---


def test_merge_env_file_updates_existing_key_and_appends_new(
    tmp_path: Path,
) -> None:
    """FR-13: update existing KEY= lines and append absent keys."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment keep me\n"
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
        "OTHER_UNRELATED=keep\n",
        encoding="utf-8",
    )

    result = merge_env_file(
        env_path,
        {
            "CURSOR_API_KEY": _PLACEHOLDER_API_KEY,
            "CURSOR_AGENT_SESSIONS_DB": str(tmp_path / "sessions.db"),
        },
        force=False,
    )

    assert result.changed is True
    text = env_path.read_text(encoding="utf-8")
    assert "# comment keep me" in text
    assert "OTHER_UNRELATED=keep" in text
    assert f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}" in text
    assert f"CURSOR_AGENT_SESSIONS_DB={tmp_path / 'sessions.db'}" in text


def test_merge_env_file_preserves_comments_when_updating(tmp_path: Path) -> None:
    """ADR-028: preserve unrelated comments when merge-writing."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# header\nCURSOR_AGENT_SESSIONS_DB=/old/path\n# footer\n",
        encoding="utf-8",
    )

    merge_env_file(
        env_path,
        {"CURSOR_AGENT_SESSIONS_DB": "/new/path"},
        force=True,
    )

    text = env_path.read_text(encoding="utf-8")
    assert text.startswith("# header\n")
    assert "# footer" in text
    assert "CURSOR_AGENT_SESSIONS_DB=/new/path" in text


def test_merge_env_file_refuse_different_value_without_force(tmp_path: Path) -> None:
    """FR-9 / ADR-028 §5: differing env value refuses without force."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="cursor-agent setup show") as exc_info:
        merge_env_file(
            env_path,
            {"CURSOR_API_KEY": "sk-test-other-placeholder"},
            force=False,
        )

    assert "force" in str(exc_info.value).lower()
    assert env_path.read_text(encoding="utf-8") == (
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
    )


def test_check_env_merge_allowed_refuse_without_writing(tmp_path: Path) -> None:
    """Preflight refuse raises without mutating the env file."""
    env_path = tmp_path / ".env"
    original = f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
    env_path.write_text(original, encoding="utf-8")

    with pytest.raises(ConfigError, match="force"):
        check_env_merge_allowed(
            env_path,
            {"CURSOR_API_KEY": "sk-test-other-placeholder"},
            force=False,
        )

    assert env_path.read_text(encoding="utf-8") == original


def test_check_env_merge_allowed_passes_when_force_or_identical(
    tmp_path: Path,
) -> None:
    """Preflight is a no-op (no raise) for identical values or force=True."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n",
        encoding="utf-8",
    )

    check_env_merge_allowed(
        env_path,
        {"CURSOR_API_KEY": _PLACEHOLDER_API_KEY},
        force=False,
    )
    check_env_merge_allowed(
        env_path,
        {"CURSOR_API_KEY": "sk-test-other-placeholder"},
        force=True,
    )
    assert env_path.read_text(encoding="utf-8") == (
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
    )


def test_merge_env_file_force_creates_timestamped_backup_once(
    tmp_path: Path,
) -> None:
    """Q6 Accept C: force writes one timestamped .env.bak then updates."""
    env_path = tmp_path / ".env"
    original = f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
    env_path.write_text(original, encoding="utf-8")

    result = merge_env_file(
        env_path,
        {"CURSOR_API_KEY": "sk-test-forced-placeholder"},
        force=True,
    )

    assert result.changed is True
    assert result.backup_path is not None
    assert result.backup_path.parent == env_path.parent
    assert _BACKUP_NAME_PATTERN.match(result.backup_path.name)
    assert result.backup_path.read_text(encoding="utf-8") == original
    assert "sk-test-forced-placeholder" in env_path.read_text(encoding="utf-8")
    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == 1
    backup_mode = stat.S_IMODE(result.backup_path.stat().st_mode)
    assert backup_mode == 0o600


def test_merge_env_file_identical_value_is_idempotent(tmp_path: Path) -> None:
    """ADR-028 §4: same env value is a no-op with changed=False."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n",
        encoding="utf-8",
    )

    result = merge_env_file(
        env_path,
        {"CURSOR_API_KEY": _PLACEHOLDER_API_KEY},
        force=False,
    )

    assert result.changed is False
    assert result.backup_path is None
    assert list(tmp_path.glob(".env.bak.*")) == []


def test_merge_env_file_sets_mode_0o600_best_effort(tmp_path: Path) -> None:
    """ADR-028 §3: env file mode 0o600 after write when chmod is meaningful."""
    env_path = tmp_path / ".env"

    merge_env_file(
        env_path,
        {"CURSOR_API_KEY": _PLACEHOLDER_API_KEY},
        force=False,
    )

    mode = stat.S_IMODE(env_path.stat().st_mode)
    assert mode == 0o600


def test_merge_env_file_updates_first_duplicate_key_line(tmp_path: Path) -> None:
    """ADR-028 §10: write updates the first matching KEY= line only."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "CURSOR_AGENT_SESSIONS_DB=/first\nCURSOR_AGENT_SESSIONS_DB=/second\n",
        encoding="utf-8",
    )

    merge_env_file(
        env_path,
        {"CURSOR_AGENT_SESSIONS_DB": "/updated"},
        force=True,
    )

    lines = env_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "CURSOR_AGENT_SESSIONS_DB=/updated"
    assert lines[1] == "CURSOR_AGENT_SESSIONS_DB=/second"


# --- Task 2.5 / 2.6: path validation + memory_root touch ---


def test_write_config_yaml_rejects_nonexistent_workspace_with_ConfigError(
    tmp_path: Path,
) -> None:
    """FR-15: workspace must be an existing directory; message cites value."""
    missing = tmp_path / "does-not-exist"
    config_path = tmp_path / "home" / "config.yaml"

    with pytest.raises(ConfigError, match="does-not-exist") as exc_info:
        write_config_yaml(
            config_path,
            {"runtime": {"local": {"cwd": str(missing)}}},
        )

    message = str(exc_info.value)
    assert "expected existing directory" in message
    assert repr(str(missing)) in message or f"'{missing}'" in message


def test_write_config_yaml_rejects_file_as_workspace(tmp_path: Path) -> None:
    """FR-15: a regular file is not a valid workspace directory."""
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    config_path = tmp_path / "config.yaml"

    with pytest.raises(ConfigError, match="expected existing directory"):
        write_config_yaml(
            config_path,
            {"runtime": {"local": {"cwd": str(not_a_dir)}}},
        )


def test_write_config_yaml_memory_root_touches_empty_user_and_memory_md(
    tmp_path: Path,
) -> None:
    """Q2 Accept A: creating memory_root touches empty USER.md / MEMORY.md."""
    memory_root = tmp_path / "memory"
    config_path = tmp_path / "home" / "config.yaml"

    result = write_config_yaml(config_path, {"memory_root": str(memory_root)})

    assert result.changed is True
    assert memory_root.is_dir()
    user_md = memory_root / "USER.md"
    memory_md = memory_root / "MEMORY.md"
    assert user_md.is_file()
    assert memory_md.is_file()
    assert user_md.read_text(encoding="utf-8") == ""
    assert memory_md.read_text(encoding="utf-8") == ""
    assert _load_yaml(config_path)["memory_root"] == str(memory_root)


def test_write_config_yaml_memory_root_does_not_clobber_existing_files(
    tmp_path: Path,
) -> None:
    """Q2 Accept A: existing USER.md / MEMORY.md content is preserved."""
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    (memory_root / "USER.md").write_text("keep-user", encoding="utf-8")
    (memory_root / "MEMORY.md").write_text("keep-memory", encoding="utf-8")
    config_path = tmp_path / "config.yaml"

    write_config_yaml(config_path, {"memory_root": str(memory_root)})

    assert (memory_root / "USER.md").read_text(encoding="utf-8") == "keep-user"
    assert (memory_root / "MEMORY.md").read_text(encoding="utf-8") == "keep-memory"


# --- Task 2.7: flag matrix, secrets, partial updates ---


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "gpt-test-model"),
        ("tool_profile", "messaging"),
        ("tool_profile", "full"),
    ],
)
def test_write_config_yaml_flag_matrix_model_and_tool_profile(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    """FR-7 flag matrix: model and tool_profile land in YAML."""
    config_path = tmp_path / "config.yaml"

    write_config_yaml(config_path, {field: value})

    assert _load_yaml(config_path)[field] == value


def test_write_config_yaml_accepts_full_tool_profile(tmp_path: Path) -> None:
    """FR-1: tool_profile full is a valid persisted profile (PRD-012)."""
    config_path = tmp_path / "config.yaml"

    result = write_config_yaml(config_path, {"tool_profile": "full"})

    assert result.changed is True
    assert _load_yaml(config_path)["tool_profile"] == "full"


def test_write_config_yaml_rejects_invalid_tool_profile(tmp_path: Path) -> None:
    """Invalid tool_profile (not coding|messaging|full) raises ConfigError."""
    config_path = tmp_path / "config.yaml"

    with pytest.raises(ConfigError, match="tool_profile") as exc_info:
        write_config_yaml(config_path, {"tool_profile": "garbage"})

    message = str(exc_info.value)
    assert "coding" in message
    assert "messaging" in message
    assert "full" in message
    assert "garbage" in message
    assert not config_path.exists()


def test_merge_env_file_sessions_db_key(tmp_path: Path) -> None:
    """FR-7: --sessions-db maps to CURSOR_AGENT_SESSIONS_DB in .env only."""
    env_path = tmp_path / ".env"
    sessions_db = str(tmp_path / "custom-sessions.db")

    result = merge_env_file(
        env_path,
        {"CURSOR_AGENT_SESSIONS_DB": sessions_db},
        force=False,
    )

    assert result.changed is True
    assert f"CURSOR_AGENT_SESSIONS_DB={sessions_db}" in env_path.read_text(
        encoding="utf-8"
    )


def test_write_config_yaml_never_writes_secrets(tmp_path: Path) -> None:
    """ADR-028 §1: secrets never appear in YAML output."""
    config_path = tmp_path / "config.yaml"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with pytest.raises(ConfigError, match="unsupported"):
        write_config_yaml(
            config_path,
            {"CURSOR_API_KEY": _PLACEHOLDER_API_KEY},  # type: ignore[dict-item]
        )

    write_config_yaml(
        config_path,
        {
            "model": "composer-2.5",
            "runtime": {"local": {"cwd": str(workspace)}},
        },
    )
    yaml_text = config_path.read_text(encoding="utf-8")
    assert "CURSOR_API_KEY" not in yaml_text
    assert _PLACEHOLDER_API_KEY not in yaml_text


def test_write_config_yaml_partial_update_preserves_unrelated_keys(
    tmp_path: Path,
) -> None:
    """Partial updates must not wipe unrelated existing YAML keys."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model: keep-me\n"
        "tool_profile: coding\n"
        "custom_operator_note: preserve\n"
        "runtime:\n"
        "  mode: local\n"
        "  local:\n"
        "    cwd: .\n"
        "    setting_sources:\n"
        "      - project\n",
        encoding="utf-8",
    )

    write_config_yaml(config_path, {"tool_profile": "messaging"})

    data = _load_yaml(config_path)
    assert data["model"] == "keep-me"
    assert data["tool_profile"] == "messaging"
    assert data["custom_operator_note"] == "preserve"
    assert data["runtime"]["mode"] == "local"
    assert data["runtime"]["local"]["setting_sources"] == ["project"]


def test_merge_env_file_rejects_disallowed_keys(tmp_path: Path) -> None:
    """Only allowlisted env keys may be written by the setup writer."""
    env_path = tmp_path / ".env"

    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        merge_env_file(
            env_path,
            {"TELEGRAM_BOT_TOKEN": "not-allowed"},
            force=False,
        )
