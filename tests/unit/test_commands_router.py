"""Unit tests for CommandRouter parsing and resolution (PRD-004 FR-1, FR-2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest

from cursor_agent.cli.command_router import (
    RESERVED_BUILTIN_COMMANDS,
    BuiltinMatch,
    CommandContext,
    CommandRouter,
    ReplState,
    UnknownSlashCommand,
    parse_slash_line,
)
from cursor_agent.sdk_facade import RunStatus

CommandHandler = Callable[..., Any]


def _noop_handler() -> CommandHandler:
    async def handler(
        ctx: CommandContext,
        arg: str | None,
        writer: Callable[[str], None],
    ) -> None:
        _ = (ctx, arg, writer)

    return handler


@pytest.mark.parametrize(
    ("line", "expected_name", "expected_arg"),
    [
        ("/resume abc-123", "resume", "abc-123"),
        ("/new", "new", None),
        ("/model composer-2.5", "model", "composer-2.5"),
        ("/foo  bar  baz", "foo", "bar  baz"),
    ],
)
def test_parse_slash_line_splits_name_and_arg(
    line: str,
    expected_name: str,
    expected_arg: str | None,
) -> None:
    """Slash lines split into command name and optional trailing argument."""
    assert parse_slash_line(line) == (expected_name, expected_arg)


def test_register_command_by_name_without_slash_prefix() -> None:
    """Handlers register with bare command names, not leading slashes."""
    router = CommandRouter()
    handler = _noop_handler()
    router.register("new", handler)
    result = router.resolve("/new")
    assert isinstance(result, BuiltinMatch)
    assert result.canonical_name == "new"
    assert result.handler is handler


def test_register_rejects_slash_prefixed_name() -> None:
    """Registration must use bare names so parsing stays centralized."""
    router = CommandRouter()
    with pytest.raises(ValueError, match="/"):
        router.register("/new", _noop_handler())


def test_reset_alias_resolves_to_new_handler() -> None:
    """ADR-013: /reset is an alias of /new."""
    router = CommandRouter()
    handler = _noop_handler()
    router.register("new", handler)
    result = router.resolve("/reset")
    assert isinstance(result, BuiltinMatch)
    assert result.canonical_name == "new"
    assert result.handler is handler
    assert result.arg is None


def test_reset_alias_preserves_arguments() -> None:
    """Alias resolution keeps any trailing argument untouched."""
    router = CommandRouter()
    router.register("new", _noop_handler())
    result = router.resolve("/reset extra")
    assert isinstance(result, BuiltinMatch)
    assert result.arg == "extra"


@pytest.mark.parametrize(
    "name",
    sorted(
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
    ),
)
def test_reserved_builtin_command_names_match_adr_013(name: str) -> None:
    """ADR-013 denylist blocks skill namespace collisions."""
    assert name in RESERVED_BUILTIN_COMMANDS


def test_builtin_handler_takes_precedence_over_skills_stub() -> None:
    """Built-in registry wins before the skills fallback path."""
    router = CommandRouter()
    handler = _noop_handler()
    router.register("new", handler)
    result = router.resolve("/new")
    assert isinstance(result, BuiltinMatch)
    assert result.handler is handler


def test_non_reserved_slash_without_skill_falls_through_as_free_text() -> None:
    """ADR-013: non-reserved slash names with no skill match return None for free text."""
    router = CommandRouter()
    assert router.resolve("/custom-skill") is None


def test_reserved_name_without_handler_returns_unknown_feedback() -> None:
    """Reserved built-ins without handlers surface friendly unknown feedback."""
    router = CommandRouter()
    result = router.resolve("/help")
    assert isinstance(result, UnknownSlashCommand)
    assert "not available" in result.message.lower()


def test_unknown_slash_without_skill_returns_none_for_free_text() -> None:
    """ADR-013: unknown slash with no skill match falls through to agent free text."""
    router = CommandRouter()
    assert router.resolve("/totally-unknown") is None


def test_resolve_non_slash_line_returns_none() -> None:
    """Free-text lines are not slash commands."""
    router = CommandRouter()
    assert router.resolve("hello agent") is None


def test_repl_state_defaults() -> None:
    """ReplState starts empty for session and last-turn context."""
    state = ReplState()
    assert state.active_session_id is None
    assert state.last_user_message is None
    assert state.last_status is None
    assert state.model_override is None


def test_repl_state_accepts_last_turn_fields() -> None:
    """ReplState stores session id, retry text, status, and model override."""
    state = ReplState(
        active_session_id="sess-1",
        last_user_message="fix tests",
        last_status=RunStatus.ERROR,
        model_override="composer-2.5",
    )
    assert state.active_session_id == "sess-1"
    assert state.last_user_message == "fix tests"
    assert state.last_status is RunStatus.ERROR
    assert state.model_override == "composer-2.5"


def test_command_context_bundles_repl_dependencies() -> None:
    """CommandContext exposes pool, store, config, facade, key, and ReplState."""
    state = ReplState()
    pool = MagicMock()
    store = MagicMock()
    config = MagicMock()
    facade = MagicMock()
    ctx = CommandContext(
        pool=pool,
        store=store,
        config=config,
        facade=facade,
        session_key="default",
        state=state,
    )
    assert ctx.pool is pool
    assert ctx.store is store
    assert ctx.config is config
    assert ctx.facade is facade
    assert ctx.session_key == "default"
    assert ctx.state is state
