"""Unit tests for effective config + source attribution (PRD-013 Task 3.0, ADR-028).

Uses injectable env mappings and ``tmp_path`` only — never the developer's real
``~/.cursor-agent`` or secrets. API key fixtures use ``sk-test-placeholder``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config.effective import (
    ConfigSourceLabel,
    EffectiveConfigView,
    build_effective_config,
    render_effective_config_redacted,
)

_PLACEHOLDER_API_KEY = "sk-test-placeholder"
_SHELL_API_KEY = "sk-test-placeholder-shell"
_DOTENV_API_KEY = "sk-test-placeholder-dotenv"
_REDACTION_TOKEN = "***"


def test_build_effective_config_defaults_when_empty(tmp_path: Path) -> None:
    """Effective view reports pydantic defaults with source=default."""
    config_path = tmp_path / "missing.yaml"
    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=tmp_path / ".env",
    )

    assert isinstance(view, EffectiveConfigView)
    assert view.model == "composer-2.5"
    assert view.tool_profile == "coding"
    assert view.api_key_present is False
    assert view.api_key_redacted is None
    assert view.sources["model"] == "default"
    assert view.sources["tool_profile"] == "default"
    assert view.sources["workspace"] == "default"
    assert view.sources["api_key"] == "default"


def test_build_effective_config_yaml_source_and_values(tmp_path: Path) -> None:
    """YAML supplies non-secret fields with source=yaml when env is unset."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "model: from-yaml-model\n"
        "tool_profile: messaging\n"
        f"memory_root: {memory_root}\n"
        "runtime:\n"
        "  local:\n"
        f"    cwd: {workspace}\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=tmp_path / ".env",
    )

    assert view.model == "from-yaml-model"
    assert view.tool_profile == "messaging"
    assert view.workspace == str(workspace)
    assert view.memory_root == str(memory_root)
    assert view.sources["model"] == "yaml"
    assert view.sources["tool_profile"] == "yaml"
    assert view.sources["workspace"] == "yaml"
    assert view.sources["memory_root"] == "yaml"


def test_build_effective_config_surfaces_tool_profile_full(tmp_path: Path) -> None:
    """FR-1: effective view surfaces tool_profile full from YAML."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("tool_profile: full\n", encoding="utf-8")

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=tmp_path / ".env",
    )

    assert view.tool_profile == "full"
    assert view.sources["tool_profile"] == "yaml"
    rendered = render_effective_config_redacted(view)
    assert "tool_profile: full" in rendered


def test_build_effective_config_surfaces_mcp_full_servers_allowlist(
    tmp_path: Path,
) -> None:
    """FR-9: effective view surfaces mcp.full.servers allowlist and yaml source."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tool_profile: full\n"
        "mcp:\n"
        "  full:\n"
        "    servers:\n"
        "      - github\n"
        "      - brave-search\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=tmp_path / ".env",
    )

    assert view.mcp_full_servers == ["github", "brave-search"]
    assert view.sources["mcp_full_servers"] == "yaml"
    rendered = render_effective_config_redacted(view)
    assert "mcp.full.servers" in rendered
    assert "github" in rendered


def test_build_effective_config_empty_mcp_full_servers_allowlist_display(
    tmp_path: Path,
) -> None:
    """Explicit empty allowlist must not look like default-all in setup show."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "tool_profile: full\nmcp:\n  full:\n    servers: []\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=tmp_path / ".env",
    )

    assert view.mcp_full_servers == []
    rendered = render_effective_config_redacted(view)
    assert "(empty allowlist)" in rendered
    assert "(all curated)" not in rendered


def test_build_effective_config_env_api_key_present_and_redacted(
    tmp_path: Path,
) -> None:
    """CURSOR_API_KEY from CWD .env is present, redacted, source=env."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=tmp_path / "missing.yaml",
        environ={},
        dotenv_path=dotenv_path,
    )

    assert view.api_key_present is True
    assert view.api_key_redacted == _REDACTION_TOKEN
    assert view.sources["api_key"] == "env"


def test_render_effective_config_redacted_never_includes_raw_api_key(
    tmp_path: Path,
) -> None:
    """Show rendering redacts the API key and never echoes the fixture secret."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: show-model\n", encoding="utf-8")

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=dotenv_path,
    )
    rendered = render_effective_config_redacted(view)

    assert isinstance(rendered, str)
    assert _PLACEHOLDER_API_KEY not in rendered
    assert _REDACTION_TOKEN in rendered
    assert "show-model" in rendered
    assert "api_key" in rendered.lower() or "CURSOR_API_KEY" in rendered


def test_render_effective_config_includes_source_labels(tmp_path: Path) -> None:
    """Rendered show output includes locked source label strings."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: labeled-model\n", encoding="utf-8")

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=tmp_path / ".env",
    )
    rendered = render_effective_config_redacted(view)

    assert "yaml" in rendered
    assert "default" in rendered
    assert "labeled-model" in rendered


def test_config_source_label_locked_literals() -> None:
    """ADR-028 §9: source labels are exactly shell|env|yaml|default."""
    allowed: set[ConfigSourceLabel] = {"shell", "env", "yaml", "default"}
    assert allowed == {"shell", "env", "yaml", "default"}


@pytest.mark.parametrize(
    ("field", "source"),
    [
        ("model", "default"),
        ("tool_profile", "default"),
        ("api_key", "default"),
    ],
)
def test_effective_sources_map_contains_core_fields(
    tmp_path: Path,
    field: str,
    source: ConfigSourceLabel,
) -> None:
    """Sources map always includes core setup-show fields."""
    view = build_effective_config(
        config_path=tmp_path / "missing.yaml",
        environ={},
        dotenv_path=tmp_path / ".env",
    )
    assert view.sources[field] == source


def test_shell_beats_dotenv_for_api_key_source_shell(tmp_path: Path) -> None:
    """When shell and CWD .env both set CURSOR_API_KEY, winning source is shell."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        f"CURSOR_API_KEY={_DOTENV_API_KEY}\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=tmp_path / "missing.yaml",
        environ={"CURSOR_API_KEY": _SHELL_API_KEY},
        dotenv_path=dotenv_path,
    )

    assert view.api_key_present is True
    assert view.api_key_redacted == _REDACTION_TOKEN
    assert view.sources["api_key"] == "shell"
    rendered = render_effective_config_redacted(view)
    assert _SHELL_API_KEY not in rendered
    assert _DOTENV_API_KEY not in rendered
    assert "source: shell" in rendered


def test_shell_beats_dotenv_for_model_source_shell(tmp_path: Path) -> None:
    """Exported CURSOR_AGENT__MODEL beats CWD .env; source label is shell."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "CURSOR_AGENT__MODEL=from-dotenv-model\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=tmp_path / "missing.yaml",
        environ={"CURSOR_AGENT__MODEL": "from-shell-model"},
        dotenv_path=dotenv_path,
    )

    assert view.model == "from-shell-model"
    assert view.sources["model"] == "shell"


def test_dotenv_model_source_is_env_when_shell_unset(tmp_path: Path) -> None:
    """CWD .env alone attributes model source as env (not shell)."""
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "CURSOR_AGENT__MODEL=from-dotenv-only\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=tmp_path / "missing.yaml",
        environ={},
        dotenv_path=dotenv_path,
    )

    assert view.model == "from-dotenv-only"
    assert view.sources["model"] == "env"


def test_env_beats_yaml_for_model_source_precedence(tmp_path: Path) -> None:
    """Non-secret field: CURSOR_AGENT__MODEL env beats YAML; source is shell."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("model: from-yaml-model\n", encoding="utf-8")

    view = build_effective_config(
        config_path=config_path,
        environ={"CURSOR_AGENT__MODEL": "from-env-over-yaml"},
        dotenv_path=tmp_path / ".env",
    )

    assert view.model == "from-env-over-yaml"
    assert view.sources["model"] == "shell"
    assert view.sources["model"] != "yaml"


def test_dotenv_beats_yaml_for_tool_profile_source_env(tmp_path: Path) -> None:
    """Non-secret field: CWD .env beats YAML when shell unset; source is env."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("tool_profile: coding\n", encoding="utf-8")
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "CURSOR_AGENT__TOOL_PROFILE=messaging\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=config_path,
        environ={},
        dotenv_path=dotenv_path,
    )

    assert view.tool_profile == "messaging"
    assert view.sources["tool_profile"] == "env"


def test_sessions_db_shell_source_beats_dotenv(tmp_path: Path) -> None:
    """CURSOR_AGENT_SESSIONS_DB from process env wins over .env with source=shell."""
    shell_db = tmp_path / "shell-sessions.db"
    dotenv_db = tmp_path / "dotenv-sessions.db"
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        f"CURSOR_AGENT_SESSIONS_DB={dotenv_db}\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=tmp_path / "missing.yaml",
        environ={"CURSOR_AGENT_SESSIONS_DB": str(shell_db)},
        dotenv_path=dotenv_path,
    )

    assert view.sessions_db == str(shell_db)
    assert view.sources["sessions_db"] == "shell"


def test_source_labels_locked_to_adr028_strings(tmp_path: Path) -> None:
    """ADR-028 §9: every attributed source is one of shell|env|yaml|default."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"model: yaml-model\nruntime:\n  local:\n    cwd: {workspace}\n",
        encoding="utf-8",
    )
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        f"CURSOR_API_KEY={_PLACEHOLDER_API_KEY}\n"
        "CURSOR_AGENT__TOOL_PROFILE=messaging\n",
        encoding="utf-8",
    )

    view = build_effective_config(
        config_path=config_path,
        environ={"CURSOR_AGENT__MODEL": "shell-model"},
        dotenv_path=dotenv_path,
    )

    allowed = {"shell", "env", "yaml", "default"}
    for field, label in view.sources.items():
        assert label in allowed, f"field {field!r} has unexpected source {label!r}"
    assert view.sources["model"] == "shell"
    assert view.sources["tool_profile"] == "env"
    assert view.sources["workspace"] == "yaml"
    assert view.sources["api_key"] == "env"
    assert view.sources["memory_root"] == "default"
    assert view.sources["sessions_db"] == "default"
