"""Gateway allowlist authorization."""

from __future__ import annotations

from collections.abc import Callable

from cursor_agent.gateway.config import GatewayConfig

_SUPPORTED_PLATFORMS: frozenset[str] = frozenset({"telegram"})


def normalize_sender_id(user_id: str | int) -> str:
    """Normalize platform sender ID to a canonical string for allowlist matching."""
    if isinstance(user_id, bool):
        raise TypeError(
            f"invalid sender_id type: received {type(user_id).__name__!r}, "
            "expected str or int",
        )
    if isinstance(user_id, int):
        return str(user_id)
    if isinstance(user_id, str):
        return user_id.strip()
    raise TypeError(
        f"invalid sender_id type: received {type(user_id).__name__!r}, "
        "expected str or int",
    )


def is_allowed_sender(
    platform: str,
    user_id: str | int,
    config: GatewayConfig,
) -> bool:
    """Return True when the sender is on the platform allowlist."""
    normalized_platform = platform.strip().lower()
    if normalized_platform not in _SUPPORTED_PLATFORMS:
        return False

    normalized_user_id = normalize_sender_id(user_id)
    if normalized_user_id == "":
        return False

    return _is_on_platform_allowlist(normalized_platform, normalized_user_id, config)


def blocked_sender_response_text() -> str | None:
    """Return outbound text for blocked senders; ``None`` means silent ignore."""
    return None


def _telegram_allowlist(config: GatewayConfig) -> set[str]:
    return {
        normalize_sender_id(entry) for entry in config.platforms.telegram.allowed_users
    }


_PLATFORM_ALLOWLIST_GETTERS: dict[str, Callable[[GatewayConfig], set[str]]] = {
    "telegram": _telegram_allowlist,
}


def _is_on_platform_allowlist(
    platform: str,
    normalized_user_id: str,
    config: GatewayConfig,
) -> bool:
    allowlist_getter = _PLATFORM_ALLOWLIST_GETTERS.get(platform)
    if allowlist_getter is None:
        return False
    return normalized_user_id in allowlist_getter(config)
