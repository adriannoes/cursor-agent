"""Offline gateway YAML validation + ``gateway check`` CLI (PRD-017 FR-3).

``collect_gateway_check_lines`` is the pure shared core. Wave 2 ``doctor``
calls it when a gateway file is present; Wave 3 wraps it in
``gateway check`` on :data:`gateway_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from cursor_agent.errors import ConfigError
from cursor_agent.gateway.config import (
    default_gateway_config_path,
    enabled_platform_names,
    load_gateway_config,
    redact_gateway_secrets_in_text,
    resolve_gateway_startup_config,
)
from cursor_agent.platforms.factory import validate_telegram_bot_token

GATEWAY_ABSENT_OK_LINE = "ok: gateway.yaml — (absent)"

GatewayConfigPathOpt = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help="Path to gateway YAML configuration.",
        dir_okay=False,
        file_okay=True,
        resolve_path=True,
    ),
]

gateway_app = typer.Typer(
    invoke_without_command=True,
    help="Run or validate the messaging gateway.",
)


def collect_gateway_check_lines(config_path: Path) -> tuple[list[str], bool]:
    """Validate gateway YAML offline; never echo ``bot_token`` (ADR-025).

    Missing file → error line (FR-3). Doctor short-circuits absent paths to
    :data:`GATEWAY_ABSENT_OK_LINE` before calling this helper.

    Example::

        lines, failed = collect_gateway_check_lines(Path("~/.cursor-agent/gateway.yaml"))
    """
    path = config_path.expanduser()
    if not path.is_file():
        return (
            [f"error: gateway.yaml — received {str(path)!r}, expected existing file"],
            True,
        )

    try:
        gateway_config = load_gateway_config(path)
        resolve_gateway_startup_config(gateway_config)
        # WHY: load/resolve accept empty bot_token strings; startup factory does not.
        validate_telegram_bot_token(gateway_config)
    except ConfigError as exc:
        # Defense in depth: load_gateway_config already sanitizes; keep public API.
        safe_message = redact_gateway_secrets_in_text(str(exc))
        return ([f"error: gateway.yaml — {safe_message}"], True)

    lines: list[str] = [f"ok: gateway.yaml — {path}"]
    failed = False

    workspace = Path(gateway_config.workspace).expanduser()
    if workspace.is_dir():
        lines.append(f"ok: gateway workspace — {workspace}")
    else:
        lines.append(
            f"error: gateway workspace — received {str(workspace)!r}, "
            "expected existing directory"
        )
        failed = True

    lines.append(f"ok: gateway tool_profile — {gateway_config.tool_profile}")

    platforms = enabled_platform_names(gateway_config)
    if platforms:
        lines.append(f"ok: gateway platforms — {', '.join(platforms)}")
    else:
        lines.append("ok: gateway platforms — (none enabled)")

    return lines, failed


@gateway_app.command("check")
def gateway_check_command(config: GatewayConfigPathOpt = None) -> None:
    """Validate gateway YAML offline (no network / Telegram).

    Example::

        cursor-agent gateway check --config ~/.cursor-agent/gateway.yaml
    """
    path = default_gateway_config_path() if config is None else config
    lines, failed = collect_gateway_check_lines(path)
    for line in lines:
        typer.echo(line)
    if failed:
        raise typer.Exit(1)
