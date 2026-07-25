"""CLI command: show current Cursor plan usage."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from cursor_agent.cli.exit_codes import exit_code_for_error
from cursor_agent.errors import CursorAgentError
from cursor_agent.usage import (
    fetch_current_period_usage,
    format_plan_usage,
    parse_plan_usage,
    resolve_usage_access_token,
)


def usage_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the parsed usage snapshot as JSON."),
    ] = False,
) -> None:
    """Show current Cursor plan usage (total / auto / API).

    Uses the undocumented dashboard endpoint with the OAuth access token
    from the official Cursor Agent CLI auth store (`agent login`), or
    ``CURSOR_AGENT_USAGE_TOKEN``. This package has no login command.
    """
    try:
        token = resolve_usage_access_token()
        payload = fetch_current_period_usage(token=token)
        usage = parse_plan_usage(payload)
    except CursorAgentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(exit_code_for_error(exc)) from exc
    if json_output:
        typer.echo(json.dumps(usage.to_dict(), indent=2))
        return
    typer.echo(format_plan_usage(usage))
