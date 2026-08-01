"""CLI ``models`` command: live Cursor model catalog (PRD-017 FR-5)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Annotated, Any

import typer

from cursor_agent.auth_status import API_KEY_ENV_VAR
from cursor_agent.cli.error_display import format_startup_error
from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.config.effective import REDACTION_TOKEN
from cursor_agent.errors import AuthError, CursorAgentError
from cursor_agent.first_party_models import recommended_agent_model_ids
from cursor_agent.sdk_facade import MODELS_LIST_TIMEOUT_SECONDS, list_models
from cursor_agent.sdk_facade_models import ModelCatalogEntry

_DESCRIPTION_MAX_LEN: int = 120


def _resolve_models_api_key() -> str:
    """Return a non-empty ``CURSOR_API_KEY`` or raise ``AuthError``.

    Example:
        >>> # _resolve_models_api_key()  # doctest: +SKIP
    """
    raw = os.environ.get(API_KEY_ENV_VAR)
    if raw is None or not raw.strip():
        raise AuthError(
            f"missing {API_KEY_ENV_VAR}: received {raw!r}, "
            "expected non-empty API key string"
        )
    return raw.strip()


def _redact_api_key_in_text(message: str, *, api_key: str) -> str:
    """Replace a known API key substring so CLI errors never echo secrets (ADR-025).

    Example:
        >>> _redact_api_key_in_text("bad key sk-abc", api_key="sk-abc")
        'bad key ***'
    """
    if not api_key:
        return message
    return message.replace(api_key, REDACTION_TOKEN)


def _collapse_description_whitespace(description: str) -> str:
    """Collapse embedded newlines/whitespace so human rows stay single-line."""
    return " ".join(description.split())


def _truncate_description(description: str) -> str:
    """Truncate a long model description for human one-line display."""
    collapsed = _collapse_description_whitespace(description)
    if len(collapsed) <= _DESCRIPTION_MAX_LEN:
        return collapsed
    return collapsed[: _DESCRIPTION_MAX_LEN - 1] + "…"


def _format_models_human_line(
    entry: ModelCatalogEntry,
    *,
    recommended: bool,
) -> str:
    """Format one catalog row for human stdout (id + display_name + marker)."""
    marker = " (recommended)" if recommended else ""
    line = f"{entry.id}  {entry.display_name}{marker}"
    if entry.description:
        line = f"{line}  — {_truncate_description(entry.description)}"
    return line


def _models_row_json_dict(
    entry: ModelCatalogEntry,
    *,
    recommended: bool,
) -> dict[str, Any]:
    """Build one ``--json`` object (no parameter schema fields)."""
    return {
        "id": entry.id,
        "display_name": entry.display_name,
        "description": entry.description,
        "recommended": recommended,
    }


def _echo_models_cli_error(exc: CursorAgentError, *, api_key: str | None) -> None:
    """Print a domain error; redact the resolved API key when present (ADR-025)."""
    rendered = format_startup_error(exc)
    if api_key is not None:
        rendered = _redact_api_key_in_text(rendered, api_key=api_key)
    typer.echo(rendered, err=True)


def models_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the live model catalog as JSON."),
    ] = False,
) -> None:
    """List live Cursor models available to the configured API key.

    Soft-catalog ids from ``recommended_agent_model_ids()`` are marked
    ``(recommended)`` in human output and ``recommended: true`` in JSON.

    Example:
        ``cursor-agent models``
        ``cursor-agent models --json``
    """
    api_key: str | None = None
    try:
        api_key = _resolve_models_api_key()
        catalog = asyncio.run(
            list_models(
                api_key=api_key,
                timeout_seconds=MODELS_LIST_TIMEOUT_SECONDS,
            )
        )
    except CursorAgentError as exc:
        # WHY: redact before exit; from None so a traceback cannot re-surface
        # the original AuthError/ConfigError text that may embed the raw key
        # (ADR-025; same posture as gateway redaction follow-up).
        exit_code = exit_code_for_error(exc)
        _echo_models_cli_error(exc, api_key=api_key)
        raise typer.Exit(exit_code) from None

    recommended_ids = frozenset(recommended_agent_model_ids())
    if json_output:
        payload = [
            _models_row_json_dict(entry, recommended=entry.id in recommended_ids)
            for entry in catalog
        ]
        typer.echo(json.dumps(payload, indent=2))
        return

    for entry in catalog:
        typer.echo(
            _format_models_human_line(
                entry,
                recommended=entry.id in recommended_ids,
            )
        )
