"""Slash command handlers for the CLI REPL (PRD-003 / PRD-004)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from cursor_agent.cli.command_router import (
    CommandContext,
    CommandFailed,
    CommandHandled,
    CommandResult,
    CommandRouter,
    QuitRequested,
    SessionActivated,
)
from cursor_agent.cli.compress import run_compress_session
from cursor_agent.cli.error_display import format_error
from cursor_agent.cli.rich_display import format_memory_show_output
from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import ConfigError, CursorAgentError
from cursor_agent.memory import MEMORY_FILENAME, USER_FILENAME, LocalMemoryStore
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import RunStatus, SdkFacade
from cursor_agent.sessions.models import SessionCreateParams
from cursor_agent.sessions.store import SessionStore

_HELP_TEXT = """\
Slash commands:

P0 — session control:
  /new            Start a new session
  /reset          Alias of /new
  /resume [id]    Resume a session (latest or by id)
  /help           List available commands
  /quit           Exit the REPL

P1 — operational:
  /stop           Cancel the current run
  /model [id]     Set model override for next send

P2 — advanced:
  /retry          Resend the last user message
  /usage          Show usage from the last run
  /compress       Compress session context
  /memory show    Inspect effective Memory v1 payload
"""

_NO_ACTIVE_SESSION = "No active session. Use /new or /resume to continue."
_NO_PREVIOUS_MESSAGE = "No previous message to retry."
_NO_USAGE_DATA = "No usage data from the last run."
_RUN_FAILED_NOTICE = "Run failed (status=error). You can retry or continue."
_MODEL_USAGE = "Usage: /model <id>"
_COMPRESSING_MESSAGE = "Compressing context..."
_COMPRESS_SUCCESS = "Context compressed. New agent active."
_MEMORY_USAGE = "Usage: /memory show"
_MEMORY_UNSUPPORTED_SUBCOMMAND = (
    "Unsupported /memory subcommand: {subcommand!r}. Only /memory show is available."
)


async def handle_new(
    *,
    facade: SdkFacade,
    store: SessionStore,
    config: CursorAgentConfig,
    session_key: str,
    writer: Callable[[str], None],
    model: str | None = None,
) -> str:
    """Create a new SDK agent and session row; return the new session id."""
    workspace = str(Path(config.runtime.local.cwd).resolve())
    effective_model = model if model is not None and model.strip() else config.model
    agent_id = await facade.create_agent(
        workspace=workspace,
        model=effective_model,
        tool_profile=config.tool_profile,
        runtime_mode=config.runtime.mode,
    )
    row = await store.create(
        SessionCreateParams(
            session_key=session_key,
            agent_id=agent_id,
            workspace=workspace,
            runtime=config.runtime.mode,
            tool_profile=config.tool_profile,
            title=None,
        )
    )
    writer(f"Created session {row.id}")
    return row.id


async def handle_resume(
    *,
    pool: SessionAgentPool,
    session_key: str,
    arg: str | None,
    writer: Callable[[str], None],
    model_override: str | None = None,
) -> str | None:
    """Resume a session via ``pool.get``; return session id or ``None`` on failure."""
    try:
        row = await pool.get(
            session_key,
            session_id=arg or None,
            model_override=model_override,
        )
    except CursorAgentError as exc:
        writer(format_error(exc))
        return None
    writer(f"Resumed session {row.id}")
    return row.id


def handle_help(*, writer: Callable[[str], None]) -> None:
    """Write static help listing P0/P1/P2 commands and the /reset alias."""
    writer(_HELP_TEXT.strip())


async def _route_new(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Wrap PRD-003 ``handle_new`` for CommandRouter dispatch."""
    _ = arg
    try:
        session_id = await handle_new(
            facade=ctx.facade,
            store=ctx.store,
            config=ctx.config,
            session_key=ctx.session_key,
            writer=writer,
            model=ctx.state.model_override,
        )
    except CursorAgentError as exc:
        writer(format_error(exc))
        return CommandFailed()
    return SessionActivated(session_id=session_id)


async def _route_resume(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Wrap PRD-003 ``handle_resume`` for CommandRouter dispatch."""
    new_id = await handle_resume(
        pool=ctx.pool,
        session_key=ctx.session_key,
        arg=arg,
        writer=writer,
        model_override=ctx.state.model_override,
    )
    if new_id is not None:
        return SessionActivated(session_id=new_id)
    return CommandFailed()


async def _route_quit(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Return a sentinel so ``run_repl`` exits without ``sys.exit``."""
    _ = ctx, arg, writer
    return QuitRequested()


async def _route_help(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """List registered slash commands grouped by priority."""
    _ = ctx, arg
    handle_help(writer=writer)
    return CommandHandled()


async def _route_stop(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Cancel the active session agent via facade.cancel."""
    _ = arg
    if ctx.state.active_session_id is None:
        writer(_NO_ACTIVE_SESSION)
        return CommandHandled()
    row = await ctx.store.resolve(
        ctx.session_key,
        session_id=ctx.state.active_session_id,
    )
    if row is None:
        writer(
            f"No session found for active_session_id={ctx.state.active_session_id!r}"
        )
        return CommandHandled()
    await ctx.facade.cancel(row.agent_id)
    ctx.state.last_status = RunStatus.CANCELLED
    ctx.state.last_usage = None
    writer("Run cancelled.")
    return CommandHandled()


async def _route_model(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Store an in-memory model override and resume the active agent."""
    if arg is None or not arg.strip():
        writer(_MODEL_USAGE)
        return CommandHandled()
    model_id = arg.strip()
    ctx.state.model_override = model_id
    if ctx.state.active_session_id is not None:
        row = await ctx.store.resolve(
            ctx.session_key,
            session_id=ctx.state.active_session_id,
        )
        if row is not None:
            try:
                await ctx.facade.resume_agent(
                    row.agent_id,
                    workspace=row.workspace,
                    model=model_id,
                    tool_profile=row.tool_profile,
                    runtime_mode=row.runtime,
                )
                ctx.pool.forget_resumed_agent(row.agent_id)
            except CursorAgentError as exc:
                writer(format_error(exc))
                return CommandFailed()
    writer(f"Model override set to {model_id}")
    return CommandHandled()


async def _route_retry(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Resend the last free-text user message on the active session."""
    _ = arg
    if ctx.state.last_user_message is None:
        writer(_NO_PREVIOUS_MESSAGE)
        return CommandHandled()
    if ctx.state.active_session_id is None:
        writer(_NO_ACTIVE_SESSION)
        return CommandHandled()
    try:
        send_result = await ctx.pool.send(
            ctx.session_key,
            ctx.state.last_user_message,
            session_id=ctx.state.active_session_id,
            callbacks=ctx.stream_callbacks,
            blocking=True,
            model_override=ctx.state.model_override,
        )
    except CursorAgentError as exc:
        writer(format_error(exc))
        return CommandFailed()
    ctx.state.last_status = send_result.status
    ctx.state.last_usage = send_result.usage
    if ctx.stream_writer is not None:
        ctx.stream_writer("\n")
    if send_result.status == RunStatus.ERROR:
        writer(_RUN_FAILED_NOTICE)
    return CommandHandled()


def _format_usage_line(usage: dict[str, object]) -> str:
    """Format last-turn usage metadata for terminal output."""
    parts = [f"{key}={value}" for key, value in usage.items()]
    return "Last run usage: " + ", ".join(parts)


async def _route_usage(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Show usage metadata captured from the last free-text or retry turn."""
    _ = arg
    if ctx.state.last_usage is None:
        writer(_NO_USAGE_DATA)
        return CommandHandled()
    writer(_format_usage_line(ctx.state.last_usage))
    return CommandHandled()


async def _route_compress(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Run the /compress saga on the active session."""
    _ = arg
    if ctx.state.active_session_id is None:
        writer(_NO_ACTIVE_SESSION)
        return CommandHandled()
    session_id = ctx.state.active_session_id
    writer(_COMPRESSING_MESSAGE)
    try:
        result = await run_compress_session(
            store=ctx.store,
            facade=ctx.facade,
            config=ctx.config,
            session_key=ctx.session_key,
            session_id=session_id,
        )
    except CursorAgentError as exc:
        writer(format_error(exc))
        return CommandFailed()
    ctx.pool.forget_resumed_agent(result.previous_agent_id)
    ctx.pool.forget_resumed_agent(result.new_agent_id)
    ctx.state.last_status = RunStatus.FINISHED
    ctx.state.last_usage = None
    writer(_COMPRESS_SUCCESS)
    return CommandHandled()


def _memory_store_for_context(ctx: CommandContext) -> LocalMemoryStore:
    """Return a memory store using the injected root or the default home path."""
    if ctx.memory_root is not None:
        return LocalMemoryStore(root=ctx.memory_root)
    return LocalMemoryStore()


def _section_missing(store: LocalMemoryStore, filename: str) -> bool:
    """Return True when a memory file is absent on disk."""
    if not store.root.exists():
        return True
    return not (store.root / filename).is_file()


async def _route_memory(
    ctx: CommandContext,
    arg: str | None,
    writer: Callable[[str], None],
) -> CommandResult:
    """Show the effective Memory v1 payload from local files (CLI-only)."""
    if arg is None or not arg.strip():
        writer(_MEMORY_USAGE)
        return CommandHandled()
    subcommand = arg.strip().split(maxsplit=1)[0].lower()
    if subcommand != "show":
        writer(_MEMORY_UNSUPPORTED_SUBCOMMAND.format(subcommand=subcommand))
        return CommandHandled()
    store = _memory_store_for_context(ctx)
    try:
        payload = store.build_effective_payload()
    except ValueError as exc:
        writer(format_error(ConfigError(str(exc))))
        return CommandFailed()
    output = format_memory_show_output(
        payload,
        user_missing=_section_missing(store, USER_FILENAME),
        memory_missing=_section_missing(store, MEMORY_FILENAME),
    )
    writer(output)
    return CommandHandled()


def build_repl_command_router() -> CommandRouter:
    """Build a router with P0 slash commands registered for the REPL."""
    router = CommandRouter()
    router.register("new", _route_new)
    router.register("resume", _route_resume)
    router.register("quit", _route_quit)
    router.register("help", _route_help)
    router.register("stop", _route_stop)
    router.register("model", _route_model)
    router.register("retry", _route_retry)
    router.register("usage", _route_usage)
    router.register("compress", _route_compress)
    router.register("memory", _route_memory)
    router.register_alias("reset", "new")
    return router
