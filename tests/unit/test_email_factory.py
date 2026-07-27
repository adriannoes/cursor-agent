"""Unit tests for email platform adapter factory construction."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from cursor_agent.errors import ConfigError
from cursor_agent.gateway.config import (
    EmailPlatformConfig,
    GatewayConfig,
    PlatformsConfig,
    TelegramPlatformConfig,
    resolve_gateway_startup_config,
)
from cursor_agent.platforms.email import EmailAdapter
from cursor_agent.platforms.factory import build_platform_adapters
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.email_adapter_fakes import email_gateway_config, email_platform_config


def _runtime_handles(
    tmp_path: Path,
    gateway_cfg: GatewayConfig,
) -> dict[str, object]:
    cursor_cfg = resolve_gateway_startup_config(gateway_cfg)
    facade = FakeSdkFacade()
    store = SessionStore(tmp_path / "sessions.db")
    pool = SessionAgentPool(store=store, facade=facade, config=cursor_cfg)
    logger = logging.getLogger("test.email.factory")
    return {
        "gateway_config": gateway_cfg,
        "config": cursor_cfg,
        "store": store,
        "facade": facade,
        "pool": pool,
        "logger": logger,
    }


def test_build_platform_adapters_enabled_true_constructs_email_adapter(
    tmp_path: Path,
) -> None:
    handles = _runtime_handles(tmp_path, email_gateway_config())

    adapters = build_platform_adapters(**handles)  # type: ignore[arg-type]

    assert len(adapters) == 1
    assert isinstance(adapters[0], EmailAdapter)
    assert adapters[0].platform == "email"


def test_build_platform_adapters_email_disabled_constructs_none(
    tmp_path: Path,
) -> None:
    disabled = GatewayConfig(
        workspace="/tmp/gateway-workspace",
        tool_profile="messaging",
        platforms=PlatformsConfig(
            telegram=TelegramPlatformConfig(enabled=False),
            email=EmailPlatformConfig(enabled=False),
        ),
    )
    handles = _runtime_handles(tmp_path, disabled)

    assert build_platform_adapters(**handles) == []  # type: ignore[arg-type]


def test_build_platform_adapters_missing_email_password_raises(
    tmp_path: Path,
) -> None:
    cfg = GatewayConfig(
        workspace="/tmp/gateway-workspace",
        tool_profile="messaging",
        platforms=PlatformsConfig(
            email=email_platform_config(password=""),
        ),
    )
    handles = _runtime_handles(tmp_path, cfg)

    with pytest.raises(ConfigError, match="password"):
        build_platform_adapters(**handles)  # type: ignore[arg-type]


def test_build_platform_adapters_empty_email_allowlist_warns(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = email_gateway_config(allowed_users=[])
    handles = _runtime_handles(tmp_path, cfg)
    caplog.set_level(logging.WARNING, logger="test.email.factory")

    adapters = build_platform_adapters(**handles)  # type: ignore[arg-type]

    assert len(adapters) == 1
    assert "allowed_users is empty" in caplog.text
