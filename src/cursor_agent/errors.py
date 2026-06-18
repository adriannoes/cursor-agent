"""Domain errors for cursor-agent (ADR-024, ADR-008).

AsyncSdkFacade maps SDK and network failures to ``CursorAgentError`` subclasses.
``AgentBusyError`` is a shared concurrency type raised only by ``SessionAgentPool``.
"""

from __future__ import annotations


class CursorAgentError(Exception):
    """Base for pre-run failures mapped by ``AsyncSdkFacade``.

    Attributes:
        is_retryable: When ``True``, the facade may retry up to three times.
        retry_after: Optional seconds hint from upstream (e.g. ``Retry-After``).

    Example:
        >>> err = NetworkError("connection reset")
        >>> err.is_retryable
        True
    """

    is_retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        """Initialize with a message and optional retry hint.

        Args:
            message: Human-readable failure description.
            retry_after: Suggested wait in seconds before retry, if any.
        """
        super().__init__(message)
        self.retry_after = retry_after


class AuthError(CursorAgentError):
    """API key invalid or expired."""

    is_retryable = False


class ConfigError(CursorAgentError):
    """Invalid parameters before a run starts."""

    is_retryable = False


class NetworkError(CursorAgentError):
    """Timeout, connection reset, or transient upstream 5xx."""

    is_retryable = True


class SdkInternalError(NetworkError):
    """SDK bridge internal server error after resume or send."""

    is_retryable = True


class TimeoutError(CursorAgentError):
    """Run or bridge exceeded a configured time limit."""

    is_retryable = True


class InvalidAgentError(CursorAgentError):
    """``agent_id`` does not exist or resume is impossible."""

    is_retryable = False


class AgentBusyError(Exception):
    """Active run on the same session; raised only by ``SessionAgentPool``.

    ``AsyncSdkFacade`` must never raise this type (ADR-008). Gateway adapters
    catch it and send a friendly busy message to the user.
    """
