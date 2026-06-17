"""Slash command routing for the CLI REPL (PRD-004 / ADR-013)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import CursorAgentError
from cursor_agent.facade_logging import emit_command_end, emit_command_start
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import RunStatus, SdkFacade, StreamCallbacks
from cursor_agent.sessions.store import SessionStore

_MODULE_LOGGER = logging.getLogger(__name__)

UNKNOWN_SLASH_MESSAGE = "Command not available yet"

RESERVED_BUILTIN_COMMANDS: frozenset[str] = frozenset(
    {
        "help",
        "quit",
        "new",
        "reset",
        "resume",
        "stop",
        "model",
        "retry",
        "usage",
        "compress",
        "skills",
        "memory",
        "personality",
        "title",
    }
)

_DEFAULT_ALIASES: dict[str, str] = {"reset": "new"}


@dataclass
class ReplState:
    """Mutable REPL session state shared between the loop and command handlers."""

    active_session_id: str | None = None
    last_user_message: str | None = None
    last_status: RunStatus | None = None
    last_usage: dict[str, Any] | None = None
    model_override: str | None = None


@dataclass
class CommandContext:
    """Dependencies passed to slash command handlers without hidden globals."""

    pool: SessionAgentPool
    store: SessionStore
    config: CursorAgentConfig
    facade: SdkFacade
    session_key: str
    state: ReplState
    stream_callbacks: StreamCallbacks | None = None
    stream_writer: Callable[[str], None] | None = None
    logger: logging.Logger | None = None


@dataclass(frozen=True)
class QuitRequested:
    """Sentinel returned by ``/quit`` so ``run_repl`` can exit the loop."""


@dataclass(frozen=True)
class SessionActivated:
    """Handler activated or switched the active session."""

    session_id: str | None


@dataclass(frozen=True)
class CommandHandled:
    """Handler completed without changing the active session id."""


CommandResult = QuitRequested | SessionActivated | CommandHandled | None


class CommandHandler(Protocol):
    """Async slash command handler invoked by the router."""

    async def __call__(
        self,
        ctx: CommandContext,
        arg: str | None,
        writer: Callable[[str], None],
    ) -> CommandResult: ...


@dataclass(frozen=True)
class BuiltinMatch:
    """A registered built-in command matched the slash input."""

    canonical_name: str
    arg: str | None
    handler: CommandHandler


@dataclass(frozen=True)
class UnknownSlashCommand:
    """Slash input did not resolve to a built-in or skill."""

    message: str


ResolveResult = BuiltinMatch | UnknownSlashCommand


def parse_slash_line(line: str) -> tuple[str, str | None]:
    """Parse ``/name arg`` into command name and optional argument.

    Example:
        >>> parse_slash_line("/resume abc-123")
        ('resume', 'abc-123')
    """
    if not line.startswith("/"):
        msg = f"expected slash-prefixed line, received {line!r}"
        raise ValueError(msg)
    body = line[1:].strip()
    if not body:
        msg = f"expected command name after '/', received {line!r}"
        raise ValueError(msg)
    parts = body.split(maxsplit=1)
    name = parts[0]
    if len(parts) < 2:
        return name, None
    arg = parts[1].strip()
    return name, arg or None


class CommandRouter:
    """Register built-in slash commands and resolve user slash input."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._aliases: dict[str, str] = dict(_DEFAULT_ALIASES)

    def register(self, name: str, handler: CommandHandler) -> None:
        """Register a handler by bare command name (no leading ``/``)."""
        if name.startswith("/"):
            msg = f"register bare command name without '/', received {name!r}"
            raise ValueError(msg)
        self._handlers[name] = handler

    def register_alias(self, alias: str, canonical: str) -> None:
        """Map an alias name to a registered canonical command."""
        if alias.startswith("/") or canonical.startswith("/"):
            msg = (
                "register_alias expects bare names without '/', "
                f"received alias={alias!r}, canonical={canonical!r}"
            )
            raise ValueError(msg)
        self._aliases[alias] = canonical

    def resolve(self, line: str) -> ResolveResult | None:
        """Resolve slash input; return ``None`` for free-text lines."""
        stripped = line.strip()
        if not stripped.startswith("/"):
            return None
        name, arg = parse_slash_line(stripped)
        return self.resolve_name(name, arg=arg)

    def resolve_name(self, name: str, *, arg: str | None = None) -> ResolveResult:
        """Resolve a bare command name using ADR-013 precedence."""
        canonical = self._aliases.get(name, name)
        handler = self._handlers.get(canonical)
        if handler is not None:
            return BuiltinMatch(
                canonical_name=canonical,
                arg=arg,
                handler=handler,
            )
        if canonical in RESERVED_BUILTIN_COMMANDS:
            return UnknownSlashCommand(message=UNKNOWN_SLASH_MESSAGE)
        if self._resolve_skill(canonical) is not None:
            msg = f"skill routing is not implemented yet for {canonical!r}"
            raise RuntimeError(msg)
        return UnknownSlashCommand(message=UNKNOWN_SLASH_MESSAGE)

    def _resolve_skill(self, name: str) -> CommandHandler | None:
        """Skills stub until PRD-009; always returns no match."""
        _ = name
        return None


def _command_logger(ctx: CommandContext) -> logging.Logger:
    """Return the injected command logger or the module default."""
    return ctx.logger if ctx.logger is not None else _MODULE_LOGGER


async def _resolve_command_agent_id(ctx: CommandContext) -> str | None:
    """Look up the active session agent id without logging message bodies."""
    session_id = ctx.state.active_session_id
    if session_id is None:
        return None
    row = await ctx.store.resolve(ctx.session_key, session_id=session_id)
    return row.agent_id if row is not None else None


def _command_outcome(result: CommandResult | None) -> str:
    """Map handler results to stable NDJSON outcome values."""
    if isinstance(result, QuitRequested):
        return "quit"
    return "success"


async def execute_builtin_command(
    resolved: BuiltinMatch,
    ctx: CommandContext,
    writer: Callable[[str], None],
    *,
    on_error: Callable[[CursorAgentError], str],
) -> CommandResult | None:
    """Run a built-in handler with NDJSON command lifecycle logging.

    Example:
        result = await execute_builtin_command(resolved, ctx, writer, on_error=format_error)
    """
    logger = _command_logger(ctx)
    session_id = ctx.state.active_session_id
    agent_id = await _resolve_command_agent_id(ctx)
    emit_command_start(
        logger,
        command=resolved.canonical_name,
        session_id=session_id,
        session_key=ctx.session_key,
        agent_id=agent_id,
    )
    started_at = time.perf_counter()
    outcome = "success"
    try:
        result = await resolved.handler(ctx, resolved.arg, writer)
        outcome = _command_outcome(result)
        return result
    except CursorAgentError as exc:
        writer(on_error(exc))
        outcome = "error"
        return None
    finally:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        end_agent_id = await _resolve_command_agent_id(ctx)
        emit_command_end(
            logger,
            command=resolved.canonical_name,
            outcome=outcome,
            duration_ms=duration_ms,
            session_id=ctx.state.active_session_id,
            session_key=ctx.session_key,
            agent_id=end_agent_id,
        )
