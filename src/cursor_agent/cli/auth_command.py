"""CLI ``auth`` group: ``auth status`` (PRD-017 FR-1).

Q1 LOCKED: probes by default when a credential is locally present;
``--no-probe`` is the only offline path (zero ``probe_api_key`` / dashboard
fetch).
"""

from __future__ import annotations

import json
from typing import Annotated

import typer

from cursor_agent.auth_status import (
    auth_status_to_json_dict,
    collect_auth_channel_report,
    exit_code_for_auth_status,
    format_auth_status_human,
)

auth_app = typer.Typer(help="Inspect Cursor authentication channels.")


@auth_app.command("status")
def auth_status_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print channel status as JSON."),
    ] = False,
    probe: Annotated[
        bool,
        typer.Option(
            "--probe/--no-probe",
            help=(
                "Live-probe present credentials (default: on). "
                "--no-probe is local-only / offline."
            ),
        ),
    ] = True,
) -> None:
    """Show local (+ optional live) status for API key and usage OAuth.

    Never prints key/token values or ``me`` identity fields (ADR-025).
    """
    report = collect_auth_channel_report(probe=probe)
    if json_output:
        typer.echo(json.dumps(auth_status_to_json_dict(report), indent=2))
    else:
        typer.echo(format_auth_status_human(report))
    code = exit_code_for_auth_status(report)
    if code != 0:
        raise typer.Exit(code)
