"""User-facing error formatting for the CLI REPL (PRD-003).

Shared so every REPL path renders domain errors with the same shape; lives in
its own module to avoid an import cycle between ``repl_session`` and
``slash_commands``.
"""

from __future__ import annotations

from cursor_agent.errors import CursorAgentError


def format_error(exc: CursorAgentError) -> str:
    """Render a domain error as a single-line, user-facing REPL message.

    Example:
        >>> from cursor_agent.errors import ConfigError
        >>> format_error(ConfigError("bad runtime"))
        'Error: bad runtime'
    """
    return f"Error: {exc}"
