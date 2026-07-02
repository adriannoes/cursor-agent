"""Best-effort SDK agent cleanup helpers."""

from __future__ import annotations

import logging

from cursor_agent.sdk_facade import SdkFacade

_MODULE_LOGGER = logging.getLogger(__name__)


async def cancel_agent_quietly(facade: SdkFacade, agent_id: str) -> None:
    """Best-effort cancel of an SDK agent; never raises to the caller."""
    try:
        await facade.cancel(agent_id)
    except Exception:
        _MODULE_LOGGER.warning(
            "agent cleanup: failed to cancel orphaned agent_id=%s",
            agent_id,
            exc_info=True,
        )
