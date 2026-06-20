"""Map SDK and transport exceptions onto cursor-agent errors (ADR-024)."""

from __future__ import annotations

from cursor_agent.errors import (
    AuthError,
    ConfigError,
    CursorAgentError,
    InvalidAgentError,
    NetworkError,
    SdkInternalError,
    TimeoutError as AgentTimeoutError,
)
from cursor_agent.sdk_retry import parse_retry_after_seconds

# SDK import boundary for error type mapping (see AGENTS.md).
from cursor_sdk.errors import (
    AgentNotFoundError as SdkAgentNotFoundError,
    APITimeoutError as SdkAPITimeoutError,
    AuthenticationError as SdkAuthenticationError,
    ConfigurationError as SdkConfigurationError,
    CursorAgentError as SdkCursorAgentError,
    InternalServerError as SdkInternalServerError,
    NetworkError as SdkNetworkError,
    PermissionDeniedError as SdkPermissionDeniedError,
    RateLimitError as SdkRateLimitError,
)


def map_sdk_exception(exc: BaseException) -> BaseException:
    """Map SDK and transport exceptions onto cursor-agent errors (ADR-024)."""
    if isinstance(exc, CursorAgentError):
        return exc

    if isinstance(exc, SdkCursorAgentError):
        message = str(exc)
        retry_after = parse_retry_after_seconds(getattr(exc, "retry_after", None))
        is_retryable = bool(getattr(exc, "is_retryable", False))

        if isinstance(exc, (SdkAuthenticationError, SdkPermissionDeniedError)):
            return AuthError(message)
        if isinstance(exc, SdkAPITimeoutError):
            return AgentTimeoutError(message, retry_after=retry_after)
        if isinstance(exc, SdkAgentNotFoundError):
            return InvalidAgentError(message)
        if isinstance(exc, SdkConfigurationError):
            return ConfigError(message)
        if isinstance(exc, SdkInternalServerError):
            return SdkInternalError(message, retry_after=retry_after)
        if isinstance(exc, (SdkNetworkError, SdkRateLimitError)):
            return NetworkError(message, retry_after=retry_after)
        if is_retryable:
            return NetworkError(message, retry_after=retry_after)
        return ConfigError(message)

    exc_name = exc.__class__.__name__.lower()
    message = str(exc)
    if "auth" in exc_name or "unauthorized" in message.lower():
        return AuthError(message)
    if "timeout" in exc_name:
        return AgentTimeoutError(message)
    if "network" in exc_name or "connection" in exc_name:
        return NetworkError(message)
    if isinstance(exc, TypeError):
        return ConfigError(f"SDK request serialization failed: {message}")
    return exc
