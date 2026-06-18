"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config


@pytest.fixture(autouse=True)
def isolated_memory_root(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop unit tests from reading the operator's real ``~/.cursor-agent`` memory.

    PRD-008 wired Memory v1 injection into the shared ``SessionAgentPool.send()``
    path, defaulting to ``~/.cursor-agent``. Any test using the default pool (e.g.
    gateway busy/shutdown tests) would otherwise read the real ``USER.md`` /
    ``MEMORY.md`` and become environment-dependent. This keeps the suite hermetic.
    """
    isolated_root = tmp_path_factory.mktemp("cursor-agent-home")
    monkeypatch.setattr(
        "cursor_agent.memory.store._DEFAULT_MEMORY_ROOT",
        isolated_root,
    )


@pytest.fixture
def config(tmp_path: Path) -> CursorAgentConfig:
    """Default config loaded from a missing YAML path."""
    return load_config(config_path=tmp_path / "missing.yaml")
