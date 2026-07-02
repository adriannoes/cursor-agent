"""Telegram slash-command parsing and session command handling (PRD-012)."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

from cursor_agent.agent_cleanup import cancel_agent_quietly
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import GatewayConfig
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

TELEGRAM_NEW_CONFIRMATION: Final[str] = "Started a new conversation."
TELEGRAM_STOP_SUCCESS: Final[str] = "Run cancelled."
TELEGRAM_STOP_NO_SESSION: Final[str] = (
    "No active session. Send /new to start a conversation."
)
TELEGRAM_HELP_TEXT: Final[str] = """\
Telegram commands:

/new — Start or reset your conversation
/stop — Cancel the current run
/help — Show this message
"""

SUPPORTED_TELEGRAM_COMMANDS: Final[frozenset[str]] = frozenset(
    {"new", "stop", "help", "start"},
)

SendPlainReply = Callable[[int, str], Awaitable[None]]


def parse_telegram_command(text: str) -> str | None:
    """Return a supported Telegram slash command name, or ``None`` for free text."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    command_token = stripped.split(maxsplit=1)[0]
    command_name = command_token.split("@", maxsplit=1)[0].lstrip("/").lower()
    if command_name in SUPPORTED_TELEGRAM_COMMANDS:
        return command_name
    return None


def workspace_path(
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
) -> str:
    """Return the canonical workspace path used for Telegram session keys."""
    return config.runtime.local.cwd or gateway_config.workspace


def resolved_workspace(
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
) -> str:
    """Return the absolute workspace path used for SDK agent creation."""
    return str(Path(workspace_path(gateway_config, config)).resolve())


class TelegramCommandRouter:
    """Dispatch supported Telegram slash commands to session actions.

    Example:
        >>> router = TelegramCommandRouter(
        ...     gateway_config=gateway_config,
        ...     config=cursor_config,
        ...     store=store,
        ...     facade=facade,
        ...     logger=logger,
        ...     send_plain_reply=adapter.send_plain_reply,
        ... )
        >>> await router.dispatch("new", chat_id=123, session_key="telegram:123:abc12345")
    """

    def __init__(
        self,
        *,
        gateway_config: GatewayConfig,
        config: CursorAgentConfig,
        store: SessionStore,
        facade: SdkFacade,
        logger: logging.Logger,
        send_plain_reply: SendPlainReply,
    ) -> None:
        self._gateway_config = gateway_config
        self._config = config
        self._store = store
        self._facade = facade
        self._logger = logger
        self._send_plain_reply = send_plain_reply

    async def dispatch(
        self,
        command: str,
        *,
        chat_id: int,
        session_key: str,
    ) -> None:
        """Route a parsed command name to its session action handler."""
        if command == "new":
            await self._handle_new(chat_id=chat_id, session_key=session_key)
            return
        if command == "stop":
            await self._handle_stop(chat_id=chat_id, session_key=session_key)
            return
        if command == "help":
            await self._send_plain_reply(chat_id, TELEGRAM_HELP_TEXT.strip())
            return
        if command == "start":
            await self._send_plain_reply(chat_id, TELEGRAM_NO_SESSION_HINT)
            return
        msg = (
            "unsupported telegram command dispatch: "
            f"received {command!r}, expected one of {sorted(SUPPORTED_TELEGRAM_COMMANDS)!r}"
        )
        raise ValueError(msg)

    async def _handle_new(self, *, chat_id: int, session_key: str) -> None:
        previous = await self._store.resolve(session_key)
        workspace = resolved_workspace(self._gateway_config, self._config)
        agent_id = await self._facade.create_agent(
            workspace=workspace,
            model=self._config.model,
            tool_profile=self._config.tool_profile,
            runtime_mode=self._config.runtime.mode,
        )
        try:
            await self._store.create(
                SessionCreateParams(
                    session_key=session_key,
                    agent_id=agent_id,
                    workspace=workspace,
                    runtime=self._config.runtime.mode,
                    tool_profile=self._config.tool_profile,
                    title=None,
                ),
            )
        except BaseException:
            await cancel_agent_quietly(self._facade, agent_id)
            raise
        if previous is not None and previous.agent_id != agent_id:
            await self._cancel_superseded_agent(session_key, previous.agent_id)
        self._logger.info(
            "telegram_command_new platform=telegram chat_id=%s session_key=%s",
            chat_id,
            session_key,
        )
        await self._send_plain_reply(chat_id, TELEGRAM_NEW_CONFIRMATION)

    async def _cancel_superseded_agent(self, session_key: str, agent_id: str) -> None:
        """Best-effort cancel of the agent replaced by ``/new``.

        Long-running gateways would otherwise leak superseded SDK agents on every
        ``/new``. Cancellation is best-effort: a failure must not break ``/new``.
        """
        try:
            await self._facade.cancel(agent_id)
        except Exception as exc:
            self._logger.warning(
                "telegram_new_supersede_cancel_failed platform=telegram "
                "session_key=%s exception_class=%s",
                session_key,
                exc.__class__.__name__,
            )
            return
        self._logger.info(
            "telegram_new_superseded_agent_cancelled platform=telegram session_key=%s",
            session_key,
        )

    async def _handle_stop(self, *, chat_id: int, session_key: str) -> None:
        row = await self._store.resolve(session_key)
        if row is None:
            await self._send_plain_reply(chat_id, TELEGRAM_STOP_NO_SESSION)
            return
        await self._facade.cancel(row.agent_id)
        self._logger.info(
            "telegram_command_stop platform=telegram chat_id=%s session_key=%s",
            chat_id,
            session_key,
        )
        await self._send_plain_reply(chat_id, TELEGRAM_STOP_SUCCESS)


__all__ = [
    "SUPPORTED_TELEGRAM_COMMANDS",
    "TELEGRAM_HELP_TEXT",
    "TELEGRAM_NEW_CONFIRMATION",
    "TELEGRAM_STOP_NO_SESSION",
    "TELEGRAM_STOP_SUCCESS",
    "TelegramCommandRouter",
    "parse_telegram_command",
    "resolved_workspace",
    "workspace_path",
]
