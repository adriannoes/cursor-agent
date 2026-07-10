"""Curated MCP server catalog for the ``full`` tool profile (ADR-029).

Builds flat dicts matching the Cursor ``mcp.json`` mental model: remote HTTP
(``url`` / ``headers``) for github by default, or stdio (``command`` / ``args`` /
``env``) for Docker github and other curated servers. No ``cursor_sdk`` import —
the facade may wrap these dicts into SDK types later.

Per-server emit lives on each catalog definition (TN-07): the build loop never
branches on ``server_id``; github HTTP vs Docker is strategy data.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

# Named constants keep allowlist config and policy grep-friendly (ADR-029 Q1).
MCP_SERVER_ID_GITHUB: Final[str] = "github"
MCP_SERVER_ID_BRAVE_SEARCH: Final[str] = "brave-search"
MCP_SERVER_ID_PLAYWRIGHT: Final[str] = "playwright"

GithubTransport = Literal["http", "stdio"]

_GITHUB_ENV_KEY: Final[str] = "GITHUB_PERSONAL_ACCESS_TOKEN"
_BRAVE_ENV_KEY: Final[str] = "BRAVE_API_KEY"
_GITHUB_HTTP_URL: Final[str] = "https://api.githubcopilot.com/mcp/"
# Public set shared with config loader validation (single source of truth).
ALLOWED_GITHUB_TRANSPORTS: Final[frozenset[str]] = frozenset({"http", "stdio"})


@dataclass(frozen=True, slots=True)
class _McpEmitContext:
    """Shared inputs for per-server emit strategies during a full-profile build."""

    environ: Mapping[str, str]
    github_transport: GithubTransport


@dataclass(frozen=True, slots=True)
class _CuratedMcpServerDefinition:
    """Internal catalog entry for one curated MCP server (stdio shape when used)."""

    server_id: str
    command: str
    args: tuple[str, ...]
    required_env_keys: tuple[str, ...]
    emit_strategy: Callable[
        [_CuratedMcpServerDefinition, _McpEmitContext], dict[str, Any]
    ]

    def emit(self, context: _McpEmitContext) -> dict[str, Any]:
        """Emit flat MCP config via this server's strategy.

        Example:
            servers[id] = definition.emit(emit_context)
        """
        return self.emit_strategy(self, context)


def _emit_stdio_strategy(
    definition: _CuratedMcpServerDefinition,
    context: _McpEmitContext,
) -> dict[str, Any]:
    """Default emit: flat stdio dict from definition + environ."""
    return _emit_stdio_server_config(definition, context.environ)


def _emit_github_strategy(
    definition: _CuratedMcpServerDefinition,
    context: _McpEmitContext,
) -> dict[str, Any]:
    """Github emit: HTTP remote or Docker stdio from transport strategy data."""
    return _emit_github_server_config(
        transport=context.github_transport,
        environ=context.environ,
        stdio_definition=definition,
    )


# Appendix A spike values — github stdio retained as explicit operator choice (Wave 5).
_CURATED_MCP_SERVER_DEFINITIONS: Final[dict[str, _CuratedMcpServerDefinition]] = {
    MCP_SERVER_ID_GITHUB: _CuratedMcpServerDefinition(
        server_id=MCP_SERVER_ID_GITHUB,
        command="docker",
        args=(
            "run",
            "-i",
            "--rm",
            "-e",
            _GITHUB_ENV_KEY,
            "ghcr.io/github/github-mcp-server",
        ),
        required_env_keys=(_GITHUB_ENV_KEY,),
        emit_strategy=_emit_github_strategy,
    ),
    MCP_SERVER_ID_BRAVE_SEARCH: _CuratedMcpServerDefinition(
        server_id=MCP_SERVER_ID_BRAVE_SEARCH,
        command="npx",
        args=("-y", "@brave/brave-search-mcp-server"),
        required_env_keys=(_BRAVE_ENV_KEY,),
        emit_strategy=_emit_stdio_strategy,
    ),
    MCP_SERVER_ID_PLAYWRIGHT: _CuratedMcpServerDefinition(
        server_id=MCP_SERVER_ID_PLAYWRIGHT,
        command="npx",
        args=("-y", "@playwright/mcp@latest"),
        required_env_keys=(),
        emit_strategy=_emit_stdio_strategy,
    ),
}

# Public allowlist set derived from catalog keys — load-time drift guard.
CURATED_MCP_SERVER_IDS: Final[frozenset[str]] = frozenset(
    _CURATED_MCP_SERVER_DEFINITIONS
)
if CURATED_MCP_SERVER_IDS != frozenset(
    {
        MCP_SERVER_ID_GITHUB,
        MCP_SERVER_ID_BRAVE_SEARCH,
        MCP_SERVER_ID_PLAYWRIGHT,
    }
):
    raise RuntimeError(
        "curated MCP catalog drift: CURATED_MCP_SERVER_IDS "
        f"{sorted(CURATED_MCP_SERVER_IDS)!r} does not match named constants "
        f"{[MCP_SERVER_ID_GITHUB, MCP_SERVER_ID_BRAVE_SEARCH, MCP_SERVER_ID_PLAYWRIGHT]!r}"
    )


def build_mcp_servers_for_full(
    *,
    allowlist: Sequence[str] | None,
    environ: Mapping[str, str],
    github_transport: GithubTransport | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build curated MCP server configs for ``tool_profile: full``.

    ``allowlist=None`` enables every curated id. Missing required env omits that
    server and appends a warning (Q2) — never hard-fails for optional MCP.
    Unknown ids raise ``ValueError`` with the received value and allowed set.
    ``github_transport`` defaults to official remote HTTP; ``stdio`` selects
    Docker (no silent Docker fallback).

    Example:
        >>> servers, warnings = build_mcp_servers_for_full(
        ...     allowlist=["playwright"],
        ...     environ={},
        ... )
        >>> sorted(servers)
        ['playwright']
        >>> warnings
        []

    Args:
        allowlist: Curated server ids to enable, or ``None`` for all curated.
        environ: Environment mapping used to interpolate required secrets.
        github_transport: ``http`` (default), ``stdio``, or ``None`` (= ``http``).

    Returns:
        A ``(servers, warnings)`` tuple. ``servers`` maps id → flat MCP dict;
        ``warnings`` lists omit reasons without secret token values.

    Raises:
        ValueError: When ``allowlist`` contains an unknown server id, or when
            ``github_transport`` is not ``http`` / ``stdio`` / ``None``.
    """
    resolved_transport = _resolve_github_transport(github_transport)
    resolved_ids = _resolve_allowlist(allowlist)
    emit_context = _McpEmitContext(
        environ=environ,
        github_transport=resolved_transport,
    )
    servers: dict[str, Any] = {}
    warnings: list[str] = []

    for server_id in resolved_ids:
        definition = _CURATED_MCP_SERVER_DEFINITIONS[server_id]
        missing_keys = _missing_required_env_keys(definition, environ)
        if missing_keys:
            warnings.append(_omit_warning_for_missing_env(server_id, missing_keys))
            continue
        servers[server_id] = definition.emit(emit_context)

    return servers, warnings


def _resolve_github_transport(
    github_transport: GithubTransport | None,
) -> GithubTransport:
    """Normalize github transport; unset defaults to http (never Docker)."""
    if github_transport is None:
        return "http"
    if github_transport not in ALLOWED_GITHUB_TRANSPORTS:
        allowed = ", ".join(sorted(ALLOWED_GITHUB_TRANSPORTS))
        raise ValueError(
            f"invalid github_transport: received {github_transport!r}, "
            f"expected one of {{{allowed}}}"
        )
    return github_transport


def _resolve_allowlist(allowlist: Sequence[str] | None) -> list[str]:
    """Return ordered curated ids for the allowlist, or all curated when None."""
    if allowlist is None:
        return sorted(CURATED_MCP_SERVER_IDS)

    resolved: list[str] = []
    seen: set[str] = set()
    for server_id in allowlist:
        if server_id not in CURATED_MCP_SERVER_IDS:
            allowed = ", ".join(sorted(CURATED_MCP_SERVER_IDS))
            raise ValueError(
                f"unknown MCP server id: received {server_id!r}, "
                f"expected one of {{{allowed}}}"
            )
        if server_id in seen:
            continue
        seen.add(server_id)
        resolved.append(server_id)
    return resolved


def _missing_required_env_keys(
    definition: _CuratedMcpServerDefinition,
    environ: Mapping[str, str],
) -> list[str]:
    """Return required env keys that are absent or empty in ``environ``."""
    missing: list[str] = []
    for key in definition.required_env_keys:
        value = environ.get(key)
        # Whitespace-only is not a usable secret — omit+warn like empty (Q2).
        if value is None or value.strip() == "":
            missing.append(key)
    return missing


def _omit_warning_for_missing_env(server_id: str, missing_keys: Sequence[str]) -> str:
    """Build an omit warning that names env keys but never secret values."""
    keys = ", ".join(missing_keys)
    return (
        f"omitting MCP server {server_id!r}: missing required environment "
        f"variable(s) {keys} (set the variable name(s); values are never logged)"
    )


def _emit_github_server_config(
    *,
    transport: GithubTransport,
    environ: Mapping[str, str],
    stdio_definition: _CuratedMcpServerDefinition,
) -> dict[str, Any]:
    """Emit github HTTP remote or Docker stdio; never fall back silently."""
    if transport == "http":
        # Strip so .env trailing newlines never land in Authorization headers.
        pat = environ[_GITHUB_ENV_KEY].strip()
        return {
            "url": _GITHUB_HTTP_URL,
            "headers": {"Authorization": f"Bearer {pat}"},
        }
    return _emit_stdio_server_config(stdio_definition, environ)


def _emit_stdio_server_config(
    definition: _CuratedMcpServerDefinition,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Emit a flat stdio dict; interpolate required env from ``environ``.

    Strip secret values so ``.env`` trailing newlines match the HTTP Bearer path
    (Wave 5 review: HTTP vs stdio PAT asymmetry).
    """
    env: dict[str, str] = {
        key: environ[key].strip() for key in definition.required_env_keys
    }
    return {
        "command": definition.command,
        "args": list(definition.args),
        "env": env,
    }
