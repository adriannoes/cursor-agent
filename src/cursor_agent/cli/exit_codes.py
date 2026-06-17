"""Map run status and domain errors to CLI exit codes (PRD-003 FR-10)."""

from __future__ import annotations

from cursor_agent.errors import CursorAgentError
from cursor_agent.sdk_facade import RunStatus


def exit_code_for_status(status: RunStatus | None) -> int:
    """Return the process exit code for a terminal REPL run status.

    Example:
        >>> exit_code_for_status(RunStatus.FINISHED)
        0
    """
    match status:
        case None | RunStatus.FINISHED | RunStatus.CANCELLED:
            return 0
        case RunStatus.ERROR:
            return 2


def exit_code_for_error(exc: BaseException) -> int:
    """Return the process exit code for a pre-run or startup failure.

    Example:
        >>> from cursor_agent.errors import ConfigError
        >>> exit_code_for_error(ConfigError("invalid config"))
        1
    """
    if isinstance(exc, CursorAgentError):
        return 1
    return 1
