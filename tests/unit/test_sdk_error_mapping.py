"""Unit tests for SDK exception mapping (ADR-024)."""

from __future__ import annotations

from cursor_agent.errors import AuthError, ConfigError, CursorAgentError, NetworkError
from cursor_agent.sdk_error_mapping import map_sdk_exception
from cursor_sdk.errors import (
    AuthenticationError as SdkAuthenticationError,
    ConfigurationError as SdkConfigurationError,
    CursorAgentError as SdkCursorAgentError,
    PermissionDeniedError as SdkPermissionDeniedError,
)


def test_map_sdk_exception_maps_sdk_permission_denied_to_auth_error() -> None:
    """PermissionDenied must surface as non-retryable AuthError for gateway policy."""
    mapped = map_sdk_exception(SdkPermissionDeniedError("forbidden"))

    assert isinstance(mapped, AuthError)
    assert str(mapped) == "forbidden"
    assert mapped.is_retryable is False


def test_map_sdk_exception_maps_sdk_authentication_error_to_auth_error() -> None:
    mapped = map_sdk_exception(SdkAuthenticationError("invalid api key"))

    assert isinstance(mapped, AuthError)
    assert mapped.is_retryable is False


def test_map_sdk_exception_passthrough_existing_cursor_agent_error() -> None:
    original = CursorAgentError("already mapped")

    assert map_sdk_exception(original) is original


def test_map_sdk_exception_maps_retryable_sdk_cursor_agent_error_to_network_error() -> (
    None
):
    exc = SdkCursorAgentError("upstream unavailable")
    exc.is_retryable = True  # type: ignore[attr-defined]

    mapped = map_sdk_exception(exc)

    assert isinstance(mapped, NetworkError)


def test_map_sdk_exception_maps_sdk_configuration_error_to_config_error() -> None:
    mapped = map_sdk_exception(SdkConfigurationError("missing model"))

    assert isinstance(mapped, ConfigError)
    assert str(mapped) == "missing model"
