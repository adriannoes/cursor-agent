"""Platform adapter contracts for gateway integrations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol

GATEWAY_BUSY_MESSAGE: Final[str] = (
    "Estou processando sua mensagem anterior. Aguarde ou envie /stop."
)


@dataclass(frozen=True, slots=True)
class PlatformMessage:
    """Normalized platform message payload (inbound or outbound)."""

    platform: str
    sender_id: str
    session_key: str
    text: str


InboundMessage = PlatformMessage
OutboundMessage = PlatformMessage


def outbound_reply(inbound: PlatformMessage, text: str) -> OutboundMessage:
    """Build an outbound reply from an inbound message and response text."""
    return OutboundMessage(
        platform=inbound.platform,
        sender_id=inbound.sender_id,
        session_key=inbound.session_key,
        text=text,
    )


GatewayInboundCallback = Callable[[InboundMessage], Awaitable[None]]


class PlatformAdapter(Protocol):
    """Async lifecycle contract for messaging platform integrations."""

    @property
    def platform(self) -> str:
        """Stable platform identifier (for example ``telegram``)."""
        ...

    async def start(self, on_inbound: GatewayInboundCallback) -> None:
        """Begin receiving inbound messages and invoke ``on_inbound`` for each."""
        ...

    async def stop(self) -> None:
        """Stop receiving inbound messages and release platform resources."""
        ...

    async def send_message(self, outbound: OutboundMessage) -> None:
        """Deliver an outbound reply to the platform user identified in ``outbound``."""
        ...
