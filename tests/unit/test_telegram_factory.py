"""Unit tests for platform adapter factory production construction."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cursor_agent.errors import ConfigError
from cursor_agent.gateway.config import (
    GatewayConfig,
    PlatformsConfig,
    TelegramPlatformConfig,
    resolve_gateway_startup_config,
)
from cursor_agent.platforms.factory import build_platform_adapters
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import gateway_config


def _runtime_handles(
    tmp_path: Path,
    gateway_cfg: GatewayConfig,
) -> dict[str, object]:
    """Build factory runtime handles without starting adapters or polling."""
    cursor_cfg = resolve_gateway_startup_config(gateway_cfg)
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    pool = SessionAgentPool(store=store, facade=facade, config=cursor_cfg)
    logger = logging.getLogger("test.telegram.factory")
    return {
        "gateway_config": gateway_cfg,
        "config": cursor_cfg,
        "store": store,
        "facade": facade,
        "pool": pool,
        "logger": logger,
    }


def test_build_platform_adapters_enabled_true_constructs_telegram_adapter(
    tmp_path: Path,
) -> None:
    """Enabled Telegram with a valid token registers one TelegramAdapter."""
    handles = _runtime_handles(tmp_path, gateway_config())

    adapters = build_platform_adapters(**handles)  # type: ignore[arg-type]

    assert len(adapters) == 1
    assert isinstance(adapters[0], TelegramAdapter)
    assert adapters[0].platform == "telegram"


def test_build_platform_adapters_enabled_false_constructs_none(
    tmp_path: Path,
) -> None:
    """Disabled Telegram must not register any adapters."""
    disabled_config = GatewayConfig(
        workspace="/tmp/gateway-workspace",
        tool_profile="messaging",
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(
                enabled=False,
                bot_token="",
                allowed_users=[123456789],
            ),
        ),
    )
    handles = _runtime_handles(tmp_path, disabled_config)

    adapters = build_platform_adapters(**handles)  # type: ignore[arg-type]

    assert adapters == []


def test_build_platform_adapters_empty_token_raises_config_error(
    tmp_path: Path,
) -> None:
    """Enabled Telegram with empty bot_token must fail with actionable ConfigError."""
    secret_token = "super-secret-bot-token-value"
    empty_token_config = GatewayConfig(
        workspace="/tmp/gateway-workspace",
        tool_profile="messaging",
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(
                enabled=True,
                bot_token="",
                allowed_users=[123456789],
            ),
        ),
    )
    handles = _runtime_handles(tmp_path, empty_token_config)

    with pytest.raises(ConfigError, match="bot_token") as exc_info:
        build_platform_adapters(**handles)  # type: ignore[arg-type]

    message = str(exc_info.value)
    assert secret_token not in message
    assert "telegram" in message.lower()
    assert "empty" in message.lower() or "missing" in message.lower()


def test_build_platform_adapters_whitespace_token_raises_config_error(
    tmp_path: Path,
) -> None:
    """Whitespace-only bot_token is treated as missing."""
    whitespace_config = GatewayConfig(
        workspace="/tmp/gateway-workspace",
        tool_profile="messaging",
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(
                enabled=True,
                bot_token="   ",
                allowed_users=[123456789],
            ),
        ),
    )
    handles = _runtime_handles(tmp_path, whitespace_config)

    with pytest.raises(ConfigError, match="bot_token"):
        build_platform_adapters(**handles)  # type: ignore[arg-type]


def test_build_platform_adapters_empty_allowlist_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Enabled Telegram with an empty allowlist still builds but warns the operator."""
    empty_allowlist_config = GatewayConfig(
        workspace="/tmp/gateway-workspace",
        tool_profile="messaging",
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(
                enabled=True,
                bot_token="bot123456:placeholder-token",
                allowed_users=[],
            ),
        ),
    )
    handles = _runtime_handles(tmp_path, empty_allowlist_config)
    caplog.set_level(logging.WARNING, logger="test.telegram.factory")

    adapters = build_platform_adapters(**handles)  # type: ignore[arg-type]

    assert len(adapters) == 1
    assert "allowed_users is empty" in caplog.text


def test_build_platform_adapters_nonempty_allowlist_does_not_warn(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A populated allowlist must not emit the empty-allowlist warning."""
    handles = _runtime_handles(tmp_path, gateway_config())
    caplog.set_level(logging.WARNING, logger="test.telegram.factory")

    build_platform_adapters(**handles)  # type: ignore[arg-type]

    assert "allowed_users is empty" not in caplog.text
