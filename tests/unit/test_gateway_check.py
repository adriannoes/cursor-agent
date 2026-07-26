"""Unit tests for PRD-017 ``gateway check`` (Wave 3).

Public API under test:

- **CLI** ``cursor-agent gateway check [--config PATH]``.
  Flag name is **``--config``** (LOCKED), not ``--gateway-config``.
  Default path: ``~/.cursor-agent/gateway.yaml`` (same as ``gateway`` start).

- **Behavior (FR-3 / A4):** offline parse + validate via ``load_gateway_config``
  + startup refuse (``tool_profile`` must be ``messaging``) and enabled-Telegram
  empty ``bot_token`` refuse (same intent as factory startup). Print greppable
  ``ok:`` / ``error:`` lines. **No** network / Telegram ``getMe``.

- **Exit matrix:**
  - valid messaging config + existing workspace dir → exit **0**
  - missing file / missing workspace dir / wrong profile / empty bot_token /
    load error → exit **1**
  - Missing file is an **error** (unlike ``doctor``, which prints
    ``ok: gateway.yaml — (absent)``).

- **Secrets (ADR-025):** never print Telegram ``bot_token`` (including invalid
  shapes that land in Pydantic ``ValidationError.errors()`` ``input``).

- **Shared helper:** ``collect_gateway_check_lines``. CLI wraps it after
  converting ``gateway`` to a Typer group with ``invoke_without_command=True``.

Pattern: ``tests/unit/test_gateway_config.py`` YAML fixtures;
``tests/unit/test_doctor.py`` ``_write_minimal_gateway_yaml`` / CliRunner.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.gateway_check import (
    GATEWAY_ABSENT_OK_LINE,
    collect_gateway_check_lines,
)
from cursor_agent.gateway import DEFAULT_GATEWAY_CONFIG_PATH

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_PLACEHOLDER_BOT_TOKEN = "telegram-bot-token-secret-never-print-gw-check"


def _strip_ansi(text: str) -> str:
    """Remove Rich/ANSI SGR sequences so flag names are contiguous substrings."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _invoke_gateway_check(*args: str) -> Any:
    """Invoke ``gateway check`` via the root Typer app."""
    return CliRunner().invoke(app, ["gateway", "check", *args])


def _write_minimal_gateway_yaml(
    path: Path,
    *,
    workspace: Path | str,
    tool_profile: str = "messaging",
    bot_token: str = _PLACEHOLDER_BOT_TOKEN,
    telegram_enabled: bool = True,
) -> None:
    """Write a gateway.yaml matching doctor / gateway-config fixture shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                f"tool_profile: {tool_profile}",
                "platforms:",
                "  telegram:",
                f"    enabled: {str(telegram_enabled).lower()}",
                f"    bot_token: {bot_token}",
                "    allowed_users:",
                "      - 123456789",
                "",
            ]
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Helper: collect_gateway_check_lines (may already be green — Wave 2 shipped)
# ---------------------------------------------------------------------------


def test_collect_gateway_check_lines_valid_config_returns_ok_lines(
    tmp_path: Path,
) -> None:
    """Valid messaging YAML + existing workspace → ok lines, failed=False."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(config_path, workspace=workspace)

    lines, failed = collect_gateway_check_lines(config_path)

    assert failed is False
    assert any(line.startswith("ok: gateway.yaml —") for line in lines)
    assert any(line.startswith("ok: gateway workspace —") for line in lines)
    assert "ok: gateway tool_profile — messaging" in lines
    assert any(line.startswith("ok: gateway platforms —") for line in lines)
    assert not any(line.startswith("error:") for line in lines)
    assert _PLACEHOLDER_BOT_TOKEN not in "\n".join(lines)


def test_collect_gateway_check_lines_missing_file_returns_error(
    tmp_path: Path,
) -> None:
    """Missing file → error line with path; failed=True (FR-3, unlike doctor)."""
    missing = tmp_path / "absent-gateway.yaml"
    assert not missing.exists()

    lines, failed = collect_gateway_check_lines(missing)

    assert failed is True
    joined = "\n".join(lines)
    assert any(line.startswith("error: gateway.yaml —") for line in lines)
    assert str(missing) in joined
    assert GATEWAY_ABSENT_OK_LINE not in lines


def test_collect_gateway_check_lines_missing_workspace_dir_returns_error(
    tmp_path: Path,
) -> None:
    """YAML workspace path that is not a directory → error + failed=True."""
    missing_ws = tmp_path / "no-such-workspace"
    assert not missing_ws.exists()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(config_path, workspace=missing_ws)

    lines, failed = collect_gateway_check_lines(config_path)

    assert failed is True
    assert any(line.startswith("error: gateway workspace —") for line in lines)
    assert str(missing_ws) in "\n".join(lines)


def test_collect_gateway_check_lines_wrong_profile_returns_error(
    tmp_path: Path,
) -> None:
    """Non-messaging tool_profile → error line (startup refuse), failed=True."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(
        config_path,
        workspace=workspace,
        tool_profile="coding",
    )

    lines, failed = collect_gateway_check_lines(config_path)

    assert failed is True
    joined = "\n".join(lines)
    assert any(line.startswith("error: gateway.yaml —") for line in lines)
    assert "messaging" in joined
    assert "coding" in joined
    assert _PLACEHOLDER_BOT_TOKEN not in joined


def test_collect_gateway_check_lines_empty_telegram_bot_token_returns_error(
    tmp_path: Path,
) -> None:
    """Enabled Telegram with empty bot_token → error + failed=True (startup parity)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    # Quoted empty string: bare `bot_token:` is YAML null (validation error), not "".
    config_path.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "tool_profile: messaging",
                "platforms:",
                "  telegram:",
                "    enabled: true",
                '    bot_token: ""',
                "    allowed_users:",
                "      - 123456789",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lines, failed = collect_gateway_check_lines(config_path)

    assert failed is True
    joined = "\n".join(lines)
    assert any(line.startswith("error:") for line in lines)
    assert "bot_token" in joined
    assert "telegram" in joined.lower()


def test_collect_gateway_check_lines_whitespace_telegram_bot_token_returns_error(
    tmp_path: Path,
) -> None:
    """Whitespace-only bot_token is treated as empty for gateway check."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "tool_profile: messaging",
                "platforms:",
                "  telegram:",
                "    enabled: true",
                '    bot_token: "   "',
                "    allowed_users:",
                "      - 123456789",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lines, failed = collect_gateway_check_lines(config_path)

    assert failed is True
    assert any("bot_token" in line for line in lines)


def test_collect_gateway_check_lines_invalid_bot_token_shape_redacts_input(
    tmp_path: Path,
) -> None:
    """Invalid bot_token shape must not echo secret-looking ValidationError input."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    secret_payload = "secret-list-token-never-print"
    config_path.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "tool_profile: messaging",
                "platforms:",
                "  telegram:",
                "    enabled: true",
                "    bot_token:",
                f"      - {secret_payload}",
                "      - not-a-string-either",
                "    allowed_users:",
                "      - 123456789",
                "",
            ]
        ),
        encoding="utf-8",
    )

    lines, failed = collect_gateway_check_lines(config_path)

    assert failed is True
    joined = "\n".join(lines)
    assert any(line.startswith("error: gateway.yaml —") for line in lines)
    assert secret_payload not in joined
    assert "not-a-string-either" not in joined


def test_collect_gateway_check_lines_malformed_yaml_redacts_bot_token(
    tmp_path: Path,
) -> None:
    """YAMLError that quotes the bot_token line must not echo the secret value.

    Unclosed quotes keep ``bot_token: <secret>`` in PyYAML's exception text,
    bypassing Pydantic sanitization — gateway load/check must redact it.
    """
    from cursor_agent.errors import ConfigError
    from cursor_agent.gateway.config import load_gateway_config

    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    # Keep short so PyYAML's error snippet includes the full scalar (not truncated).
    secret = "sekretTok9"
    # Unclosed quote: YAMLError message includes the offending scalar line.
    config_path.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "tool_profile: messaging",
                "platforms:",
                "  telegram:",
                "    enabled: true",
                f'    bot_token: "{secret}',
                "    allowed_users:",
                "      - 123456789",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_gateway_config(config_path=config_path)
    assert secret not in str(exc_info.value)

    lines, failed = collect_gateway_check_lines(config_path)
    assert failed is True
    joined = "\n".join(lines)
    assert any(line.startswith("error: gateway.yaml —") for line in lines)
    assert secret not in joined

    result = _invoke_gateway_check("--config", str(config_path))
    assert result.exit_code == 1, result.output
    assert secret not in result.output


# ---------------------------------------------------------------------------
# CLI: gateway check
# ---------------------------------------------------------------------------


def test_cli_gateway_check_valid_config_exits_zero(tmp_path: Path) -> None:
    """``gateway check --config PATH`` with valid messaging YAML → exit 0."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(config_path, workspace=workspace)

    result = _invoke_gateway_check("--config", str(config_path))

    assert result.exit_code == 0, result.output
    assert "ok: gateway.yaml —" in result.output
    assert "ok: gateway tool_profile — messaging" in result.output
    assert "error:" not in result.output


def test_cli_gateway_check_missing_file_exits_one_with_path(tmp_path: Path) -> None:
    """Missing ``--config`` path → exit 1 and echoes the expected path."""
    missing = tmp_path / "no-gateway.yaml"
    assert not missing.exists()

    result = _invoke_gateway_check("--config", str(missing))

    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert str(missing) in result.output
    assert GATEWAY_ABSENT_OK_LINE not in result.output


def test_cli_gateway_check_missing_workspace_exits_one(tmp_path: Path) -> None:
    """Workspace path in YAML that does not exist → exit 1."""
    missing_ws = tmp_path / "missing-ws"
    assert not missing_ws.exists()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(config_path, workspace=missing_ws)

    result = _invoke_gateway_check("--config", str(config_path))

    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert "workspace" in result.output.lower()


def test_cli_gateway_check_wrong_profile_exits_one(tmp_path: Path) -> None:
    """``tool_profile: coding`` refused → exit 1 with messaging expectation."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(
        config_path,
        workspace=workspace,
        tool_profile="coding",
    )

    result = _invoke_gateway_check("--config", str(config_path))

    assert result.exit_code == 1, result.output
    assert "error:" in result.output
    assert "messaging" in result.output
    assert "coding" in result.output


def test_cli_gateway_check_redacts_bot_token(tmp_path: Path) -> None:
    """Valid check output must never echo Telegram ``bot_token`` (ADR-025)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    config_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(config_path, workspace=workspace)

    result = _invoke_gateway_check("--config", str(config_path))

    assert result.exit_code == 0, result.output
    assert _PLACEHOLDER_BOT_TOKEN not in result.output


def test_cli_gateway_check_default_path_uses_home_cursor_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no ``--config``, check uses the default gateway YAML path.

    ``DEFAULT_GATEWAY_CONFIG_PATH`` is import-time (real HOME); patch the
    constant the CLI / loader consult when ``--config`` is omitted.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    default_path = tmp_path / "home" / ".cursor-agent" / "gateway.yaml"
    _write_minimal_gateway_yaml(default_path, workspace=workspace)
    monkeypatch.setattr(
        "cursor_agent.gateway.config.DEFAULT_GATEWAY_CONFIG_PATH",
        default_path,
    )
    # CLI may re-export or import the constant; patch if present after 4.2.
    monkeypatch.setattr(
        "cursor_agent.cli.gateway_check.DEFAULT_GATEWAY_CONFIG_PATH",
        default_path,
        raising=False,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.app.DEFAULT_GATEWAY_CONFIG_PATH",
        default_path,
        raising=False,
    )
    assert DEFAULT_GATEWAY_CONFIG_PATH.name == "gateway.yaml"

    result = _invoke_gateway_check()

    assert result.exit_code == 0, result.output
    assert "ok: gateway.yaml —" in result.output
    assert _PLACEHOLDER_BOT_TOKEN not in result.output


def test_cli_gateway_check_help_lists_config_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``gateway check --help`` is a real subcommand help with ``--config``."""
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)

    result = CliRunner().invoke(app, ["gateway", "check", "--help"])

    assert result.exit_code == 0, result.output
    help_text = _strip_ansi(result.output)
    assert "gateway check" in help_text
    assert "--config" in help_text
    assert "--gateway-config" not in help_text
