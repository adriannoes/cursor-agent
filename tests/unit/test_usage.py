"""Unit tests for the plan-usage query module and CLI command."""

from __future__ import annotations

import email.message
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.errors import AuthError, NetworkError
from cursor_agent.usage import (
    USAGE_TOKEN_ENV_VAR,
    fetch_current_period_usage,
    format_plan_usage,
    parse_plan_usage,
    resolve_usage_access_token,
)


def _epoch_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


_PAYLOAD: dict[str, Any] = {
    "billingCycleStart": _epoch_ms(2026, 7, 5),
    "billingCycleEnd": _epoch_ms(2026, 8, 5),
    "planUsage": {
        "totalPercentUsed": 93.4,
        "autoPercentUsed": 96.9,
        "apiPercentUsed": 68.3,
        "includedSpend": 7000,
        "limit": 7000,
    },
    "displayMessage": "You've hit your usage limit",
}


def _write_auth_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------


def test_resolve_token_env_wins(tmp_path: Path) -> None:
    env = {USAGE_TOKEN_ENV_VAR: "env-token"}
    token = resolve_usage_access_token(
        env=env,
        auth_json_path=tmp_path / "missing.json",
    )
    assert token == "env-token"


def test_resolve_token_from_auth_json(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    _write_auth_json(auth, {"accessToken": "stored-token"})
    assert resolve_usage_access_token(env={}, auth_json_path=auth) == "stored-token"


def test_resolve_token_missing_store_raises(tmp_path: Path) -> None:
    with pytest.raises(AuthError, match="no access token"):
        resolve_usage_access_token(env={}, auth_json_path=tmp_path / "missing.json")


def test_resolve_token_malformed_store_raises(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text("not json", encoding="utf-8")
    with pytest.raises(AuthError, match="invalid auth store"):
        resolve_usage_access_token(env={}, auth_json_path=auth)


def test_resolve_token_missing_field_raises(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    _write_auth_json(auth, {"refreshToken": "only-refresh"})
    with pytest.raises(AuthError, match="no accessToken"):
        resolve_usage_access_token(env={}, auth_json_path=auth)


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _install_urlopen(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", fake)


def test_fetch_posts_bearer_and_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        captured["request"] = args[0]
        return _FakeResponse(json.dumps(_PAYLOAD).encode())

    _install_urlopen(monkeypatch, fake)
    payload = fetch_current_period_usage(token="tok123")

    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.headers.get("Authorization") == "Bearer tok123"
    assert payload["planUsage"]["totalPercentUsed"] == 93.4


def test_fetch_401_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "https://x", 401, "Unauthorized", email.message.Message(), None
        )

    _install_urlopen(monkeypatch, fake)
    with pytest.raises(AuthError, match="401"):
        fetch_current_period_usage(token="tok123")


def test_fetch_403_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "https://x", 403, "Forbidden", email.message.Message(), None
        )

    _install_urlopen(monkeypatch, fake)
    with pytest.raises(AuthError, match="403"):
        fetch_current_period_usage(token="tok123")


def test_fetch_500_raises_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "https://x", 500, "Server Error", email.message.Message(), None
        )

    _install_urlopen(monkeypatch, fake)
    with pytest.raises(NetworkError, match="HTTP 500"):
        fetch_current_period_usage(token="tok123")


def test_fetch_connection_failure_raises_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        raise urllib.error.URLError("connection refused")

    _install_urlopen(monkeypatch, fake)
    with pytest.raises(NetworkError, match="failed to reach"):
        fetch_current_period_usage(token="tok123")


def test_fetch_non_json_raises_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(b"<html>oops</html>")

    _install_urlopen(monkeypatch, fake)
    with pytest.raises(NetworkError, match="non-JSON"):
        fetch_current_period_usage(token="tok123")


def test_fetch_non_dict_payload_raises_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake(*args: Any, **kwargs: Any) -> _FakeResponse:
        return _FakeResponse(b"[1, 2, 3]")

    _install_urlopen(monkeypatch, fake)
    with pytest.raises(NetworkError, match="unexpected shape"):
        fetch_current_period_usage(token="tok123")


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def test_parse_full_payload() -> None:
    usage = parse_plan_usage(_PAYLOAD)
    assert usage.billing_cycle_start_ms == _epoch_ms(2026, 7, 5)
    assert usage.billing_cycle_end_ms == _epoch_ms(2026, 8, 5)
    assert usage.total_percent_used == 93.4
    assert usage.auto_percent_used == 96.9
    assert usage.api_percent_used == 68.3
    assert usage.included_spend_cents == 7000
    assert usage.limit_cents == 7000
    assert usage.display_message == "You've hit your usage limit"


def test_parse_empty_payload_yields_none_fields() -> None:
    usage = parse_plan_usage({})
    assert usage.total_percent_used is None
    assert usage.auto_percent_used is None
    assert usage.api_percent_used is None
    assert usage.billing_cycle_start_ms is None
    assert usage.display_message is None


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


def test_format_renders_percentages_and_remaining() -> None:
    text = format_plan_usage(parse_plan_usage(_PAYLOAD))
    assert "billing_cycle: 2026-07-05 -> 2026-08-05" in text
    assert "total: used=93.4% remaining=6.6%" in text
    assert "auto : used=96.9% remaining=3.1%" in text
    assert "api  : used=68.3% remaining=31.7%" in text
    assert "included_spend_cents: 7000 / limit_cents: 7000" in text
    assert "display_message: You've hit your usage limit" in text


def test_format_handles_missing_fields() -> None:
    text = format_plan_usage(parse_plan_usage({}))
    assert "billing_cycle: unknown -> unknown" in text
    assert "total: used=unknown" in text
    assert "display_message" not in text
    assert "included_spend_cents" not in text


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


def test_cli_usage_prints_formatted_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cursor_agent.cli.usage_command.resolve_usage_access_token",
        lambda: "tok123",
    )
    monkeypatch.setattr(
        "cursor_agent.cli.usage_command.fetch_current_period_usage",
        lambda *, token: _PAYLOAD,
    )
    result = CliRunner().invoke(app, ["usage"])
    assert result.exit_code == 0
    assert "total: used=93.4% remaining=6.6%" in result.output


def test_cli_usage_json_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cursor_agent.cli.usage_command.resolve_usage_access_token",
        lambda: "tok123",
    )
    monkeypatch.setattr(
        "cursor_agent.cli.usage_command.fetch_current_period_usage",
        lambda *, token: _PAYLOAD,
    )
    result = CliRunner().invoke(app, ["usage", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_percent_used"] == 93.4
    assert data["billing_cycle_end_ms"] == _epoch_ms(2026, 8, 5)


def test_cli_usage_auth_failure_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = AuthError("cursor usage: no access token for test")

    def _raise() -> str:
        raise failure

    monkeypatch.setattr(
        "cursor_agent.cli.usage_command.resolve_usage_access_token",
        _raise,
    )
    result = CliRunner().invoke(app, ["usage"])
    assert result.exit_code == exit_code_for_error(failure)
    assert "no access token" in result.output
