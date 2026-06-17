"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config


@pytest.fixture
def config(tmp_path: Path) -> CursorAgentConfig:
    """Default config loaded from a missing YAML path."""
    return load_config(config_path=tmp_path / "missing.yaml")
