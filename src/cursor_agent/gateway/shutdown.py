"""Graceful gateway shutdown coordination (ADR-021)."""

from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Sequence
from dataclasses import dataclass, field

from cursor_agent.gateway.context import GatewayContext
from cursor_agent.platforms.base import PlatformAdapter

_MODULE_LOGGER = logging.getLogger(__name__)

DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS = 30.0
GATEWAY_SHUTDOWN_EXIT_CODE = 0


def flush_logging_handlers() -> None:
    """Flush all handlers attached to the root logger."""
    root = logging.getLogger()
    for handler in root.handlers:
        handler.flush()


async def stop_adapters(adapters: Sequence[PlatformAdapter]) -> None:
    for adapter in adapters:
        await adapter.stop()


@dataclass
class GatewayShutdownCoordinator:
    """Coordinate graceful gateway shutdown."""

    shutdown_timeout_seconds: float = DEFAULT_GATEWAY_SHUTDOWN_TIMEOUT_SECONDS
    shutdown_complete: asyncio.Event | None = None
    _shutdown_complete: bool = field(default=False, init=False, repr=False)
    _shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _logger: logging.Logger = field(default=_MODULE_LOGGER, repr=False)

    async def shutdown(self, ctx: GatewayContext) -> int:
        async with self._shutdown_lock:
            if self._shutdown_complete:
                return GATEWAY_SHUTDOWN_EXIT_CODE

            ctx.shutting_down = True
            await stop_adapters(ctx.adapters)

            for agent_id in list(ctx._active_agent_ids):
                try:
                    await ctx.facade.cancel(agent_id)
                except Exception:
                    self._logger.warning(
                        "gateway shutdown: facade cancel failed for agent_id=%s",
                        agent_id,
                        exc_info=True,
                    )

            await self._await_or_cancel_dispatch_tasks(ctx)

            try:
                await ctx.facade.close()
            except Exception:
                self._logger.debug(
                    "gateway shutdown: facade close failed", exc_info=True
                )

            flush_logging_handlers()
            self._shutdown_complete = True
            if self.shutdown_complete is not None:
                self.shutdown_complete.set()
            return GATEWAY_SHUTDOWN_EXIT_CODE

    async def _await_or_cancel_dispatch_tasks(self, ctx: GatewayContext) -> None:
        pending = list(ctx._active_dispatch_tasks)
        if not pending:
            return

        _done, still_pending = await asyncio.wait(
            pending,
            timeout=self.shutdown_timeout_seconds,
            return_when=asyncio.ALL_COMPLETED,
        )
        if not still_pending:
            return

        self._logger.warning(
            "gateway shutdown: %d dispatch task(s) did not finish within %.3fs",
            len(still_pending),
            self.shutdown_timeout_seconds,
        )
        for task in still_pending:
            task.cancel()
        await asyncio.gather(*still_pending, return_exceptions=True)


def register_shutdown_signals(
    coordinator: GatewayShutdownCoordinator,
    ctx: GatewayContext,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Register SIGINT/SIGTERM handlers that schedule graceful shutdown."""
    event_loop = loop or asyncio.get_running_loop()

    def _schedule_shutdown() -> None:
        asyncio.create_task(coordinator.shutdown(ctx))

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            event_loop.add_signal_handler(sig, _schedule_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            _MODULE_LOGGER.debug(
                "gateway shutdown: signal handler not registered for %s",
                sig,
            )
