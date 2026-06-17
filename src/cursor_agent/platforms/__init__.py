"""Platform adapter contracts for gateway integrations."""

from cursor_agent.platforms.base import (
    GATEWAY_BUSY_MESSAGE,
    GatewayInboundCallback,
    InboundMessage,
    OutboundMessage,
    PlatformAdapter,
    PlatformMessage,
    outbound_reply,
)

__all__ = [
    "GATEWAY_BUSY_MESSAGE",
    "GatewayInboundCallback",
    "InboundMessage",
    "OutboundMessage",
    "PlatformAdapter",
    "PlatformMessage",
    "outbound_reply",
]
