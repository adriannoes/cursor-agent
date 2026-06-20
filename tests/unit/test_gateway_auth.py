"""Unit tests for gateway allowlist authorization."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from cursor_agent.gateway.auth import (
    blocked_sender_response_text,
    is_allowed_sender,
    normalize_sender_id,
)
from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.base import InboundMessage
from cursor_agent.sdk_facade import FakeSdkFacade

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    NoopCronScheduler,
    SendSpyPool,
    _wait_for_condition,
    gateway_config,
    seed_session,
)


def test_is_allowed_sender_allows_listed_telegram_user() -> None:
    """Listed Telegram user IDs pass the allowlist gate."""
    config = gateway_config(allowed_users=[123456789, 987654321])
    assert is_allowed_sender("telegram", "123456789", config) is True
    assert is_allowed_sender("telegram", 987654321, config) is True


def test_is_allowed_sender_blocks_unlisted_telegram_user() -> None:
    """Unlisted Telegram user IDs are rejected."""
    config = gateway_config()
    assert is_allowed_sender("telegram", "000000001", config) is False


def test_is_allowed_sender_rejects_unknown_platform() -> None:
    """Unknown platforms are rejected by default."""
    config = gateway_config()
    assert is_allowed_sender("discord", "123456789", config) is False
    assert is_allowed_sender("slack", "123456789", config) is False


def test_is_allowed_sender_blocks_when_allowlist_empty() -> None:
    """Empty allowlists block every sender."""
    config = gateway_config(allowed_users=[])
    assert is_allowed_sender("telegram", "123456789", config) is False


def test_normalize_sender_id_matches_int_and_string_forms() -> None:
    """User IDs normalize to the same canonical string for int and str inputs."""
    assert normalize_sender_id(123456789) == "123456789"
    assert normalize_sender_id("123456789") == "123456789"
    assert normalize_sender_id(" 123456789 ") == "123456789"


def test_is_allowed_sender_matches_normalized_string_user_id() -> None:
    """Allowlist compares normalized string forms of configured int IDs."""
    config = gateway_config(allowed_users=[42])
    assert is_allowed_sender("telegram", "42", config) is True
    assert is_allowed_sender("telegram", 42, config) is True


def test_is_allowed_sender_rejects_empty_user_id() -> None:
    """Empty sender IDs must not pass via loose truthiness."""
    config = gateway_config()
    assert is_allowed_sender("telegram", "", config) is False
    assert is_allowed_sender("telegram", "   ", config) is False


def test_is_allowed_sender_normalizes_platform_name() -> None:
    """Platform names are matched case-insensitively."""
    config = gateway_config()
    assert is_allowed_sender("Telegram", "123456789", config) is True


def test_blocked_sender_receives_no_outbound_response() -> None:
    """MVP: blocked users get no outbound message (silent ignore)."""
    assert blocked_sender_response_text() is None


def test_gateway_auth_blocked_log_emits_ndjson() -> None:
    """Blocked auth attempts emit structured NDJSON with safe metadata only."""
    from cursor_agent.facade_logging import emit_gateway_auth_blocked

    logger = logging.getLogger("test.gateway.auth.blocked")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_gateway_auth_blocked(
        logger,
        platform="telegram",
        sender_id="999888777",
        session_key="telegram:999888777:abc12345",
    )

    logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["v"] == 1
    assert payload["event"] == "gateway_auth_blocked"
    assert payload["platform"] == "telegram"
    assert payload["sender_id"] == "999888777"
    assert payload["session_key"] == "telegram:999888777:abc12345"
    assert "ts" in payload


def test_gateway_auth_blocked_log_omits_session_key_when_unavailable() -> None:
    """Session key is optional when dispatch rejects before session resolution."""
    from cursor_agent.facade_logging import emit_gateway_auth_blocked

    logger = logging.getLogger("test.gateway.auth.blocked.no_session")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_gateway_auth_blocked(
        logger,
        platform="telegram",
        sender_id="111222333",
    )

    logger.removeHandler(handler)
    payload = json.loads(records[0])
    assert payload["session_key"] is None


def test_gateway_auth_blocked_log_redacts_token_like_sender_id() -> None:
    """Blocked-auth logs redact token-like substrings in sender identifiers."""
    from cursor_agent.facade_logging import emit_gateway_auth_blocked

    logger = logging.getLogger("test.gateway.auth.blocked.redact")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_gateway_auth_blocked(
        logger,
        platform="telegram",
        sender_id="bot123456:ABCdef-token-sk-live-secret",
        session_key="telegram:chat:abc",
    )

    logger.removeHandler(handler)
    raw_log = records[0]
    payload = json.loads(raw_log)
    assert "[REDACTED]" in payload["sender_id"]
    assert "sk-live-secret" not in raw_log
    assert "bot123456:ABCdef" not in raw_log


def test_gateway_auth_blocked_log_excludes_inbound_message_text() -> None:
    """Blocked-auth logs must not include inbound message bodies."""
    from cursor_agent.facade_logging import emit_gateway_auth_blocked

    logger = logging.getLogger("test.gateway.auth.blocked.no_text")
    records: list[str] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _ListHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    emit_gateway_auth_blocked(
        logger,
        platform="telegram",
        sender_id="444555666",
        session_key="telegram:444555666:hash",
    )

    logger.removeHandler(handler)
    raw_log = records[0]
    payload = json.loads(raw_log)
    secret_prompt = "super-secret-user-prompt-body"
    assert secret_prompt not in raw_log
    assert "text" not in payload
    assert "message" not in payload
    assert "prompt" not in payload


@pytest.fixture(autouse=True)
def _isolate_gateway_cron_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep gateway auth dispatch tests hermetic after cron startup wiring."""
    monkeypatch.setattr("cursor_agent.gateway.runner.CronScheduler", NoopCronScheduler)


async def test_dispatch_blocked_inbound_skips_pool_and_emits_auth_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Blocked inbound does not call the pool and emits gateway_auth_blocked."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade()
    session_key = "telegram:999888777:deadbeef"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        with caplog.at_level(logging.INFO, logger="cursor_agent.gateway.runner"):
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="999888777",
                    session_key=session_key,
                    text="unauthorized",
                )
            )
            await _wait_for_condition(
                lambda: any(
                    record.message.startswith("{")
                    and "gateway_auth_blocked" in record.message
                    for record in caplog.records
                ),
                description="blocked auth log",
            )

        assert ctx.pool.send_calls == []
        assert adapter.outbound_messages == []

    payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
    ]
    blocked = [p for p in payloads if p.get("event") == "gateway_auth_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["platform"] == "telegram"
    assert blocked[0]["sender_id"] == "999888777"
    assert blocked[0]["session_key"] == session_key
