"""Unit tests for PRD-017 ``doctor`` aggregate (Wave 2).

Public API under test:

- **CLI** ``cursor-agent doctor [--json] [--gateway-config PATH] [--probe]``.
  Flag name is **``--gateway-config``** (LOCKED), not ``--config``.
  Doctor is **local by default**; ``--probe`` is opt-in and forwards to FR-1
  auth probes. Default run performs **zero** ``probe_api_key`` / facade bridges.

- **Sections** (order fixed for greppability): Setup → Auth → Messaging hooks
  → Gateway. Setup reuses shared helpers behind ``run_setup_check``.

- **Messaging hooks** — public ``messaging_hooks_status(...)`` in
  ``cursor_agent.messaging_hooks_status``:
  - ``messaging`` + missing/incomplete → **error** severity
  - incomplete includes scripts present but project ``hooks.json`` missing
    **any** expected messaging command binding (not merely ``any()``)
  - ``coding`` / ``full`` without hooks →
    ``ok: messaging hooks — (not required for profile <name>)``
    and **never** a perpetual ``warning:`` for that section

- **Gateway** — absent YAML → ``ok: gateway.yaml — (absent)``; present path
  via ``--gateway-config`` is validated (shared helper with FR-3).

- **Exit matrix:** any ``error:`` line → exit 1; warnings alone → exit 0.

- **Secrets (ADR-025):** never print API keys, OAuth tokens, or Telegram
  ``bot_token``.

Pattern: ``tests/unit/test_auth_status.py`` CliRunner + ANSI strip;
``tests/unit/test_setup_check_show.py`` tmp_path / env fixtures.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.usage import USAGE_TOKEN_ENV_VAR


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_PLACEHOLDER_API_KEY = "sk-test-doctor-never-print"
_PLACEHOLDER_BOT_TOKEN = "telegram-bot-token-secret-never-print"
_GATEWAY_ABSENT_OK = "ok: gateway.yaml — (absent)"
_HOOKS_NOT_REQUIRED_PREFIX = "ok: messaging hooks — (not required for profile"


def _strip_ansi(text: str) -> str:
    """Remove Rich/ANSI SGR sequences so flag names are contiguous substrings."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _invoke_doctor(*args: str) -> Any:
    """Invoke the ``doctor`` command via the root Typer app."""
    return CliRunner().invoke(app, ["doctor", *args])


def _prepare_doctor_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tool_profile: str = "coding",
    api_key: str | None = _PLACEHOLDER_API_KEY,
    oauth_token: str | None = None,
) -> Path:
    """Isolate HOME + env so setup/auth/hooks resolve against tmp_path.

    Uses ``CURSOR_AGENT__*`` env overrides (higher precedence than YAML) so
    doctor does not depend on the import-time ``DEFAULT_CONFIG_PATH``.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (home / ".cursor-agent").mkdir()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    memory_root = tmp_path / "memory"
    memory_root.mkdir()
    sessions_parent = tmp_path / "sessions_parent"
    sessions_parent.mkdir()
    sessions_db = sessions_parent / "sessions.db"

    monkeypatch.setenv("CURSOR_AGENT__TOOL_PROFILE", tool_profile)
    monkeypatch.setenv("CURSOR_AGENT__RUNTIME__LOCAL__CWD", str(workspace))
    monkeypatch.setenv("CURSOR_AGENT__MEMORY_ROOT", str(memory_root))
    monkeypatch.setenv("CURSOR_AGENT_SESSIONS_DB", str(sessions_db))

    if api_key is None:
        monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    else:
        monkeypatch.setenv("CURSOR_API_KEY", api_key)

    if oauth_token is None:
        monkeypatch.delenv(USAGE_TOKEN_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, oauth_token)

    return workspace


def _write_minimal_gateway_yaml(path: Path, *, workspace: Path) -> None:
    """Write a valid messaging gateway.yaml with a secret bot_token placeholder."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f"workspace: {workspace}",
                "tool_profile: messaging",
                "platforms:",
                "  telegram:",
                "    enabled: true",
                f"    bot_token: {_PLACEHOLDER_BOT_TOKEN}",
                "    allowed_users:",
                "      - 123456789",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _spy_probe_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> list[object]:
    """Install probe spies on the real bind sites (auth_status + sdk_facade)."""
    probe_calls: list[object] = []

    async def _recording_probe(**kwargs: object) -> bool:
        probe_calls.append(kwargs)
        return True

    for target in (
        "cursor_agent.auth_status.probe_api_key",
        "cursor_agent.sdk_facade.probe_api_key",
    ):
        monkeypatch.setattr(target, _recording_probe, raising=True)

    return probe_calls


# ---------------------------------------------------------------------------
# Public helper: messaging_hooks_status (task 3.3)
# ---------------------------------------------------------------------------


def test_messaging_hooks_status_messaging_missing_is_error(
    tmp_path: Path,
) -> None:
    """Public helper: messaging profile + incomplete hooks → error severity."""
    from cursor_agent.messaging_hooks_status import messaging_hooks_status

    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = messaging_hooks_status(workspace=workspace, tool_profile="messaging")
    severity = getattr(report, "severity", None) or getattr(report, "level", None)
    lines = getattr(report, "lines", None)
    assert severity == "error" or (
        isinstance(lines, list)
        and any(str(line).startswith("error:") for line in lines)
    )


def test_messaging_hooks_status_coding_not_required_is_ok_not_warning(
    tmp_path: Path,
) -> None:
    """Public helper: coding without hooks → ok (not required), never warning."""
    from cursor_agent.messaging_hooks_status import messaging_hooks_status

    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = messaging_hooks_status(workspace=workspace, tool_profile="coding")
    lines_raw = getattr(report, "lines", None)
    if lines_raw is None:
        formatted = str(report)
        lines = [formatted]
    else:
        lines = [str(line) for line in lines_raw]
    joined = "\n".join(lines)
    assert f"{_HOOKS_NOT_REQUIRED_PREFIX} coding)" in joined
    assert not any(line.startswith("warning:") for line in lines)


def test_messaging_hooks_status_full_not_required_is_ok_not_warning(
    tmp_path: Path,
) -> None:
    """Public helper: full without hooks → ok (not required), never warning."""
    from cursor_agent.messaging_hooks_status import messaging_hooks_status

    workspace = tmp_path / "ws"
    workspace.mkdir()
    report = messaging_hooks_status(workspace=workspace, tool_profile="full")
    lines_raw = getattr(report, "lines", None)
    if lines_raw is None:
        formatted = str(report)
        lines = [formatted]
    else:
        lines = [str(line) for line in lines_raw]
    joined = "\n".join(lines)
    assert f"{_HOOKS_NOT_REQUIRED_PREFIX} full)" in joined
    assert not any(line.startswith("warning:") for line in lines)


def test_messaging_hooks_status_single_binding_is_incomplete_error(
    tmp_path: Path,
) -> None:
    """Scripts + only one messaging hooks.json binding → incomplete / error.

    Completeness must require *all* expected messaging command bindings from the
    packaged source hooks.json (rewritten deploy paths), not ``any()``.
    """
    from cursor_agent.messaging_hooks import (
        MESSAGING_HOOK_FILENAMES,
        WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX,
        ensure_messaging_hooks,
        workspace_messaging_hooks_dir,
        workspace_project_hooks_manifest_path,
    )
    from cursor_agent.messaging_hooks_status import messaging_hooks_status

    workspace = tmp_path / "ws"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks"
    ensure_messaging_hooks(workspace, user_hooks_dir=user_hooks)

    scripts_dir = workspace_messaging_hooks_dir(workspace)
    assert scripts_dir.is_dir()
    assert all(
        (scripts_dir / name).is_file()
        for name in MESSAGING_HOOK_FILENAMES
        if name.endswith(".sh")
    )

    # Strip all but one messaging command binding from the project manifest.
    manifest_path = workspace_project_hooks_manifest_path(workspace)
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    prefix = f"{WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX}/"
    kept_one = False
    truncated_hooks: dict[str, list[dict[str, object]]] = {}
    for event, entries in loaded["hooks"].items():
        kept_entries: list[dict[str, object]] = []
        for entry in entries:
            command = str(entry.get("command", ""))
            if not command.startswith(prefix):
                kept_entries.append(entry)
                continue
            if not kept_one:
                kept_entries.append(entry)
                kept_one = True
        if kept_entries:
            truncated_hooks[event] = kept_entries
    assert kept_one, "expected at least one messaging binding after deploy"
    manifest_path.write_text(
        json.dumps({"version": 1, "hooks": truncated_hooks}, indent=2) + "\n",
        encoding="utf-8",
    )

    report = messaging_hooks_status(workspace=workspace, tool_profile="messaging")
    assert report.complete is False
    assert report.severity == "error"
    assert any(line.startswith("error:") for line in report.lines)


def test_messaging_hooks_status_wrong_event_bindings_is_incomplete_error(
    tmp_path: Path,
) -> None:
    """Scripts + all messaging commands under the wrong event → incomplete.

    Completeness must compare ``(event, command, matcher, failClosed)`` bindings
    against the rewritten packaged source, not command-path sets alone. Moving
    every messaging script to a wrong event must still report incomplete.
    """
    from cursor_agent.messaging_hooks import (
        MESSAGING_HOOK_FILENAMES,
        WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX,
        ensure_messaging_hooks,
        workspace_messaging_hooks_dir,
        workspace_project_hooks_manifest_path,
    )
    from cursor_agent.messaging_hooks_status import messaging_hooks_status

    workspace = tmp_path / "ws"
    workspace.mkdir()
    user_hooks = tmp_path / "user-hooks"
    ensure_messaging_hooks(workspace, user_hooks_dir=user_hooks)

    scripts_dir = workspace_messaging_hooks_dir(workspace)
    assert scripts_dir.is_dir()
    assert all(
        (scripts_dir / name).is_file()
        for name in MESSAGING_HOOK_FILENAMES
        if name.endswith(".sh")
    )

    manifest_path = workspace_project_hooks_manifest_path(workspace)
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    prefix = f"{WORKSPACE_MESSAGING_HOOK_COMMAND_PREFIX}/"
    wrong_event = "sessionStart"
    assert wrong_event not in loaded["hooks"], (
        f"fixture assumes {wrong_event!r} is unused; pick another wrong event"
    )

    non_messaging: dict[str, list[dict[str, object]]] = {}
    messaging_entries: list[dict[str, object]] = []
    for event, entries in loaded["hooks"].items():
        kept: list[dict[str, object]] = []
        for entry in entries:
            command = str(entry.get("command", ""))
            if command.startswith(prefix):
                messaging_entries.append(entry)
            else:
                kept.append(entry)
        if kept:
            non_messaging[event] = kept
    assert messaging_entries, "expected messaging bindings after deploy"
    relocated = dict(non_messaging)
    relocated[wrong_event] = messaging_entries
    manifest_path.write_text(
        json.dumps({"version": 1, "hooks": relocated}, indent=2) + "\n",
        encoding="utf-8",
    )

    report = messaging_hooks_status(workspace=workspace, tool_profile="messaging")
    assert report.complete is False
    assert report.severity == "error"
    assert any(line.startswith("error:") for line in report.lines)


# ---------------------------------------------------------------------------
# CLI: help / locked flag names
# ---------------------------------------------------------------------------


def test_doctor_help_exposes_json_gateway_config_and_probe_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``doctor --help`` documents --json, --gateway-config, and --probe."""
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    result = CliRunner().invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _strip_ansi(result.output)
    assert "--json" in help_text
    assert "--gateway-config" in help_text
    assert "--probe" in help_text
    # LOCKED: doctor must not advertise bare --config (collides with agent config).
    assert "--config " not in help_text.replace("--gateway-config", "")


# ---------------------------------------------------------------------------
# CLI: exit matrix — error → 1; warnings-only → 0
# ---------------------------------------------------------------------------


def test_cli_doctor_error_severity_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any error-severity line (messaging + missing hooks) → exit 1."""
    _prepare_doctor_env(tmp_path, monkeypatch, tool_profile="messaging")
    # No workspace messaging hooks deployed → error under messaging profile.
    result = _invoke_doctor(
        "--gateway-config",
        str(tmp_path / "missing-gateway.yaml"),
    )
    assert result.exit_code == 1, result.output
    assert "error:" in result.output.lower()
    assert (
        "messaging hooks" in result.output.lower() or "hooks" in result.output.lower()
    )


def test_cli_doctor_warnings_only_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warnings alone (e.g. usage OAuth missing) → exit 0; no error: lines."""
    _prepare_doctor_env(
        tmp_path,
        monkeypatch,
        tool_profile="coding",
        oauth_token=None,
    )
    result = _invoke_doctor(
        "--gateway-config",
        str(tmp_path / "missing-gateway.yaml"),
    )
    assert result.exit_code == 0, result.output
    assert "error:" not in result.output.lower()
    assert "warning:" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: gateway absent + --gateway-config honored
# ---------------------------------------------------------------------------


def test_cli_doctor_absent_gateway_yaml_prints_ok_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent gateway YAML → greppable ``ok: gateway.yaml — (absent)``."""
    _prepare_doctor_env(tmp_path, monkeypatch, tool_profile="coding")
    missing = tmp_path / "no-gateway-here.yaml"
    assert not missing.exists()
    result = _invoke_doctor("--gateway-config", str(missing))
    assert result.exit_code == 0, result.output
    assert _GATEWAY_ABSENT_OK in result.output


def test_cli_doctor_gateway_config_flag_honored_for_present_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--gateway-config PATH`` validates the given file (not default path)."""
    workspace = _prepare_doctor_env(tmp_path, monkeypatch, tool_profile="coding")
    gateway_path = tmp_path / "custom" / "gateway.yaml"
    _write_minimal_gateway_yaml(gateway_path, workspace=workspace)

    result = _invoke_doctor("--gateway-config", str(gateway_path))
    assert _GATEWAY_ABSENT_OK not in result.output
    assert "gateway" in result.output.lower()
    # ADR-025: never echo bot_token.
    assert _PLACEHOLDER_BOT_TOKEN not in result.output
    assert _PLACEHOLDER_API_KEY not in result.output


# ---------------------------------------------------------------------------
# CLI: messaging hooks severity by profile
# ---------------------------------------------------------------------------


def test_cli_doctor_messaging_profile_missing_hooks_is_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """messaging profile + missing hooks → error: line and exit 1."""
    _prepare_doctor_env(tmp_path, monkeypatch, tool_profile="messaging")
    result = _invoke_doctor(
        "--gateway-config",
        str(tmp_path / "missing-gateway.yaml"),
    )
    assert result.exit_code == 1, result.output
    lower = result.output.lower()
    assert "error:" in lower
    assert "messaging hooks" in lower or "hooks" in lower


@pytest.mark.parametrize("tool_profile", ["coding", "full"])
def test_cli_doctor_non_messaging_profile_hooks_ok_not_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_profile: str,
) -> None:
    """coding/full without hooks → ok (not required); no warning: for hooks."""
    _prepare_doctor_env(tmp_path, monkeypatch, tool_profile=tool_profile)
    result = _invoke_doctor(
        "--gateway-config",
        str(tmp_path / "missing-gateway.yaml"),
    )
    assert result.exit_code == 0, result.output
    expected = f"{_HOOKS_NOT_REQUIRED_PREFIX} {tool_profile})"
    assert expected in result.output
    # No perpetual warning for the hooks section (auth may still warn elsewhere).
    hooks_lines = [
        line
        for line in result.output.splitlines()
        if "messaging hooks" in line.lower() or "hooks" in line.lower()
    ]
    assert hooks_lines, "expected a messaging hooks status line"
    assert not any(line.lower().startswith("warning:") for line in hooks_lines)


# ---------------------------------------------------------------------------
# CLI: default doctor — no bridge / probe_api_key
# ---------------------------------------------------------------------------


def test_cli_doctor_default_does_not_call_probe_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default ``doctor`` (no ``--probe``) performs zero probe_api_key launches."""
    _prepare_doctor_env(
        tmp_path,
        monkeypatch,
        tool_profile="coding",
        oauth_token="oauth-present-but-must-not-probe",
    )
    probe_calls = _spy_probe_api_key(monkeypatch)

    result = _invoke_doctor(
        "--gateway-config",
        str(tmp_path / "missing-gateway.yaml"),
    )
    assert result.exit_code == 0, result.output
    assert probe_calls == [], (
        f"probe_api_key must not run on default doctor: {probe_calls}"
    )
    assert _PLACEHOLDER_API_KEY not in result.output
    assert "oauth-present-but-must-not-probe" not in result.output


# ---------------------------------------------------------------------------
# CLI: --json shape without secrets
# ---------------------------------------------------------------------------


def test_cli_doctor_json_omits_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``doctor --json`` is machine-readable and never echoes secrets.

    Exit may be 1 when a present messaging gateway makes hooks required —
    secrecy still holds in the JSON payload.
    """
    workspace = _prepare_doctor_env(
        tmp_path,
        monkeypatch,
        tool_profile="coding",
        oauth_token="oauth-secret-json-never-print",
    )
    gateway_path = tmp_path / "gw.yaml"
    _write_minimal_gateway_yaml(gateway_path, workspace=workspace)

    result = _invoke_doctor("--json", "--gateway-config", str(gateway_path))
    data = json.loads(result.output)
    assert isinstance(data, dict)
    serialized = json.dumps(data)
    assert _PLACEHOLDER_API_KEY not in serialized
    assert "oauth-secret-json-never-print" not in serialized
    assert _PLACEHOLDER_BOT_TOKEN not in serialized
    assert _PLACEHOLDER_API_KEY not in result.output
    assert _PLACEHOLDER_BOT_TOKEN not in result.output


def test_cli_doctor_hooks_use_gateway_workspace_when_gateway_config_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Present gateway.yaml drives hooks profile even if agent profile is coding.

    A coding agent config must not report hooks as "not required" when the
    operator points doctor at a messaging gateway with incomplete hooks.
    """
    agent_workspace = _prepare_doctor_env(
        tmp_path,
        monkeypatch,
        tool_profile="coding",
    )
    gateway_workspace = tmp_path / "gateway_ws"
    gateway_workspace.mkdir()
    gateway_path = tmp_path / "gateway.yaml"
    _write_minimal_gateway_yaml(gateway_path, workspace=gateway_workspace)

    result = _invoke_doctor("--gateway-config", str(gateway_path))

    assert result.exit_code == 1, result.output
    lower = result.output.lower()
    assert "error:" in lower
    assert "messaging hooks" in lower or "hooks" in lower
    assert "not required for profile coding" not in result.output
    # Agent workspace must not be the sole hooks target when gateway differs.
    assert agent_workspace != gateway_workspace
