"""Gateway runtime context and adapter registry."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import GatewayConfig
from cursor_agent.platforms.base import PlatformAdapter
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.store import SessionStore

if TYPE_CHECKING:
    from cursor_agent.cron.scheduler import CronScheduler
    from cursor_agent.gateway.shutdown import GatewayShutdownCoordinator

_MODULE_LOGGER = logging.getLogger(__name__)


@dataclass
class GatewayContext:
    """Runtime handles exposed while the gateway process is active."""

    gateway_config: GatewayConfig
    config: CursorAgentConfig
    store: SessionStore
    pool: SessionAgentPool
    facade: SdkFacade
    adapters: list[PlatformAdapter]
    shutdown_coordinator: GatewayShutdownCoordinator
    cron_scheduler: CronScheduler | None = None
    shutting_down: bool = False
    _adapter_by_platform: dict[str, PlatformAdapter] = field(
        default_factory=dict,
        repr=False,
    )
    _active_dispatch_tasks: set[asyncio.Task[None]] = field(
        default_factory=set,
        repr=False,
    )
    _active_agent_ids: set[str] = field(default_factory=set, repr=False)
    _logger: logging.Logger = field(default=_MODULE_LOGGER, repr=False)

    def register_adapter(self, adapter: PlatformAdapter) -> None:
        platform = adapter.platform.strip().lower()
        self._adapter_by_platform[platform] = adapter

    def adapter_for(self, platform: str) -> PlatformAdapter | None:
        return self._adapter_by_platform.get(platform.strip().lower())

    def _track_dispatch_task(self, task: asyncio.Task[None]) -> None:
        self._active_dispatch_tasks.add(task)
        task.add_done_callback(self._finalize_dispatch_task)

    def _finalize_dispatch_task(self, task: asyncio.Task[None]) -> None:
        self._active_dispatch_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        self._logger.warning(
            "gateway dispatch task failed",
            exc_info=(type(error), error, error.__traceback__),
        )

    def _track_active_agent(self, agent_id: str) -> None:
        self._active_agent_ids.add(agent_id)

    def _untrack_active_agent(self, agent_id: str) -> None:
        self._active_agent_ids.discard(agent_id)
