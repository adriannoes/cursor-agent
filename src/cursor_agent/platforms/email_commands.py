"""Email slash-command parsing and session command handling."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final

from cursor_agent.agent_cleanup import cancel_agent_quietly
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.gateway.config import GatewayConfig
from cursor_agent.product_copy import EMAIL_NO_SESSION_HINT
from cursor_agent.sdk_facade import SdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

EMAIL_NEW_CONFIRMATION: Final[str] = "Started a new conversation."
EMAIL_STOP_SUCCESS: Final[str] = "Run cancelled."
EMAIL_STOP_NO_SESSION: Final[str] = (
    "No active session. Send /new to start a conversation."
)
EMAIL_HELP_TEXT: Final[str] = """\
Email commands (put the command alone on the first line of the body;
subject is used only when the body is empty):

/new — Start or reset your conversation
/stop — Cancel the current run
/help — Show this message
"""

SUPPORTED_EMAIL_COMMANDS: Final[frozenset[str]] = frozenset(
    {"new", "stop", "help", "start"},
)

SendPlainReply = Callable[[str, str], Awaitable[None]]


def parse_email_command(*, subject: str, body: str) -> str | None:
    """Return a supported slash command from the body, or subject if body is empty.

    Subject is consulted only when the body has no non-whitespace content so that
    mail clients that preserve prior subjects (e.g. ``Re: /new``) cannot hijack
    a free-text reply.
    """
    body_command = _parse_command_token(body)
    if body_command is not None:
        return body_command
    if body.strip():
        return None
    return _parse_command_token(subject)


def _parse_command_token(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip()
    if not first_line.startswith("/"):
        return None
    # Command-only lines: "/new" or "/new extra" — only bare command counts as cmd
    # when the first token is a known command; extra text after command is ignored
    # for dispatch (Telegram-compatible: first token wins).
    command_token = first_line.split(maxsplit=1)[0]
    command_name = command_token.lstrip("/").lower()
    if command_name in SUPPORTED_EMAIL_COMMANDS:
        return command_name
    return None


def workspace_path(
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
) -> str:
    """Return the canonical workspace path used for email session keys."""
    return config.runtime.local.cwd or gateway_config.workspace


def resolved_workspace(
    gateway_config: GatewayConfig,
    config: CursorAgentConfig,
) -> str:
    """Return the absolute workspace path used for SDK agent creation."""
    return str(Path(workspace_path(gateway_config, config)).resolve())


class EmailCommandRouter:
    """Dispatch supported email slash commands to session actions."""

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
        sender: str,
        session_key: str,
    ) -> None:
        """Route a parsed command name to its session action handler."""
        if command == "new":
            await self._handle_new(sender=sender, session_key=session_key)
            return
        if command == "stop":
            await self._handle_stop(sender=sender, session_key=session_key)
            return
        if command == "help":
            await self._send_plain_reply(sender, EMAIL_HELP_TEXT.strip())
            return
        if command == "start":
            await self._send_plain_reply(sender, EMAIL_NO_SESSION_HINT)
            return
        msg = (
            "unsupported email command dispatch: "
            f"received {command!r}, expected one of {sorted(SUPPORTED_EMAIL_COMMANDS)!r}"
        )
        raise ValueError(msg)

    async def _handle_new(self, *, sender: str, session_key: str) -> None:
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
            await self._dispose_superseded_agent(session_key, previous.agent_id)
        self._logger.info(
            "email_command_new platform=email sender=%s session_key=%s",
            sender,
            session_key,
        )
        await self._send_plain_reply(sender, EMAIL_NEW_CONFIRMATION)

    async def _dispose_superseded_agent(self, session_key: str, agent_id: str) -> None:
        """Best-effort dispose of the agent replaced by ``/new``."""
        try:
            await self._facade.dispose_agent(agent_id)
        except Exception as exc:
            self._logger.warning(
                "email_new_supersede_dispose_failed platform=email "
                "session_key=%s exception_class=%s",
                session_key,
                exc.__class__.__name__,
            )
            return
        self._logger.info(
            "email_new_superseded_agent_disposed platform=email session_key=%s",
            session_key,
        )

    async def _handle_stop(self, *, sender: str, session_key: str) -> None:
        row = await self._store.resolve(session_key)
        if row is None:
            await self._send_plain_reply(sender, EMAIL_STOP_NO_SESSION)
            return
        await self._facade.cancel(row.agent_id)
        self._logger.info(
            "email_command_stop platform=email sender=%s session_key=%s",
            sender,
            session_key,
        )
        await self._send_plain_reply(sender, EMAIL_STOP_SUCCESS)


__all__ = [
    "EMAIL_HELP_TEXT",
    "EMAIL_NEW_CONFIRMATION",
    "EMAIL_STOP_NO_SESSION",
    "EMAIL_STOP_SUCCESS",
    "EmailCommandRouter",
    "SUPPORTED_EMAIL_COMMANDS",
    "parse_email_command",
    "resolved_workspace",
    "workspace_path",
]
