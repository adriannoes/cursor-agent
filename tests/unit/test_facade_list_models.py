"""Unit tests for PRD-017 facade ``list_models`` / ``probe_api_key`` (Wave 0 / 1.1).

Intended public API (implemented in task 1.3 — these tests must fail until then):

- **Ephemeral module-level helpers** on ``cursor_agent.sdk_facade`` (one-shot
  bridge; not a long-lived ``AsyncSdkFacade`` agent session):

  ``async def probe_api_key(*, api_key: str, timeout_seconds: float | None = None) -> bool``
  ``async def list_models(*, api_key: str, timeout_seconds: float | None = None) -> list[ModelCatalogEntry]``

- **Project DTO** ``ModelCatalogEntry`` in ``sdk_facade_models`` with at least
  ``id`` and ``display_name`` (optional ``description``). Never raw SDK types.
  ``(recommended)`` markers stay in the CLI — not asserted here.

- **Named timeouts** ``AUTH_PROBE_TIMEOUT_SECONDS`` and
  ``MODELS_LIST_TIMEOUT_SECONDS`` on ``sdk_facade``, each distinct from
  ``usage.DEFAULT_TIMEOUT_SECONDS``.

- **FakeSdkFacade** constructor knobs for injection (task 1.3):

  ``model_catalog``, ``probe_ok``, ``probe_error``, ``list_models_error``,
  ``bridge_launch_error``. Lifecycle: ``aclose_call_count`` increments when the
  ephemeral client closes, including on error paths.

Q2 LOCKED: probe = SDK ``AsyncCursor.me`` → boolean only; catalog =
``AsyncCursor.models.list`` → DTOs. Auth failures → ``AuthError``; bridge launch
failure → ``ConfigError``.
"""

from __future__ import annotations

from typing import Any

import pytest

from cursor_agent.errors import AuthError, ConfigError
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.usage import DEFAULT_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Timeout constants (import symbols that do not exist yet — red until 1.3)
# ---------------------------------------------------------------------------


def test_auth_probe_and_models_list_timeout_constants_are_distinct() -> None:
    """Named probe/list timeouts exist and do not reuse usage dashboard timeout."""
    from cursor_agent.sdk_facade import (  # noqa: PLC0415 — red until 1.3 exports
        AUTH_PROBE_TIMEOUT_SECONDS,
        MODELS_LIST_TIMEOUT_SECONDS,
    )

    assert isinstance(AUTH_PROBE_TIMEOUT_SECONDS, (int, float))
    assert isinstance(MODELS_LIST_TIMEOUT_SECONDS, (int, float))
    assert AUTH_PROBE_TIMEOUT_SECONDS > 0
    assert MODELS_LIST_TIMEOUT_SECONDS > 0
    assert AUTH_PROBE_TIMEOUT_SECONDS != DEFAULT_TIMEOUT_SECONDS
    assert MODELS_LIST_TIMEOUT_SECONDS != DEFAULT_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Fake / list_models DTO shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_list_models_returns_dto_rows_with_id_and_display_name() -> None:
    """FakeSdkFacade.list_models returns project DTOs, not raw SDK types."""
    from cursor_agent.sdk_facade_models import ModelCatalogEntry  # noqa: PLC0415

    catalog = [
        ModelCatalogEntry(id="grok-4.5", display_name="Grok 4.5"),
        ModelCatalogEntry(
            id="composer-2.5",
            display_name="Composer 2.5",
            description="optional description",
        ),
    ]
    facade = FakeSdkFacade(model_catalog=catalog)

    rows = await facade.list_models()

    assert len(rows) >= 1
    for row in rows:
        assert isinstance(row, ModelCatalogEntry)
        assert isinstance(row.id, str) and row.id
        assert isinstance(row.display_name, str) and row.display_name
        assert not hasattr(row, "recommended")


@pytest.mark.asyncio
async def test_module_list_models_returns_dto_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level list_models returns ModelCatalogEntry rows (ephemeral path)."""
    from cursor_agent.sdk_facade import list_models  # noqa: PLC0415
    from cursor_agent.sdk_facade_models import ModelCatalogEntry  # noqa: PLC0415

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


# ---------------------------------------------------------------------------
# probe_api_key — boolean only, no identity fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_probe_api_key_success_returns_true_without_identity() -> None:
    """Fake probe_api_key success is a truthy bool — never identity fields."""
    facade = FakeSdkFacade(probe_ok=True)

    ok = await facade.probe_api_key()

    assert ok is True
    assert isinstance(ok, bool)
    # bool has no identity attrs; guard against accidental dict/object returns.
    assert not isinstance(ok, dict)
    for forbidden in ("api_key_name", "user_email", "email", "name"):
        assert not hasattr(ok, forbidden)


@pytest.mark.asyncio
async def test_module_probe_api_key_success_returns_true_without_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level probe_api_key returns True and exposes no identity fields."""
    from cursor_agent.sdk_facade import probe_api_key  # noqa: PLC0415

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


# ---------------------------------------------------------------------------
# Auth failure → AuthError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_probe_api_key_auth_failure_raises_auth_error() -> None:
    """Injected probe auth failure raises AuthError from cursor_agent.errors."""
    facade = FakeSdkFacade(
        probe_error=AuthError(
            "invalid api key: received rejected credential, expected valid CURSOR_API_KEY"
        ),
    )

    with pytest.raises(AuthError, match="invalid api key"):
        await facade.probe_api_key()


@pytest.mark.asyncio
async def test_fake_list_models_auth_failure_raises_auth_error() -> None:
    """Injected list_models auth failure raises AuthError."""
    facade = FakeSdkFacade(
        list_models_error=AuthError(
            "models list unauthorized: received 401, expected authenticated catalog"
        ),
    )

    with pytest.raises(AuthError, match="unauthorized|401|api key"):
        await facade.list_models()


# ---------------------------------------------------------------------------
# Bridge launch failure → ConfigError (explicit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_bridge_launch_failure_on_probe_raises_config_error() -> None:
    """Bridge launch/spawn failure on probe maps to ConfigError, not AuthError."""
    facade = FakeSdkFacade(
        bridge_launch_error=ConfigError(
            "bridge launch failed: received spawn error, expected running cursor-sdk bridge"
        ),
    )

    with pytest.raises(ConfigError, match="bridge launch"):
        await facade.probe_api_key()


@pytest.mark.asyncio
async def test_fake_bridge_launch_failure_on_list_models_raises_config_error() -> None:
    """Bridge launch/spawn failure on list_models maps to ConfigError."""
    facade = FakeSdkFacade(
        bridge_launch_error=ConfigError(
            "bridge launch failed: received spawn error, expected running cursor-sdk bridge"
        ),
    )

    with pytest.raises(ConfigError, match="bridge launch"):
        await facade.list_models()


@pytest.mark.asyncio
async def test_module_probe_bridge_launch_failure_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level probe_api_key maps launch_bridge failure to ConfigError."""
    from cursor_agent.sdk_facade import probe_api_key  # noqa: PLC0415

    async def _failing_launch_bridge(*_args: Any, **_kwargs: Any) -> Any:
        raise ConfigError(
            "bridge launch failed: received spawn error, expected running cursor-sdk bridge"
        )

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.AsyncClient.launch_bridge",
        _failing_launch_bridge,
    )

    with pytest.raises(ConfigError, match="bridge launch"):
        await probe_api_key(api_key="test-key")


# ---------------------------------------------------------------------------
# Ephemeral lifecycle — aclose() still called on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_probe_aclose_called_on_auth_error_path() -> None:
    """Ephemeral probe lifecycle calls aclose even when AuthError is raised."""
    facade = FakeSdkFacade(
        probe_error=AuthError(
            "invalid api key: received rejected credential, expected valid CURSOR_API_KEY"
        ),
    )

    with pytest.raises(AuthError):
        await facade.probe_api_key()

    assert facade.aclose_call_count >= 1


@pytest.mark.asyncio
async def test_fake_list_models_aclose_called_on_auth_error_path() -> None:
    """Ephemeral list_models lifecycle calls aclose even when AuthError is raised."""
    facade = FakeSdkFacade(
        list_models_error=AuthError(
            "models list unauthorized: received 401, expected authenticated catalog"
        ),
    )

    with pytest.raises(AuthError):
        await facade.list_models()

    assert facade.aclose_call_count >= 1


@pytest.mark.asyncio
async def test_module_list_models_aclose_called_on_error_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Module-level list_models still awaits client.aclose() when the call fails."""
    from cursor_agent.sdk_facade import list_models  # noqa: PLC0415

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
