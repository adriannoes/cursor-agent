"""Long-running gateway runner startup and lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypeAlias

from cursor_agent.cli.startup import bootstrap_messaging_hooks, create_store
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import ConfigError
from cursor_agent.gateway.config import (
    GatewayConfig,
    enabled_platform_names,
    load_gateway_config,
    resolve_gateway_startup_config,
)
from cursor_agent.gateway.context import GatewayContext
from cursor_agent.gateway.dispatch import dispatch_inbound
from cursor_agent.gateway.shutdown import (
    DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS,
    GATEWAY_SHUTDOWN_EXIT_CODE,
    GatewayShutdownCoordinator,
    flush_logging_handlers,
    register_shutdown_signals,
)
from cursor_agent.platforms.base import InboundMessage, PlatformAdapter
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import AsyncSdkFacade, SdkFacade
from cursor_agent.sessions.store import SessionStore

_MODULE_LOGGER = logging.getLogger(__name__)

PoolFactory: TypeAlias = Callable[
    [SessionStore, SdkFacade, CursorAgentConfig],
    SessionAgentPool,
]


def _default_pool_factory(
    store: SessionStore,
    facade: SdkFacade,
    config: CursorAgentConfig,
) -> SessionAgentPool:
    return SessionAgentPool(store=store, facade=facade, config=config)


def _validate_platform_adapters(
    gateway_config: GatewayConfig,
    adapters: Sequence[PlatformAdapter],
    logger: logging.Logger,
) -> None:
    """Fail fast when YAML enables platforms without a registered adapter."""
    registered = {adapter.platform for adapter in adapters}
    missing = [
        name
        for name in enabled_platform_names(gateway_config)
        if name not in registered
    ]
    if missing:
        raise ConfigError(
            "gateway startup: platform(s) enabled in config but no adapter registered: "
            f"{missing!r}, registered adapters={sorted(registered)!r}",
        )
    if not adapters:
        logger.warning(
            "gateway startup: no platform adapters registered; "
            "inbound messages will not be received",
        )


async def _start_adapters(
    ctx: GatewayContext,
    adapters: Sequence[PlatformAdapter],
) -> None:
    for adapter in adapters:
        ctx.register_adapter(adapter)

        async def _on_inbound(message: InboundMessage) -> None:
            dispatch_task = asyncio.create_task(
                dispatch_inbound(ctx, message),
                name=f"gateway-dispatch:{message.session_key}",
            )
            ctx._track_dispatch_task(dispatch_task)

        await adapter.start(_on_inbound)


@asynccontextmanager
async def _managed_facade(
    config: CursorAgentConfig,
    facade: SdkFacade | None,
) -> AsyncIterator[SdkFacade]:
    """Yield an injected facade or construct ``AsyncSdkFacade`` for production."""
    if facade is not None:
        yield facade
        return
    async with AsyncSdkFacade(  # pragma: no cover
        api_key=os.environ.get("CURSOR_API_KEY"),
        local_setting_sources=config.runtime.local.setting_sources,
    ) as real_facade:
        yield real_facade


@asynccontextmanager
async def gateway_runtime(
    gateway_config: GatewayConfig | None = None,
    *,
    config_path: Path | None = None,
    store_path: Path | None = None,
    facade: SdkFacade | None = None,
    adapters: Sequence[PlatformAdapter] | None = None,
    pool_factory: PoolFactory | None = None,
    logger: logging.Logger | None = None,
    shutdown_timeout_seconds: float | None = None,
    shutdown_complete: asyncio.Event | None = None,
    register_signals: bool = True,
) -> AsyncIterator[GatewayContext]:
    """Bootstrap gateway startup without opening the interactive REPL."""
    active_logger = logger if logger is not None else _MODULE_LOGGER
    loaded_gateway_config = (
        gateway_config
        if gateway_config is not None
        else load_gateway_config(config_path)
    )
    cursor_config = resolve_gateway_startup_config(loaded_gateway_config)
    bootstrap_messaging_hooks(cursor_config, logger=active_logger)

    store = create_store(cursor_config, store_path=store_path)
    await store.initialize()

    platform_adapters = list(adapters or [])
    _validate_platform_adapters(loaded_gateway_config, platform_adapters, active_logger)
    build_pool = pool_factory or _default_pool_factory
    shutdown_timeout = (
        shutdown_timeout_seconds
        if shutdown_timeout_seconds is not None
        else DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS
    )
    coordinator = GatewayShutdownCoordinator(
        shutdown_timeout_seconds=shutdown_timeout,
        shutdown_complete=shutdown_complete,
    )

    async with _managed_facade(cursor_config, facade) as active_facade:
        pool = build_pool(store, active_facade, cursor_config)
        ctx = GatewayContext(
            gateway_config=loaded_gateway_config,
            config=cursor_config,
            store=store,
            pool=pool,
            facade=active_facade,
            adapters=platform_adapters,
            shutdown_coordinator=coordinator,
            _logger=active_logger,
        )
        try:
            await _start_adapters(ctx, platform_adapters)
            if register_signals:
                register_shutdown_signals(coordinator, ctx)
            yield ctx
        finally:
            await coordinator.shutdown(ctx)


async def run_gateway(config_path: Path | None = None) -> int:
    """Start the gateway runtime and block until graceful shutdown."""
    shutdown_complete = asyncio.Event()
    async with gateway_runtime(
        config_path=config_path,
        shutdown_complete=shutdown_complete,
    ):
        await shutdown_complete.wait()
    return GATEWAY_SHUTDOWN_EXIT_CODE


__all__ = [
    "DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS",
    "GATEWAY_SHUTDOWN_EXIT_CODE",
    "GatewayContext",
    "GatewayShutdownCoordinator",
    "flush_logging_handlers",
    "gateway_runtime",
    "register_shutdown_signals",
    "resolve_gateway_startup_config",
    "run_gateway",
]
