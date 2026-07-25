"""Cursor plan usage via the dashboard endpoint (undocumented).

The Cursor SDK exposes no usage API. This module queries the same
``aiserver.v1.DashboardService/GetCurrentPeriodUsage`` endpoint that the
Cursor IDE and web dashboard use, authenticated with the OAuth access token
stored by the official Cursor Agent CLI at ``~/.config/cursor/auth.json``
(or the ``CURSOR_AGENT_USAGE_TOKEN`` environment override). The endpoint is
undocumented and may change without notice; failures surface as
:class:`~cursor_agent.errors.AuthError` or
:class:`~cursor_agent.errors.NetworkError` with actionable messages.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cursor_agent.errors import AuthError, NetworkError

USAGE_TOKEN_ENV_VAR = "CURSOR_AGENT_USAGE_TOKEN"
DEFAULT_USAGE_URL = (
    "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
)
DEFAULT_TIMEOUT_SECONDS = 15.0


def default_cursor_cli_auth_path() -> Path:
    """Default auth store written by the official Cursor Agent CLI login."""
    return Path.home() / ".config" / "cursor" / "auth.json"


def resolve_usage_access_token(
    *,
    env: Mapping[str, str] | None = None,
    auth_json_path: Path | None = None,
) -> str:
    """Resolve the OAuth access token for the dashboard endpoint.

    Precedence: ``CURSOR_AGENT_USAGE_TOKEN`` environment variable, then the
    official Cursor Agent CLI auth store at ``~/.config/cursor/auth.json``.
    The token is never logged or returned to callers other than the caller.
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    token = (environ.get(USAGE_TOKEN_ENV_VAR) or "").strip()
    if token:
        return token

    path = (
        auth_json_path if auth_json_path is not None else default_cursor_cli_auth_path()
    )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthError(
            f"cursor usage: no access token — set {USAGE_TOKEN_ENV_VAR} or log in "
            f"the official Cursor CLI (expected auth store at {path})"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthError(
            f"cursor usage: invalid auth store at {path} — expected JSON with "
            "an 'accessToken' field"
        ) from exc
    token = str(data.get("accessToken") or "").strip()
    if not token:
        raise AuthError(
            f"cursor usage: auth store at {path} has no accessToken — run "
            "'cursor-agent login' (official CLI) to refresh"
        )
    return token


def fetch_current_period_usage(
    *,
    token: str,
    url: str = DEFAULT_USAGE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """POST ``GetCurrentPeriodUsage`` and return the decoded JSON payload."""
    request = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AuthError(
                "cursor usage: dashboard endpoint rejected the access token "
                f"(HTTP {exc.code}) — run 'cursor-agent login' (official CLI) "
                f"or set a fresh {USAGE_TOKEN_ENV_VAR}"
            ) from exc
        raise NetworkError(
            f"cursor usage: dashboard endpoint returned HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise NetworkError(
            f"cursor usage: failed to reach dashboard endpoint: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise NetworkError("cursor usage: dashboard request timed out") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NetworkError(
            "cursor usage: dashboard endpoint returned non-JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise NetworkError(
            "cursor usage: dashboard endpoint returned unexpected shape — "
            "expected a JSON object"
        )
    return payload


@dataclass(frozen=True)
class PlanUsage:
    """Parsed snapshot of the current billing-period plan usage."""

    billing_cycle_start_ms: int | None
    billing_cycle_end_ms: int | None
    total_percent_used: float | None
    auto_percent_used: float | None
    api_percent_used: float | None
    included_spend_cents: int | None
    limit_cents: int | None
    display_message: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return the snapshot as a plain JSON-serializable mapping."""
        return asdict(self)


def _optional_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def parse_plan_usage(payload: Mapping[str, Any]) -> PlanUsage:
    """Extract plan-usage fields from a dashboard payload."""
    plan = payload.get("planUsage")
    plan_usage: Mapping[str, Any] = plan if isinstance(plan, Mapping) else {}
    return PlanUsage(
        billing_cycle_start_ms=_optional_int(payload.get("billingCycleStart")),
        billing_cycle_end_ms=_optional_int(payload.get("billingCycleEnd")),
        total_percent_used=_optional_float(plan_usage.get("totalPercentUsed")),
        auto_percent_used=_optional_float(plan_usage.get("autoPercentUsed")),
        api_percent_used=_optional_float(plan_usage.get("apiPercentUsed")),
        included_spend_cents=_optional_int(plan_usage.get("includedSpend")),
        limit_cents=_optional_int(plan_usage.get("limit")),
        display_message=_optional_str(payload.get("displayMessage")),
    )


def _format_epoch_ms(value: int | None) -> str:
    if value is None:
        return "unknown"
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _format_percent_line(label: str, percent_used: float | None) -> str:
    if percent_used is None:
        return f"{label}: used=unknown"
    remaining = round(100.0 - percent_used, 1)
    return f"{label}: used={round(percent_used, 1)}% remaining={remaining}%"


def format_plan_usage(usage: PlanUsage) -> str:
    """Render a plan-usage snapshot as human-readable lines."""
    lines = [
        f"billing_cycle: {_format_epoch_ms(usage.billing_cycle_start_ms)} -> "
        f"{_format_epoch_ms(usage.billing_cycle_end_ms)}",
        _format_percent_line("total", usage.total_percent_used),
        _format_percent_line("auto ", usage.auto_percent_used),
        _format_percent_line("api  ", usage.api_percent_used),
    ]
    if usage.included_spend_cents is not None:
        lines.append(
            f"included_spend_cents: {usage.included_spend_cents} / "
            f"limit_cents: {usage.limit_cents}"
        )
    if usage.display_message:
        lines.append(f"display_message: {usage.display_message}")
    return "\n".join(lines)
