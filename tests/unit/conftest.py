"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config

_CURSOR_FLAT_ENV_KEYS = frozenset(
    {
        "CURSOR_API_KEY",
        "CURSOR_AGENT_SESSIONS_DB",
        "CURSOR_SDK_LOG",
    }
)


def _cursor_agent_env_keys() -> list[str]:
    """Return process-env keys owned by cursor-agent config and CLI bootstrap."""
    return [
        key
        for key in os.environ
        if key.startswith("CURSOR_AGENT") or key in _CURSOR_FLAT_ENV_KEYS
    ]


@pytest.fixture(autouse=True)
def isolated_cursor_agent_process_env() -> Iterator[None]:
    """Restore cursor-agent env keys after tests that call ``load_cwd_dotenv``.

    ``python-dotenv`` mutates ``os.environ`` directly; without this, dotenv tests
    leak ``CURSOR_AGENT__*`` into unrelated config-default assertions.
    """
    snapshot = {key: os.environ[key] for key in _cursor_agent_env_keys()}
    yield
    for key in _cursor_agent_env_keys():
        if key not in snapshot:
            os.environ.pop(key, None)
    for key, value in snapshot.items():
        os.environ[key] = value


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
