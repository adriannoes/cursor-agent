"""Static checks that `.env.example` and setup docs stay aligned (PRD-012 / Wave G4)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from cursor_agent.first_party_models import (
    DEFAULT_AGENT_MODEL,
    recommended_agent_model_ids,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_EXAMPLE_PATH = _REPO_ROOT / ".env.example"
_SETUP_DOCS_PATH = _REPO_ROOT / "docs" / "setup.md"

# CursorAgentConfig fields via pydantic-settings (ADR-007) plus startup flat override.
_SUPPORTED_CURSOR_AGENT_ENV_VARS: frozenset[str] = frozenset(
    {
        "CURSOR_AGENT__MODEL",
        "CURSOR_AGENT__TOOL_PROFILE",
        "CURSOR_AGENT__MEMORY_ROOT",
        "CURSOR_AGENT__RUNTIME__MODE",
        "CURSOR_AGENT__RUNTIME__LOCAL__CWD",
        "CURSOR_AGENT__RUNTIME__LOCAL__SETTING_SOURCES",
        "CURSOR_AGENT__MCP__FULL__SERVERS",
        "CURSOR_AGENT__MCP__FULL__GITHUB_TRANSPORT",
        "CURSOR_AGENT_SESSIONS_DB",
    }
)

_UNSUPPORTED_LEGACY_CURSOR_AGENT_ENV_VARS: frozenset[str] = frozenset(
    {
        "CURSOR_AGENT_WORKSPACE",
        "CURSOR_AGENT_CONFIG",
    }
)

_ENV_LINE_PATTERN = re.compile(
    r"^\s*#?\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=",
)


def _parse_env_example_variable_names(path: Path) -> set[str]:
    """Return variable names declared in an env example file (active or commented)."""
    if not path.is_file():
        msg = f"env example file not found: {path!r}"
        raise FileNotFoundError(msg)
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") and "=" not in stripped:
            continue
        match = _ENV_LINE_PATTERN.match(line)
        if match is not None:
            names.add(match.group("name"))
    return names


def _cursor_agent_names(names: set[str]) -> set[str]:
    """Filter names that start with the CURSOR_AGENT prefix."""
    return {name for name in names if name.startswith("CURSOR_AGENT")}


@pytest.fixture
def env_example_cursor_agent_vars() -> set[str]:
    """CURSOR_AGENT* variable names documented in `.env.example`."""
    return _cursor_agent_names(_parse_env_example_variable_names(_ENV_EXAMPLE_PATH))


def test_env_example_documents_only_supported_cursor_agent_vars(
    env_example_cursor_agent_vars: set[str],
) -> None:
    """`.env.example` must not advertise unsupported CURSOR_AGENT* names."""
    unsupported = env_example_cursor_agent_vars - _SUPPORTED_CURSOR_AGENT_ENV_VARS
    assert unsupported == set(), (
        f"unsupported CURSOR_AGENT* vars in .env.example: {sorted(unsupported)!r}; "
        f"allowed: {sorted(_SUPPORTED_CURSOR_AGENT_ENV_VARS)!r}"
    )


def test_env_example_excludes_legacy_unsupported_cursor_agent_vars(
    env_example_cursor_agent_vars: set[str],
) -> None:
    """Legacy flat names must not appear in `.env.example`."""
    present = env_example_cursor_agent_vars & _UNSUPPORTED_LEGACY_CURSOR_AGENT_ENV_VARS
    assert present == set(), (
        f"legacy unsupported CURSOR_AGENT* vars in .env.example: {sorted(present)!r}"
    )


def test_env_example_includes_canonical_workspace_override() -> None:
    """Workspace override uses ADR-007 nested env, not legacy flat name."""
    names = _parse_env_example_variable_names(_ENV_EXAMPLE_PATH)
    assert "CURSOR_AGENT__RUNTIME__LOCAL__CWD" in names
    assert "CURSOR_AGENT_WORKSPACE" not in names


def test_setup_docs_and_env_example_document_soft_catalog_model_ids() -> None:
    """Public docs must mention every soft-catalog model id (Wave G4 drift guard)."""
    setup_text = _SETUP_DOCS_PATH.read_text(encoding="utf-8")
    env_text = _ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    missing_setup: list[str] = []
    missing_env: list[str] = []
    for model_id in recommended_agent_model_ids():
        if model_id not in setup_text:
            missing_setup.append(model_id)
        if model_id not in env_text:
            missing_env.append(model_id)
    assert missing_setup == [], (
        f"docs/setup.md missing soft-catalog model id(s): {missing_setup!r}; "
        f"expected every id from recommended_agent_model_ids()="
        f"{list(recommended_agent_model_ids())!r}"
    )
    assert missing_env == [], (
        f".env.example missing soft-catalog model id(s): {missing_env!r}; "
        f"expected every id from recommended_agent_model_ids()="
        f"{list(recommended_agent_model_ids())!r}"
    )


def test_setup_docs_document_default_model_and_choosing_section() -> None:
    """setup.md must name the unset default and include Choosing a model guidance."""
    setup_text = _SETUP_DOCS_PATH.read_text(encoding="utf-8")
    assert DEFAULT_AGENT_MODEL in setup_text, (
        f"docs/setup.md must mention DEFAULT_AGENT_MODEL={DEFAULT_AGENT_MODEL!r}"
    )
    # Require the Configuration child heading (###), not a top-level ## that
    # would re-parent Tool profile in the TOC.
    assert re.search(r"(?m)^### Choosing a model$", setup_text), (
        "docs/setup.md must include a '### Choosing a model' heading under "
        f"Configuration (DEFAULT_AGENT_MODEL={DEFAULT_AGENT_MODEL!r})"
    )
    assert not re.search(r"(?m)^## Choosing a model$", setup_text), (
        "docs/setup.md must not use a top-level '## Choosing a model' heading "
        "(keeps Tool profile nested under Configuration)"
    )
