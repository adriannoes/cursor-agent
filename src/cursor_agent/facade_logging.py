"""NDJSON logging helpers for SdkFacade send and command lifecycle (ADR-018, ADR-025)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_LOG_SCHEMA_VERSION = 1
_REDACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"bot[0-9]+:[A-Za-z0-9_-]+"),
)


@dataclass(frozen=True)
class LogContext:
    """Optional observability context for facade send logs."""

    session_id: str | None = None
    session_key: str | None = None
    agent_id: str | None = None


def _utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp with millisecond precision."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _redact(value: object) -> object:
    """Redact secret-like substrings from log field values."""
    if not isinstance(value, str):
        return value
    redacted = value
    for pattern in _REDACT_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def _base_payload(
    *,
    event: str,
    agent_id: str,
    log_context: LogContext | None,
    run_id: str | None = None,
    duration_ms: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build the shared NDJSON schema v1 fields for facade send events."""
    ctx_agent_id = log_context.agent_id if log_context is not None else None
    payload: dict[str, Any] = {
        "v": _LOG_SCHEMA_VERSION,
        "ts": _utc_timestamp(),
        "level": "info",
        "event": event,
        "session_id": log_context.session_id if log_context else None,
        "session_key": log_context.session_key if log_context else None,
        "agent_id": _redact(ctx_agent_id or agent_id),
        "run_id": run_id,
    }
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if status is not None:
        payload["status"] = status
    return payload


def emit_send_start(
    logger: logging.Logger,
    *,
    agent_id: str,
    log_context: LogContext | None = None,
) -> None:
    """Emit NDJSON ``send_start`` before a facade send begins.

    Example:
        emit_send_start(logger, agent_id="agent-1")
    """
    payload = _base_payload(
        event="send_start", agent_id=agent_id, log_context=log_context
    )
    logger.info(json.dumps(payload, separators=(",", ":")))


def emit_send_end(
    logger: logging.Logger,
    *,
    agent_id: str,
    run_id: str,
    duration_ms: int,
    status: str,
    log_context: LogContext | None = None,
) -> None:
    """Emit NDJSON ``send_end`` after a facade send completes.

    Example:
        emit_send_end(logger, agent_id="a", run_id="r", duration_ms=10, status="finished")
    """
    payload = _base_payload(
        event="send_end",
        agent_id=agent_id,
        log_context=log_context,
        run_id=run_id,
        duration_ms=duration_ms,
        status=status,
    )
    logger.info(json.dumps(payload, separators=(",", ":")))


def _command_payload(
    *,
    event: str,
    command: str,
    session_id: str | None,
    session_key: str | None,
    agent_id: str | None = None,
    duration_ms: int | None = None,
    outcome: str | None = None,
) -> dict[str, Any]:
    """Build NDJSON schema v1 fields for command lifecycle events."""
    payload: dict[str, Any] = {
        "v": _LOG_SCHEMA_VERSION,
        "ts": _utc_timestamp(),
        "level": "info",
        "event": event,
        "command": command,
        "session_id": session_id,
        "session_key": session_key,
    }
    if agent_id is not None:
        payload["agent_id"] = _redact(agent_id)
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if outcome is not None:
        payload["outcome"] = outcome
    return payload


def emit_command_start(
    logger: logging.Logger,
    *,
    command: str,
    session_id: str | None = None,
    session_key: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Emit NDJSON ``command_start`` before a slash command handler runs.

    Example:
        emit_command_start(
            logger, command="help", session_id="sess-1", session_key="cli:default:abc"
        )
    """
    payload = _command_payload(
        event="command_start",
        command=command,
        session_id=session_id,
        session_key=session_key,
        agent_id=agent_id,
    )
    logger.info(json.dumps(payload, separators=(",", ":")))


def emit_command_end(
    logger: logging.Logger,
    *,
    command: str,
    outcome: str,
    duration_ms: int,
    session_id: str | None = None,
    session_key: str | None = None,
    agent_id: str | None = None,
) -> None:
    """Emit NDJSON ``command_end`` after a slash command handler completes.

    Example:
        emit_command_end(
            logger,
            command="quit",
            outcome="quit",
            duration_ms=3,
            session_key="cli:default:abc",
        )
    """
    payload = _command_payload(
        event="command_end",
        command=command,
        session_id=session_id,
        session_key=session_key,
        agent_id=agent_id,
        duration_ms=duration_ms,
        outcome=outcome,
    )
    logger.info(json.dumps(payload, separators=(",", ":")))
