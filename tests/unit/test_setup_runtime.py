"""Unit tests for ``setup_runtime.apply_non_interactive`` orphan-guard ordering.

Uses ``tmp_path`` only — never the real ``~/.cursor-agent``.
API key fixtures use placeholders such as ``sk-test-placeholder``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cursor_agent.cli.setup_runtime import apply_non_interactive
from cursor_agent.errors import ConfigError

_PLACEHOLDER_API_KEY = "sk-test-placeholder"
_CONFLICTING_API_KEY = "sk-test-other-placeholder"


def test_apply_non_interactive_env_refuse_skips_yaml_and_env_writes(
    tmp_path: Path,
) -> None:
    """Conflicting .env with force=False raises before YAML/env writes.

    ``check_env_merge_allowed`` must refuse before ``write_config_yaml`` or
    ``merge_env_file`` run, so a refused overwrite cannot leave orphan
    ``config.yaml`` or memory placeholders.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "home" / "config.yaml"
    env_file = tmp_path / "project" / ".env"
    env_file.parent.mkdir()
    env_file.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n",
        encoding="utf-8",
    )
    memory_root = tmp_path / "memory"

    with (
        patch("cursor_agent.cli.setup_runtime.write_config_yaml") as mock_write_yaml,
        patch("cursor_agent.cli.setup_runtime.merge_env_file") as mock_merge_env,
        pytest.raises(ConfigError, match="force") as exc_info,
    ):
        apply_non_interactive(
            api_key=_CONFLICTING_API_KEY,
            workspace=workspace,
            memory_root=memory_root,
            sessions_db=None,
            model=None,
            tool_profile=None,
            config_path=config_path,
            env_file=env_file,
            dry_run=False,
            force=False,
        )

    assert "setup show" in str(exc_info.value)
    mock_write_yaml.assert_not_called()
    mock_merge_env.assert_not_called()
    assert not config_path.exists()
    assert not (memory_root / "USER.md").exists()
    assert not (memory_root / "MEMORY.md").exists()
    assert env_file.read_text(encoding="utf-8") == (
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
    )
