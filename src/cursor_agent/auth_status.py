"""Local auth-channel resolution and live probes for ``auth status`` (PRD-017 FR-1).

Owns the usage-OAuth tri-state enum (``present`` / ``missing`` / ``invalid_store``)
derived from structural env / ``auth.json`` inspection — never from
``AuthError`` message text. Live probes reuse facade ``probe_api_key`` and
``fetch_current_period_usage`` (boolean ok only; no secrets or identity).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from cursor_agent.sdk_facade import AUTH_PROBE_TIMEOUT_SECONDS, probe_api_key
from cursor_agent.usage import (
    USAGE_TOKEN_ENV_VAR,
    default_cursor_cli_auth_path,
    fetch_current_period_usage,
)

API_KEY_ENV_VAR = "CURSOR_API_KEY"

_OAUTH_MISSING_WARNING = (
    "warning: usage OAuth missing (optional) — required only for "
    f"`cursor-agent usage`, not for the REPL; run `agent login` "
    f"(official Cursor Agent CLI) or set {USAGE_TOKEN_ENV_VAR}"
)


class ApiKeyStatus(StrEnum):
    """Local presence of ``CURSOR_API_KEY``."""

    PRESENT = "present"
    MISSING = "missing"


class UsageOauthStatus(StrEnum):
    """Structural outcome for the usage-OAuth channel (auth_status-owned)."""

    PRESENT = "present"
    MISSING = "missing"
    INVALID_STORE = "invalid_store"


@dataclass(frozen=True)
class AuthChannelReport:
    """Aggregated local (+ optional probe) status for both auth channels.

    Example::

        report = collect_auth_channel_report(probe=False)
        print(format_auth_status_human(report))
    """

    api_key: ApiKeyStatus
    usage_oauth: UsageOauthStatus
    api_key_probe_ok: bool | None = None
    usage_oauth_probe_ok: bool | None = None
    warning: str | None = None


def resolve_api_key_local_status(
    *,
    env: Mapping[str, str] | None = None,
) -> ApiKeyStatus:
    """Return ``present`` when ``CURSOR_API_KEY`` is a non-empty string.

    Example::

        status = resolve_api_key_local_status(env={"CURSOR_API_KEY": "sk-…"})
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    key = (environ.get(API_KEY_ENV_VAR) or "").strip()
    if key:
        return ApiKeyStatus.PRESENT
    return ApiKeyStatus.MISSING


def resolve_usage_oauth_local_status(
    *,
    env: Mapping[str, str] | None = None,
    auth_json_path: Path | None = None,
) -> UsageOauthStatus:
    """Resolve usage OAuth via env token or structural ``auth.json`` inspection.

    Precedence: non-empty ``CURSOR_AGENT_USAGE_TOKEN``, then the auth store.
    Distinguishes missing file (``missing``) from malformed JSON / missing
    ``accessToken`` (``invalid_store``) without sniffing ``AuthError`` text.

    Example::

        status = resolve_usage_oauth_local_status(env={}, auth_json_path=path)
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    path = (
        auth_json_path if auth_json_path is not None else default_cursor_cli_auth_path()
    )
    status, _token = _load_usage_oauth(env=environ, auth_json_path=path)
    return status


def _load_usage_oauth(
    *,
    env: Mapping[str, str],
    auth_json_path: Path,
) -> tuple[UsageOauthStatus, str | None]:
    """Load usage-OAuth status and token from env or ``auth.json`` once.

    Returns:
        ``(PRESENT, token)`` when env or store has a non-empty token;
        ``(MISSING, None)`` when the auth store file is absent;
        ``(INVALID_STORE, None)`` when the store is unreadable or malformed.
    """
    env_token = (env.get(USAGE_TOKEN_ENV_VAR) or "").strip()
    if env_token:
        return UsageOauthStatus.PRESENT, env_token
    if not auth_json_path.is_file():
        return UsageOauthStatus.MISSING, None
    try:
        raw = auth_json_path.read_text(encoding="utf-8")
    except OSError:
        return UsageOauthStatus.INVALID_STORE, None
    try:
        data: object = json.loads(raw)
    except json.JSONDecodeError:
        return UsageOauthStatus.INVALID_STORE, None
    if not isinstance(data, dict):
        return UsageOauthStatus.INVALID_STORE, None
    # WHY (PR #80): str([...]) / str(12345) must not count as a present token.
    access_raw = data.get("accessToken")
    if not isinstance(access_raw, str):
        return UsageOauthStatus.INVALID_STORE, None
    access = access_raw.strip()
    if not access:
        return UsageOauthStatus.INVALID_STORE, None
    return UsageOauthStatus.PRESENT, access


def _probe_api_key_channel(api_key: str) -> bool:
    """Run facade ``probe_api_key`` with ``AUTH_PROBE_TIMEOUT_SECONDS``."""
    return asyncio.run(
        probe_api_key(
            api_key=api_key,
            timeout_seconds=AUTH_PROBE_TIMEOUT_SECONDS,
        )
    )


def _probe_usage_oauth_channel(token: str) -> bool:
    """Dashboard fetch success ⇒ ok; discard usage payload numbers."""
    fetch_current_period_usage(token=token)
    return True


def collect_auth_channel_report(
    *,
    probe: bool = True,
    env: Mapping[str, str] | None = None,
    auth_json_path: Path | None = None,
) -> AuthChannelReport:
    """Collect local channel status and optionally run live probes.

    Q1: when ``probe`` is true, probe each channel that is locally ``present``.
    ``probe=False`` (``--no-probe``) performs zero ``probe_api_key`` / dashboard
    fetches.

    Example::

        report = collect_auth_channel_report(probe=False)
    """
    environ: Mapping[str, str] = os.environ if env is None else env
    path = (
        auth_json_path if auth_json_path is not None else default_cursor_cli_auth_path()
    )
    api_key_status = resolve_api_key_local_status(env=environ)
    oauth_status, oauth_token = _load_usage_oauth(env=environ, auth_json_path=path)

    api_key_probe_ok: bool | None = None
    usage_oauth_probe_ok: bool | None = None

    if probe and api_key_status is ApiKeyStatus.PRESENT:
        api_key_value = (environ.get(API_KEY_ENV_VAR) or "").strip()
        try:
            api_key_probe_ok = _probe_api_key_channel(api_key_value)
        except Exception:
            # WHY: FR-1 probe failure → exit 1; unmapped SDK/runtime faults must
            # not dump a traceback from the CLI (KeyboardInterrupt still propagates).
            api_key_probe_ok = False

    if probe and oauth_status is UsageOauthStatus.PRESENT:
        if oauth_token is None:
            usage_oauth_probe_ok = False
        else:
            try:
                usage_oauth_probe_ok = _probe_usage_oauth_channel(oauth_token)
            except Exception:
                usage_oauth_probe_ok = False

    warning: str | None = None
    if (
        api_key_status is ApiKeyStatus.PRESENT
        and oauth_status is UsageOauthStatus.MISSING
        and api_key_probe_ok is not False
        and usage_oauth_probe_ok is not False
    ):
        warning = _OAUTH_MISSING_WARNING

    return AuthChannelReport(
        api_key=api_key_status,
        usage_oauth=oauth_status,
        api_key_probe_ok=api_key_probe_ok,
        usage_oauth_probe_ok=usage_oauth_probe_ok,
        warning=warning,
    )


def exit_code_for_auth_status(report: AuthChannelReport) -> int:
    """Map an auth-channel report to the FR-1 exit matrix.

    Example::

        raise typer.Exit(exit_code_for_auth_status(report))
    """
    if report.api_key is ApiKeyStatus.MISSING:
        return 1
    if report.usage_oauth is UsageOauthStatus.INVALID_STORE:
        return 1
    if report.api_key_probe_ok is False:
        return 1
    if report.usage_oauth_probe_ok is False:
        return 1
    return 0


def _format_channel_line(
    label: str,
    status: str,
    probe_ok: bool | None,
) -> str:
    if probe_ok is None:
        return f"{label}: {status}"
    probe_label = "ok" if probe_ok else "error"
    return f"{label}: {status} (probe: {probe_label})"


def format_auth_status_human(report: AuthChannelReport) -> str:
    """Render greppable human lines (no secrets or identity fields).

    Example::

        print(format_auth_status_human(report))
    """
    lines = [
        _format_channel_line("api_key", report.api_key.value, report.api_key_probe_ok),
        _format_channel_line(
            "usage_oauth",
            report.usage_oauth.value,
            report.usage_oauth_probe_ok,
        ),
    ]
    if report.warning is not None:
        lines.append(report.warning)
    return "\n".join(lines)


def auth_status_to_json_dict(report: AuthChannelReport) -> dict[str, Any]:
    """Serialize channel enums / probe booleans — never secrets or identity.

    Example::

        print(json.dumps(auth_status_to_json_dict(report)))
    """
    api_key_payload: dict[str, Any] = {"status": report.api_key.value}
    oauth_payload: dict[str, Any] = {"status": report.usage_oauth.value}
    if report.api_key_probe_ok is not None:
        api_key_payload["probe_ok"] = report.api_key_probe_ok
    if report.usage_oauth_probe_ok is not None:
        oauth_payload["probe_ok"] = report.usage_oauth_probe_ok
    payload: dict[str, Any] = {
        "api_key": api_key_payload,
        "usage_oauth": oauth_payload,
    }
    if report.warning is not None:
        payload["warning"] = report.warning
    return payload
