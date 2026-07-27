"""Email platform adapter using IMAP poll + SMTP reply."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.facade_logging import emit_gateway_auth_blocked
from cursor_agent.gateway.auth import is_allowed_sender
from cursor_agent.gateway.config import EmailPlatformConfig, GatewayConfig
from cursor_agent.platforms.base import (
    GatewayInboundCallback,
    InboundMessage,
    OutboundMessage,
)
from cursor_agent.platforms.email_chunking import (
    email_session_key,
    normalize_email_address,
)
from cursor_agent.platforms.email_commands import (
    EMAIL_HELP_TEXT,
    EmailCommandRouter,
    parse_email_command,
    workspace_path,
)
from cursor_agent.platforms.email_delivery import EmailDelivery
from cursor_agent.platforms.email_imap import (
    ImapClientFactory,
    ParsedInboundEmail,
    default_imap_client_factory,
    fetch_message_rfc822,
    fetch_seen_uids,
    fetch_unseen_uids,
    mark_seen,
    open_inbox,
    parse_rfc822_bytes,
    with_context_close,
)
from cursor_agent.platforms.email_smtp import (
    EmailThreadContext,
    SmtpClientFactory,
    default_smtp_client_factory,
)
from cursor_agent.product_copy import EMAIL_NO_SESSION_HINT
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.store import SessionStore

Sleeper = Callable[[float], Awaitable[None]]

_OWN_OUTBOUND_MESSAGE_ID_MARKER = "cursor-agent-"


def _is_own_outbound_message_id(message_id: str) -> bool:
    """Return True when ``message_id`` looks like one we generated for SMTP replies."""
    return _OWN_OUTBOUND_MESSAGE_ID_MARKER in message_id.lower()


class EmailAdapter:
    """Email ``PlatformAdapter`` using IMAP polling and SMTP replies.

    Example:
        >>> adapter = EmailAdapter(
        ...     platform_config=EmailPlatformConfig(
        ...         enabled=True,
        ...         address="bot@agentmail.to",
        ...         password="am_...",
        ...         imap_host="imap.agentmail.to",
        ...         smtp_host="smtp.agentmail.to",
        ...     ),
        ...     gateway_config=gateway_config,
        ...     config=cursor_config,
        ...     store=store,
        ...     facade=facade,
        ...     logger=logger,
        ... )
        >>> adapter.platform
        'email'
    """

    def __init__(
        self,
        *,
        platform_config: EmailPlatformConfig,
        gateway_config: GatewayConfig,
        config: CursorAgentConfig,
        store: SessionStore,
        facade: SdkFacade,
        logger: logging.Logger,
        imap_client_factory: ImapClientFactory | None = None,
        smtp_client_factory: SmtpClientFactory | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self._platform_config = platform_config
        self._gateway_config = gateway_config
        self._config = config
        self._store = store
        self._facade = facade
        self._logger = logger
        self._imap_client_factory = imap_client_factory or default_imap_client_factory
        self._smtp_client_factory = smtp_client_factory or default_smtp_client_factory
        self._sleeper = sleeper or asyncio.sleep
        self._poll_task: asyncio.Task[None] | None = None
        self._on_inbound: GatewayInboundCallback | None = None
        self._stopped = False
        self._seen_uids: set[str] = set()
        self._thread_context: dict[str, EmailThreadContext] = {}
        self._delivery = EmailDelivery(
            platform_config=platform_config,
            logger=logger,
            smtp_client_factory=self._smtp_client_factory,
            thread_context_getter=self._thread_context.get,
        )
        self._commands = EmailCommandRouter(
            gateway_config=gateway_config,
            config=config,
            store=store,
            facade=facade,
            logger=logger,
            send_plain_reply=self._delivery.send_plain_reply,
        )

    @property
    def platform(self) -> str:
        """Stable platform identifier for gateway adapter validation."""
        return "email"

    def thread_context_for(self, sender: str) -> EmailThreadContext | None:
        """Return cached thread headers for ``sender`` (test helper)."""
        return self._thread_context.get(normalize_email_address(sender))

    async def start(self, on_inbound: GatewayInboundCallback) -> None:
        """Seed seen UIDs and begin the IMAP poll loop in a background task."""
        self._stopped = False
        self._on_inbound = on_inbound
        await asyncio.to_thread(self._seed_seen_uids)
        self._poll_task = asyncio.create_task(
            self._run_poll_loop(),
            name="email-imap-poll",
        )
        self._poll_task.add_done_callback(self._handle_poll_task_done)
        self._logger.info(
            "email_adapter_started platform=email poll_task=%s poll_interval=%s",
            self._poll_task.get_name(),
            self._platform_config.poll_interval_seconds,
        )

    def _handle_poll_task_done(self, task: asyncio.Task[None]) -> None:
        """Surface unexpected poll-loop termination so the operator is not blind."""
        if task.cancelled() or self._stopped:
            return
        exc = task.exception()
        if exc is None:
            return
        self._logger.critical(
            "email_poll_terminated platform=email exception_class=%s; "
            "gateway has no inbound email path until restarted",
            exc.__class__.__name__,
        )

    async def stop(self) -> None:
        """Stop the IMAP poll loop and clear inbound callback state."""
        self._stopped = True
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        self._on_inbound = None
        self._logger.info("email_adapter_stopped platform=email")

    async def send_message(self, outbound: OutboundMessage) -> None:
        """Deliver a plain-text SMTP reply to the sender in ``session_key``."""
        await self._delivery.send_message(outbound)

    def _seed_seen_uids(self) -> None:
        """Seed local seen-set from IMAP SEEN only.

        Pending UNSEEN messages (including mail that arrived while the gateway
        was down) remain eligible for the first poll.
        """
        client = open_inbox(
            host=self._platform_config.imap_host,
            port=self._platform_config.imap_port,
            address=self._platform_config.address,
            password=self._platform_config.password,
            client_factory=self._imap_client_factory,
        )
        try:
            self._seen_uids = set(fetch_seen_uids(client))
            self._logger.info(
                "email_seen_uids_seeded platform=email count=%s",
                len(self._seen_uids),
            )
        finally:
            with_context_close(client)

    async def _run_poll_loop(self) -> None:
        try:
            while not self._stopped:
                try:
                    await self._poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._logger.exception(
                        "email_poll_failed platform=email exception_class=%s",
                        exc.__class__.__name__,
                    )
                await self._sleeper(self._platform_config.poll_interval_seconds)
        except asyncio.CancelledError:
            raise

    async def _poll_once(self) -> None:
        messages = await asyncio.to_thread(self._fetch_new_messages)
        for parsed in messages:
            if self._stopped:
                return
            await self._handle_parsed_inbound(parsed)

    def _fetch_new_messages(self) -> list[ParsedInboundEmail]:
        client = open_inbox(
            host=self._platform_config.imap_host,
            port=self._platform_config.imap_port,
            address=self._platform_config.address,
            password=self._platform_config.password,
            client_factory=self._imap_client_factory,
        )
        parsed_messages: list[ParsedInboundEmail] = []
        try:
            unseen = fetch_unseen_uids(client)
            for uid in unseen:
                if uid in self._seen_uids:
                    continue
                raw = fetch_message_rfc822(client, uid)
                parsed = parse_rfc822_bytes(uid, raw)
                self._seen_uids.add(uid)
                try:
                    mark_seen(client, uid)
                except Exception as exc:
                    self._logger.warning(
                        "email_mark_seen_failed platform=email uid=%s "
                        "exception_class=%s",
                        uid,
                        exc.__class__.__name__,
                    )
                if parsed is None:
                    continue
                own = normalize_email_address(self._platform_config.address)
                # Skip SMTP echoes of our own outbound replies (Message-ID prefix),
                # but allow other mail From the bot address (e.g. AgentMail API sends).
                if parsed.sender == own and _is_own_outbound_message_id(
                    parsed.message_id
                ):
                    continue
                parsed_messages.append(parsed)
        finally:
            with_context_close(client)
        return parsed_messages

    async def _handle_parsed_inbound(self, parsed: ParsedInboundEmail) -> None:
        if self._on_inbound is None:
            return
        workspace = workspace_path(self._gateway_config, self._config)
        session_key = email_session_key(parsed.sender, workspace)
        inbound = InboundMessage(
            platform="email",
            sender_id=parsed.sender,
            session_key=session_key,
            text=parsed.prompt_text,
        )
        self._logger.info(
            "email_inbound_received platform=email sender=%s session_key=%s",
            parsed.sender,
            session_key,
        )
        if not is_allowed_sender("email", parsed.sender, self._gateway_config):
            emit_gateway_auth_blocked(
                self._logger,
                platform="email",
                sender_id=parsed.sender,
                session_key=session_key,
            )
            return
        if parsed.message_id:
            self._thread_context[parsed.sender] = EmailThreadContext(
                subject=parsed.subject,
                message_id=parsed.message_id,
            )
        command = parse_email_command(subject=parsed.subject, body=parsed.body_text)
        if command is not None:
            await self._commands.dispatch(
                command,
                sender=parsed.sender,
                session_key=session_key,
            )
            return
        if await self._store.resolve(session_key) is None:
            await self._delivery.send_plain_reply(
                parsed.sender,
                EMAIL_NO_SESSION_HINT,
            )
            return
        await self._on_inbound(inbound)


__all__ = [
    "EMAIL_HELP_TEXT",
    "EmailAdapter",
]
