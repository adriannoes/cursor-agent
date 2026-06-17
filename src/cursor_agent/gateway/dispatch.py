"""Inbound message dispatch through auth, pool, and outbound replies."""

from __future__ import annotations

from cursor_agent.errors import AgentBusyError
from cursor_agent.facade_logging import emit_gateway_auth_blocked
from cursor_agent.gateway.auth import blocked_sender_response_text, is_allowed_sender
from cursor_agent.gateway.context import GatewayContext
from cursor_agent.platforms.base import (
    GATEWAY_BUSY_MESSAGE,
    InboundMessage,
    outbound_reply,
)


async def dispatch_inbound(ctx: GatewayContext, message: InboundMessage) -> None:
    """Route an inbound platform message through auth, pool, and outbound reply."""
    if ctx.shutting_down:
        return

    adapter = ctx.adapter_for(message.platform)
    if adapter is None:
        ctx._logger.warning(
            "gateway dispatch: no adapter registered for platform=%s",
            message.platform,
        )
        return

    if not is_allowed_sender(
        message.platform,
        message.sender_id,
        ctx.gateway_config,
    ):
        emit_gateway_auth_blocked(
            ctx._logger,
            platform=message.platform,
            sender_id=message.sender_id,
            session_key=message.session_key,
        )
        blocked_text = blocked_sender_response_text()
        if blocked_text is not None:
            await adapter.send_message(outbound_reply(message, blocked_text))
        return

    row = await ctx.store.resolve(message.session_key, session_id=None)
    if row is None:
        return

    ctx._track_active_agent(row.agent_id)
    try:
        try:
            result = await ctx.pool.send(
                message.session_key,
                message.text,
                session_row=row,
                blocking=False,
            )
        except AgentBusyError:
            await adapter.send_message(outbound_reply(message, GATEWAY_BUSY_MESSAGE))
            return

        if result.text is None:
            return

        await adapter.send_message(outbound_reply(message, result.text))
    finally:
        ctx._untrack_active_agent(row.agent_id)
