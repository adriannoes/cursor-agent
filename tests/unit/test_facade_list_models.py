"""Unit tests for PRD-017 facade ``list_models`` / ``probe_api_key``.

Canonical surface: module-level ephemeral helpers on ``cursor_agent.sdk_facade``
(one-shot bridge; not a long-lived ``AsyncSdkFacade`` agent session).

Q2 LOCKED: probe = SDK ``AsyncCursor.me`` → boolean only; catalog =
``AsyncCursor.models.list`` → DTOs. Auth failures → ``AuthError``; bridge launch
failure → ``ConfigError``.
"""

from __future__ import annotations

from typing import Any

import pytest

from cursor_agent.errors import AuthError, ConfigError
from cursor_agent.usage import DEFAULT_TIMEOUT_SECONDS


def test_auth_probe_and_models_list_timeout_constants_are_distinct() -> None:
    """Named probe/list timeouts exist and do not reuse usage dashboard timeout."""
    from cursor_agent.sdk_facade import (
        AUTH_PROBE_TIMEOUT_SECONDS,
        MODELS_LIST_TIMEOUT_SECONDS,
    )

    assert isinstance(AUTH_PROBE_TIMEOUT_SECONDS, (int, float))
    assert isinstance(MODELS_LIST_TIMEOUT_SECONDS, (int, float))
    assert AUTH_PROBE_TIMEOUT_SECONDS > 0
    assert MODELS_LIST_TIMEOUT_SECONDS > 0
    assert AUTH_PROBE_TIMEOUT_SECONDS != DEFAULT_TIMEOUT_SECONDS
    assert MODELS_LIST_TIMEOUT_SECONDS != DEFAULT_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_module_list_models_returns_dto_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level list_models returns ModelCatalogEntry rows (ephemeral path)."""
    from cursor_agent.sdk_facade import list_models
    from cursor_agent.sdk_facade_models import ModelCatalogEntry

    class _SdkModelRow:
        def __init__(self) -> None:
            self.id = "grok-4.5"
            self.display_name = "Grok 4.5"
            self.description = "test row"

    class _EphemeralBridge:
        """Thin success double: launch_bridge → AsyncCursor.models.list → aclose."""

        async def list_models(self, *, api_key: str | None = None) -> list[Any]:
            _ = api_key
            return [_SdkModelRow()]

        async def aclose(self) -> None:
            return None

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    rows = await list_models(api_key="test-key")

    assert isinstance(rows, list)
    assert len(rows) >= 1
    first = rows[0]
    assert isinstance(first, ModelCatalogEntry)
    assert first.id
    assert first.display_name
    assert not hasattr(first, "recommended")


@pytest.mark.asyncio
async def test_module_probe_api_key_success_returns_true_without_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level probe_api_key returns True and exposes no identity fields."""
    from cursor_agent.sdk_facade import probe_api_key

    class _SdkUser:
        api_key_name = "secret-name"
        user_email = "user@example.com"

    class _EphemeralBridge:
        """Thin success double: launch_bridge → AsyncCursor.me → aclose."""

        async def me(self, *, api_key: str | None = None) -> _SdkUser:
            _ = api_key
            return _SdkUser()

        async def aclose(self) -> None:
            return None

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    ok = await probe_api_key(api_key="test-key")

    assert ok is True
    assert isinstance(ok, bool)
    for forbidden in ("api_key_name", "user_email", "email", "name"):
        assert not hasattr(ok, forbidden)


@pytest.mark.asyncio
async def test_module_probe_api_key_auth_failure_raises_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level probe_api_key maps auth failure to AuthError."""
    from cursor_agent.sdk_facade import probe_api_key

    class _EphemeralBridge:
        async def me(self, *, api_key: str | None = None) -> Any:
            _ = api_key
            raise AuthError(
                "invalid api key: received rejected credential, "
                "expected valid CURSOR_API_KEY"
            )

        async def aclose(self) -> None:
            return None

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    with pytest.raises(AuthError, match="invalid api key"):
        await probe_api_key(api_key="test-key")


@pytest.mark.asyncio
async def test_module_list_models_auth_failure_raises_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level list_models maps auth failure to AuthError."""
    from cursor_agent.sdk_facade import list_models

    class _EphemeralBridge:
        async def list_models(self, *, api_key: str | None = None) -> list[Any]:
            _ = api_key
            raise AuthError(
                "models list unauthorized: received 401, expected authenticated catalog"
            )

        async def aclose(self) -> None:
            return None

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    with pytest.raises(AuthError, match="unauthorized|401|api key"):
        await list_models(api_key="test-key")


@pytest.mark.asyncio
async def test_module_probe_bridge_launch_failure_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level probe_api_key maps launch_bridge failure to ConfigError."""
    from cursor_agent.sdk_facade import probe_api_key

    async def _failing_launch_bridge(*_args: Any, **_kwargs: Any) -> Any:
        raise ConfigError(
            "bridge launch failed: received spawn error, "
            "expected running cursor-sdk bridge"
        )

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _failing_launch_bridge,
    )

    with pytest.raises(ConfigError, match="bridge launch"):
        await probe_api_key(api_key="test-key")


@pytest.mark.asyncio
async def test_module_list_models_bridge_launch_failure_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level list_models maps launch_bridge failure to ConfigError."""
    from cursor_agent.sdk_facade import list_models

    async def _failing_launch_bridge(*_args: Any, **_kwargs: Any) -> Any:
        raise ConfigError(
            "bridge launch failed: received spawn error, "
            "expected running cursor-sdk bridge"
        )

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _failing_launch_bridge,
    )

    with pytest.raises(ConfigError, match="bridge launch"):
        await list_models(api_key="test-key")


@pytest.mark.asyncio
async def test_module_probe_aclose_called_on_auth_error_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level probe_api_key still awaits client.aclose() when auth fails."""
    from cursor_agent.sdk_facade import probe_api_key

    aclose_calls: list[str] = []

    class _EphemeralBridge:
        async def me(self, *, api_key: str | None = None) -> Any:
            _ = api_key
            raise AuthError(
                "invalid api key: received rejected credential, "
                "expected valid CURSOR_API_KEY"
            )

        async def aclose(self) -> None:
            aclose_calls.append("aclose")

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    with pytest.raises(AuthError):
        await probe_api_key(api_key="test-key")

    assert aclose_calls == ["aclose"]


@pytest.mark.asyncio
async def test_module_list_models_aclose_called_on_error_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level list_models still awaits client.aclose() when the call fails."""
    from cursor_agent.sdk_facade import list_models

    aclose_calls: list[str] = []

    class _EphemeralBridge:
        """Thin test double for launch_bridge → call → aclose lifecycle."""

        async def list_models(self, *, api_key: str | None = None) -> list[Any]:
            _ = api_key
            raise AuthError(
                "models list unauthorized: received 401, expected authenticated catalog"
            )

        async def aclose(self) -> None:
            aclose_calls.append("aclose")

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    with pytest.raises(AuthError):
        await list_models(api_key="test-key")

    assert aclose_calls == ["aclose"]


@pytest.mark.asyncio
async def test_module_list_models_invalid_row_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty id/display_name rows map to ConfigError (not bare ValueError)."""
    from cursor_agent.sdk_facade import list_models

    class _Row:
        id = ""
        display_name = ""
        description = None

    class _EphemeralBridge:
        async def list_models(self, *, api_key: str | None = None) -> list[Any]:
            _ = api_key
            return [_Row()]

        async def aclose(self) -> None:
            return None

    async def _launch_bridge(*_args: Any, **_kwargs: Any) -> _EphemeralBridge:
        return _EphemeralBridge()

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _launch_bridge,
    )

    with pytest.raises(ConfigError, match="invalid SDK model row"):
        await list_models(api_key="test-key")
