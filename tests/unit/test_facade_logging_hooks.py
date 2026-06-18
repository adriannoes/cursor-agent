"""Unit tests for hook-related facade logging events."""

from __future__ import annotations

import json
import logging


def test_hook_deploy_log_redacts_error_text() -> None:
    """Hook deploy failure logs redact secret-like error substrings."""
    from cursor_agent.facade_logging import emit_hook_deploy

    logger = logging.getLogger("test.hooks.deploy.error")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_hook_deploy(
        logger,
        profile="messaging",
        workspace="/tmp/workspace",
        status="error",
        error="Bearer sk-live-secret",
    )

    logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["event"] == "hook_deploy"
    assert payload["status"] == "error"
    assert payload["error"] == "[REDACTED]"
    assert "sk-live-secret" not in payload["error"]


def test_hook_deny_log_emits_ndjson_with_redacted_fields() -> None:
    """Hook deny audit uses a dedicated event shape with redacted identifiers."""
    from cursor_agent.facade_logging import emit_hook_deny

    logger = logging.getLogger("test.hooks.deny")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_hook_deny(
        logger,
        hook_name="beforeShellExecution",
        tool_name="Shell",
        reason="denied destructive command",
        session_id="sess-1",
        session_key="cli:default:abc12345",
        agent_id="sk-live-secret",
    )

    logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["v"] == 1
    assert payload["event"] == "hook_deny"
    assert payload["hook_name"] == "beforeShellExecution"
    assert payload["tool_name"] == "Shell"
    assert payload["reason"] == "denied destructive command"
    assert payload["session_id"] == "sess-1"
    assert payload["session_key"] == "cli:default:abc12345"
    assert payload["agent_id"] == "[REDACTED]"
    assert "command_end" not in payload["event"]
    assert "payload" not in payload


def test_pool_agent_reattach_log_emits_ndjson_with_redacted_agent_ids() -> None:
    """pool_agent_reattach logs session ids and redacts agent ids."""
    from cursor_agent.facade_logging import emit_pool_agent_reattach

    logger = logging.getLogger("test.pool.reattach")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_pool_agent_reattach(
        logger,
        session_id="sess-reattach-1",
        session_key="telegram:123:coldstart",
        old_agent_id="sk-old-agent-secret",
        new_agent_id="sk-new-agent-secret",
    )

    logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["event"] == "pool_agent_reattach"
    assert payload["session_id"] == "sess-reattach-1"
    assert payload["session_key"] == "telegram:123:coldstart"
    assert payload["old_agent_id"] == "[REDACTED]"
    assert payload["new_agent_id"] == "[REDACTED]"
    assert "sk-old-agent-secret" not in records[0]
    assert "sk-new-agent-secret" not in records[0]
