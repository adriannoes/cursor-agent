"""Unit tests for PRD-017 ``auth status`` (Wave 1 / task 2.1 — red until 2.2).

Intended public API (implemented in task 2.2 — these tests must fail until then):

- **Module** ``cursor_agent.auth_status`` with its **own** OAuth status enum
  (``present`` / ``missing`` / ``invalid_store``). Never sniff ``AuthError``
  message strings to derive state.

- **Local resolvers** for the two auth channels (API key + usage OAuth),
  injectable via ``env`` / ``auth_json_path`` for unit tests.

- **CLI** ``cursor-agent auth status`` with ``--json``, ``--probe`` /
  ``--no-probe``. Q1 LOCKED: probes by default when a credential is present;
  ``--no-probe`` is the only offline path (zero ``probe_api_key`` / bridge
  launches, zero usage dashboard fetch).

- **Exit matrix (LOCKED):** API key missing → 1; usage OAuth missing alone
  (API key present, no probe failure) → 0 + ``warning:``; any requested probe
  fails → 1; all pass → 0.

- **Secrets / identity:** never print key/token values, ``api_key_name``, or
  ``user_email`` in human or ``--json`` output (ADR-025).

Pattern: ``tests/unit/test_usage.py`` CliRunner + monkeypatch.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.errors import AuthError, NetworkError
from cursor_agent.usage import USAGE_TOKEN_ENV_VAR


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove Rich/ANSI SGR sequences so flag names are contiguous substrings."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _write_auth_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _stub_load_cwd_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent root Typer callback from reloading CWD ``.env`` into the process env."""
    # WHY: ``load_cwd_dotenv(override=False)`` can re-inject CURSOR_API_KEY from a
    # developer ``.env`` after tests ``delenv`` / set controlled values
    # (same pattern as ``test_models_cli`` / ``test_skills_cli``).
    monkeypatch.setattr("cursor_agent.cli.app.load_cwd_dotenv", lambda: None)


def _invoke_auth_status(monkeypatch: pytest.MonkeyPatch, *args: str) -> Any:
    """Invoke ``auth status`` with hermetic dotenv (no CWD ``.env`` reinjection)."""
    _stub_load_cwd_dotenv(monkeypatch)
    return CliRunner().invoke(app, ["auth", "status", *args])


# ---------------------------------------------------------------------------
# Module: OAuth status enum + local channel resolution
# ---------------------------------------------------------------------------


def test_usage_oauth_status_enum_has_required_tri_state_values() -> None:
    """auth_status owns present / missing / invalid_store (not AuthError sniffing)."""
    from cursor_agent.auth_status import UsageOauthStatus  # noqa: PLC0415 — red until 2.2

    assert UsageOauthStatus.PRESENT.value == "present"
    assert UsageOauthStatus.MISSING.value == "missing"
    assert UsageOauthStatus.INVALID_STORE.value == "invalid_store"


def test_resolve_api_key_local_status_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local API-key channel reports present when CURSOR_API_KEY is non-empty."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        ApiKeyStatus,
        resolve_api_key_local_status,
    )

    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    status = resolve_api_key_local_status()
    assert status == ApiKeyStatus.PRESENT
    assert status.value == "present"


def test_resolve_api_key_local_status_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local API-key channel reports missing when CURSOR_API_KEY is unset/empty."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        ApiKeyStatus,
        resolve_api_key_local_status,
    )

    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    status = resolve_api_key_local_status(env={})
    assert status == ApiKeyStatus.MISSING
    assert status.value == "missing"


def test_resolve_usage_oauth_present_from_env_token(tmp_path: Path) -> None:
    """Env ``CURSOR_AGENT_USAGE_TOKEN`` wins → UsageOauthStatus.PRESENT."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    env: Mapping[str, str] = {USAGE_TOKEN_ENV_VAR: "env-oauth-token"}
    status = resolve_usage_oauth_local_status(
        env=env,
        auth_json_path=tmp_path / "missing.json",
    )
    assert status == UsageOauthStatus.PRESENT


def test_resolve_usage_oauth_present_from_auth_json(tmp_path: Path) -> None:
    """Valid auth.json with accessToken → UsageOauthStatus.PRESENT."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    auth = tmp_path / "auth.json"
    _write_auth_json(auth, {"accessToken": "stored-oauth-token"})
    status = resolve_usage_oauth_local_status(env={}, auth_json_path=auth)
    assert status == UsageOauthStatus.PRESENT


def test_resolve_usage_oauth_missing_when_no_token_or_store(tmp_path: Path) -> None:
    """Absent store and no env token → UsageOauthStatus.MISSING (not invalid_store)."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    status = resolve_usage_oauth_local_status(
        env={},
        auth_json_path=tmp_path / "missing.json",
    )
    assert status == UsageOauthStatus.MISSING


def test_resolve_usage_oauth_invalid_store_for_malformed_auth_json(
    tmp_path: Path,
) -> None:
    """Malformed auth.json → UsageOauthStatus.INVALID_STORE (structural, not string sniff)."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    auth = tmp_path / "auth.json"
    auth.write_text("not json {{{", encoding="utf-8")
    status = resolve_usage_oauth_local_status(env={}, auth_json_path=auth)
    assert status == UsageOauthStatus.INVALID_STORE


def test_resolve_usage_oauth_invalid_store_for_missing_access_token_field(
    tmp_path: Path,
) -> None:
    """Parseable JSON without accessToken → invalid_store (unusable store)."""
    from cursor_agent.auth_status import (  # noqa: PLC0415 — red until 2.2
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    auth = tmp_path / "auth.json"
    _write_auth_json(auth, {"refreshToken": "only-refresh"})
    status = resolve_usage_oauth_local_status(env={}, auth_json_path=auth)
    assert status == UsageOauthStatus.INVALID_STORE


def test_resolve_usage_oauth_invalid_store_for_non_string_access_token(
    tmp_path: Path,
) -> None:
    """Non-string accessToken (list/int) → invalid_store, never PRESENT (PR #80)."""
    from cursor_agent.auth_status import (
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    for bad_token in (["secret"], 12345, {"nested": "x"}):
        auth = tmp_path / f"auth-{type(bad_token).__name__}.json"
        _write_auth_json(auth, {"accessToken": bad_token})
        status = resolve_usage_oauth_local_status(env={}, auth_json_path=auth)
        assert status == UsageOauthStatus.INVALID_STORE, (
            f"expected invalid_store for accessToken={bad_token!r}, received {status!r}"
        )


def test_resolve_usage_oauth_invalid_store_for_non_dict_json(tmp_path: Path) -> None:
    """JSON array/root non-object → invalid_store (structural)."""
    from cursor_agent.auth_status import (  # noqa: PLC0415
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    auth = tmp_path / "auth.json"
    auth.write_text("[]", encoding="utf-8")
    status = resolve_usage_oauth_local_status(env={}, auth_json_path=auth)
    assert status == UsageOauthStatus.INVALID_STORE


def test_resolve_usage_oauth_invalid_store_when_auth_json_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OSError reading auth.json → invalid_store (not missing)."""
    from cursor_agent.auth_status import (  # noqa: PLC0415
        UsageOauthStatus,
        resolve_usage_oauth_local_status,
    )

    auth = tmp_path / "auth.json"
    auth.write_text('{"accessToken": "x"}', encoding="utf-8")
    original_read_text = Path.read_text

    def _boom(self: Path, *args: object, **kwargs: object) -> str:
        if self == auth:
            raise OSError("permission denied: simulated unreadable auth.json")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _boom)
    status = resolve_usage_oauth_local_status(env={}, auth_json_path=auth)
    assert status == UsageOauthStatus.INVALID_STORE


# ---------------------------------------------------------------------------
# CLI: help / flags
# ---------------------------------------------------------------------------


def test_auth_status_help_exposes_json_probe_and_no_probe_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auth status --help`` documents --json, --probe, and --no-probe."""
    # Reproduce CI: colored Rich help splits "--json" across ANSI SGR codes.
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    result = CliRunner().invoke(app, ["auth", "status", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _strip_ansi(result.output)
    assert "--json" in help_text
    assert "--probe" in help_text
    assert "--no-probe" in help_text


# ---------------------------------------------------------------------------
# CLI: local exit matrix + output labels
# ---------------------------------------------------------------------------


def test_cli_auth_status_missing_api_key_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """API key missing → exit 1 (REPL unusable), even with --no-probe."""
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv(USAGE_TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke_auth_status(monkeypatch, "--no-probe")
    assert result.exit_code == 1
    assert "api_key" in result.output.lower()


def test_cli_auth_status_oauth_missing_alone_exits_zero_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """API key present + OAuth missing + no probe failure → exit 0 + warning:."""
    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.delenv(USAGE_TOKEN_ENV_VAR, raising=False)
    # Point home away from a real auth.json so OAuth resolves as missing.
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke_auth_status(monkeypatch, "--no-probe")
    assert result.exit_code == 0, result.output
    assert "warning:" in result.output.lower()
    assert "api_key:" in result.output
    assert "usage_oauth:" in result.output
    # Optional-channel copy: missing OAuth must not read like a broken install.
    assert "optional" in result.output.lower(), result.output
    assert "cursor-agent usage" in result.output, result.output
    assert "repl" in result.output.lower(), result.output


def test_cli_auth_status_all_local_channels_present_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both channels present locally with --no-probe → exit 0."""
    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-token-present")
    monkeypatch.setenv("HOME", str(tmp_path))
    result = _invoke_auth_status(monkeypatch, "--no-probe")
    assert result.exit_code == 0, result.output
    assert "api_key:" in result.output
    assert "usage_oauth:" in result.output
    assert "sk-test-present" not in result.output
    assert "oauth-token-present" not in result.output


def test_cli_auth_status_invalid_store_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """API key present + malformed auth.json + --no-probe → exit 1 (invalid_store)."""
    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.delenv(USAGE_TOKEN_ENV_VAR, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    auth = tmp_path / ".config" / "cursor" / "auth.json"
    _write_auth_json(auth, {"refreshToken": "only-refresh-no-access"})
    result = _invoke_auth_status(monkeypatch, "--no-probe")
    assert result.exit_code == 1, result.output
    assert "usage_oauth:" in result.output
    assert "invalid_store" in result.output
    assert "sk-test-present" not in result.output
    assert "only-refresh-no-access" not in result.output


# ---------------------------------------------------------------------------
# CLI: --no-probe must not launch bridge / call probe_api_key
# ---------------------------------------------------------------------------


def test_cli_auth_status_no_probe_does_not_call_probe_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--no-probe`` performs zero probe_api_key / bridge launches."""
    probe_calls: list[object] = []

    async def _spy_probe_api_key(**kwargs: object) -> bool:
        probe_calls.append(kwargs)
        return True

    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-token-present")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "cursor_agent.auth_status.probe_api_key",
        _spy_probe_api_key,
        raising=True,
    )

    fetch_calls: list[object] = []

    def _spy_fetch(*, token: str, **kwargs: object) -> dict[str, object]:
        fetch_calls.append({"token": token, **kwargs})
        return {}

    monkeypatch.setattr(
        "cursor_agent.auth_status.fetch_current_period_usage",
        _spy_fetch,
        raising=True,
    )

    result = _invoke_auth_status(monkeypatch, "--no-probe")
    assert result.exit_code == 0, result.output
    assert probe_calls == [], (
        f"probe_api_key must not run under --no-probe: {probe_calls}"
    )
    assert fetch_calls == [], (
        f"usage dashboard fetch must not run under --no-probe: {fetch_calls}"
    )


# ---------------------------------------------------------------------------
# CLI: probe failure → exit 1
# ---------------------------------------------------------------------------


def test_cli_auth_status_probe_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Any requested probe failure (API key channel) → exit 1."""

    async def _failing_probe(**kwargs: object) -> bool:
        raise AuthError("cursor auth probe: API key rejected by Cursor.me")

    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-token-present")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "cursor_agent.auth_status.probe_api_key",
        _failing_probe,
        raising=True,
    )

    # Default is probe-on when credentials are present (Q1).
    result = _invoke_auth_status(monkeypatch)
    assert result.exit_code == 1, result.output
    assert "sk-test-present" not in result.output
    assert "oauth-token-present" not in result.output


def test_cli_auth_status_unmapped_probe_exception_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Unexpected probe Exception becomes probe:error + exit 1 (no traceback)."""

    async def _boom_probe(**kwargs: object) -> bool:
        raise AttributeError("simulated unmapped SDK attribute fault")

    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-token-present")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "cursor_agent.auth_status.probe_api_key",
        _boom_probe,
        raising=True,
    )

    result = _invoke_auth_status(monkeypatch)
    assert result.exit_code == 1, result.output
    assert "AttributeError" not in result.output
    assert "Traceback" not in result.output
    assert "sk-test-present" not in result.output


def test_cli_auth_status_present_oauth_unreadable_token_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Defensive path: local PRESENT but token reader returns None → probe fail."""
    from cursor_agent.auth_status import (  # noqa: PLC0415
        ApiKeyStatus,
        UsageOauthStatus,
    )

    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-token-present")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "cursor_agent.auth_status.resolve_api_key_local_status",
        lambda **_: ApiKeyStatus.PRESENT,
    )
    monkeypatch.setattr(
        "cursor_agent.auth_status._load_usage_oauth",
        lambda **_: (UsageOauthStatus.PRESENT, None),
    )

    async def _ok_probe(**kwargs: object) -> bool:
        return True

    monkeypatch.setattr(
        "cursor_agent.auth_status.probe_api_key",
        _ok_probe,
        raising=True,
    )

    result = _invoke_auth_status(monkeypatch)
    assert result.exit_code == 1, result.output


def test_cli_auth_status_usage_oauth_probe_failure_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Usage-channel dashboard probe failure → exit 1."""

    async def _ok_probe(**kwargs: object) -> bool:
        return True

    def _failing_fetch(*, token: str, **kwargs: object) -> dict[str, object]:
        raise NetworkError("cursor usage: failed to reach dashboard endpoint: refused")

    monkeypatch.setenv("CURSOR_API_KEY", "sk-test-present")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-token-present")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "cursor_agent.auth_status.probe_api_key",
        _ok_probe,
        raising=True,
    )
    monkeypatch.setattr(
        "cursor_agent.auth_status.fetch_current_period_usage",
        _failing_fetch,
        raising=True,
    )

    result = _invoke_auth_status(monkeypatch)
    assert result.exit_code == 1, result.output
    assert "oauth-token-present" not in result.output


# ---------------------------------------------------------------------------
# CLI: --json shape without secrets or identity fields
# ---------------------------------------------------------------------------


def test_cli_auth_status_json_shape_omits_secrets_and_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``--json`` is machine-readable status enums / booleans — no secrets or me identity."""
    monkeypatch.setenv("CURSOR_API_KEY", "sk-secret-never-print")
    monkeypatch.setenv(USAGE_TOKEN_ENV_VAR, "oauth-secret-never-print")
    monkeypatch.setenv("HOME", str(tmp_path))

    async def _ok_probe(**kwargs: object) -> bool:
        return True

    def _ok_fetch(*, token: str, **kwargs: object) -> dict[str, object]:
        return {"planUsage": {"totalPercentUsed": 1.0}}

    monkeypatch.setattr(
        "cursor_agent.auth_status.probe_api_key",
        _ok_probe,
        raising=True,
    )
    monkeypatch.setattr(
        "cursor_agent.auth_status.fetch_current_period_usage",
        _ok_fetch,
        raising=True,
    )

    result = _invoke_auth_status(monkeypatch, "--json", "--no-probe")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, dict)

    serialized = json.dumps(data)
    assert "sk-secret-never-print" not in serialized
    assert "oauth-secret-never-print" not in serialized
    assert "api_key_name" not in serialized
    assert "user_email" not in serialized
    assert "api_key_name" not in data
    assert "user_email" not in data

    # Stable channel keys (exact nested shape is owned by 2.2; top-level channels required).
    assert "api_key" in data
    assert "usage_oauth" in data
