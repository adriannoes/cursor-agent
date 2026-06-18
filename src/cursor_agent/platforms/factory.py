"""Platform adapter factory for gateway production startup."""

from __future__ import annotations

import logging

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import ConfigError
from cursor_agent.gateway.config import GatewayConfig, enabled_platform_names
from cursor_agent.platforms.base import PlatformAdapter
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.store import SessionStore


def _validate_telegram_bot_token(gateway_config: GatewayConfig) -> None:
    """Require a non-empty Telegram bot token when the platform is enabled."""
    token = gateway_config.platforms.telegram.bot_token
    if token.strip():
        return
    raise ConfigError(
        "gateway startup: platforms.telegram.enabled is true but bot_token is "
        "empty or missing; set bot_token in gateway.yaml or expand "
        "${TELEGRAM_BOT_TOKEN} from the environment",
    )


def _warn_if_telegram_allowlist_empty(
    gateway_config: GatewayConfig,
    logger: logging.Logger,
) -> None:
    """Warn when Telegram is enabled but no sender is allowlisted.

    An empty ``allowed_users`` blocks everyone by design, so the bot looks
    online yet ignores every message; a startup warning saves debugging time.
    """
    if gateway_config.platforms.telegram.allowed_users:
        return
    logger.warning(
        "gateway startup: platforms.telegram.enabled is true but allowed_users is "
        "empty; all senders will be blocked and the bot will appear online while "
        "ignoring every message",
    )


def build_platform_adapters(
    *,
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
    store: SessionStore,
    facade: SdkFacade,
    pool: SessionAgentPool,
    logger: logging.Logger,
) -> list[PlatformAdapter]:
    """Build platform adapters from validated gateway config and runtime handles.

    Construction is side-effect free: no polling starts and no Telegram API calls
    occur until ``PlatformAdapter.start()`` runs in the gateway runner.

    Example:
        >>> adapters = build_platform_adapters(
        ...     gateway_config=gateway_config,
        ...     config=cursor_config,
        ...     store=store,
        ...     facade=facade,
        ...     pool=pool,
        ...     logger=logger,
        ... )
    """
    adapters: list[PlatformAdapter] = []
    for platform_name in enabled_platform_names(gateway_config):
        if platform_name == "telegram":
            _validate_telegram_bot_token(gateway_config)
            _warn_if_telegram_allowlist_empty(gateway_config, logger)
            adapters.append(
                TelegramAdapter(
                    platform_config=gateway_config.platforms.telegram,
                    gateway_config=gateway_config,
                    config=config,
                    store=store,
                    facade=facade,
                    logger=logger,
                ),
            )
    return adapters


__all__ = ["build_platform_adapters"]
