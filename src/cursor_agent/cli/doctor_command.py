"""CLI ``doctor`` aggregate report (PRD-017 FR-2).

Sections (fixed order): Setup → Auth → Messaging hooks → Gateway.
Local by default; ``--probe`` opt-in forwards to FR-1 auth probes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from cursor_agent.auth_status import (
    AuthChannelReport,
    auth_status_to_json_dict,
    collect_auth_channel_report,
    exit_code_for_auth_status,
    format_auth_status_human,
)
from cursor_agent.cli.gateway_check import (
    GATEWAY_ABSENT_OK_LINE,
    collect_gateway_check_lines,
)
from cursor_agent.cli.setup_runtime import (
    collect_setup_check_lines,
    resolve_config_path,
    resolve_env_file,
)
from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.errors import ConfigError, CursorAgentError
from cursor_agent.gateway.config import (
    default_gateway_config_path,
    load_gateway_config,
)
from cursor_agent.messaging_hooks import (
    MessagingHooksStatusReport,
    messaging_hooks_status,
)


def _resolve_doctor_config(config_path: Path) -> CursorAgentConfig | None:
    """Load agent config after setup dotenv; return None on ConfigError."""
    try:
        return load_config(config_path=config_path)
    except CursorAgentError:
        return None


def _workspace_and_profile(
    config: CursorAgentConfig | None,
) -> tuple[Path, str]:
    """Return agent workspace cwd and tool_profile for hooks status fallback."""
    if config is None:
        return Path.cwd(), "coding"
    return Path(config.runtime.local.cwd), str(config.tool_profile)


def _hooks_workspace_and_profile(
    *,
    agent_config: CursorAgentConfig | None,
    gateway_path: Path,
) -> tuple[Path, str]:
    """Prefer gateway.yaml workspace/profile when that file is present.

    WHY: operators often keep a coding-profile agent config while running a
    messaging gateway. Hooks severity must follow the gateway perspective when
    ``--gateway-config`` (or the default path) points at an existing file, so
    incomplete messaging hooks are not reported as "not required".
    """
    agent_workspace, agent_profile = _workspace_and_profile(agent_config)
    resolved = gateway_path.expanduser()
    if not resolved.is_file():
        return agent_workspace, agent_profile
    try:
        gateway_config = load_gateway_config(resolved)
    except ConfigError:
        return agent_workspace, agent_profile
    return Path(gateway_config.workspace).expanduser(), str(gateway_config.tool_profile)


def _auth_human_lines(report: AuthChannelReport) -> list[str]:
    """Split FR-1 human formatter into individual lines."""
    return format_auth_status_human(report).splitlines()


def _collect_gateway_section(gateway_path: Path) -> tuple[list[str], bool]:
    """Absent path → ok absent; present → shared offline validate helper."""
    if not gateway_path.expanduser().is_file():
        return [GATEWAY_ABSENT_OK_LINE], False
    return collect_gateway_check_lines(gateway_path)


def _any_error_line(lines: list[str]) -> bool:
    """Return True when any line uses the greppable ``error:`` prefix."""
    return any(line.startswith("error:") for line in lines)


def _doctor_exit_code(
    *,
    setup_failed: bool,
    auth_report: AuthChannelReport,
    hooks_report: MessagingHooksStatusReport,
    gateway_failed: bool,
    all_lines: list[str],
) -> int:
    """Exit 1 on any error severity / ``error:`` line; warnings alone → 0."""
    if setup_failed:
        return 1
    if hooks_report.severity == "error":
        return 1
    if gateway_failed:
        return 1
    if exit_code_for_auth_status(auth_report) != 0:
        return 1
    if _any_error_line(all_lines):
        return 1
    return 0


def _doctor_json_payload(
    *,
    setup_lines: list[str],
    setup_failed: bool,
    auth_report: AuthChannelReport,
    hooks_report: MessagingHooksStatusReport,
    gateway_lines: list[str],
    gateway_failed: bool,
) -> dict[str, Any]:
    """Aggregate section payloads — never secrets or tokens (ADR-025)."""
    return {
        "setup": {"lines": setup_lines, "failed": setup_failed},
        "auth": auth_status_to_json_dict(auth_report),
        "messaging_hooks": {
            "severity": hooks_report.severity,
            "lines": hooks_report.lines,
            "complete": hooks_report.complete,
            "tool_profile": hooks_report.tool_profile,
        },
        "gateway": {"lines": gateway_lines, "failed": gateway_failed},
    }


def doctor_command(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Print the aggregate doctor report as JSON."),
    ] = False,
    gateway_config: Annotated[
        Path | None,
        typer.Option(
            "--gateway-config",
            help="Path to gateway YAML (default: ~/.cursor-agent/gateway.yaml).",
            dir_okay=False,
            file_okay=True,
            resolve_path=True,
        ),
    ] = None,
    probe: Annotated[
        bool,
        typer.Option(
            "--probe/--no-probe",
            help=(
                "Live-probe present credentials (default: off / local-only). "
                "--probe forwards to auth probes and may launch the SDK bridge."
            ),
        ),
    ] = False,
) -> None:
    """Aggregate setup, auth, messaging hooks, and gateway offline checks.

    Hooks status uses the gateway YAML workspace/profile when
    ``--gateway-config`` (or the default path) exists; otherwise it falls back
    to the agent config. Never prints API keys, OAuth tokens, or Telegram
    ``bot_token`` (ADR-025).
    """
    config_path = resolve_config_path(None)
    env_file = resolve_env_file(None)
    setup_lines, setup_failed = collect_setup_check_lines(
        config_path=config_path,
        env_file=env_file,
    )
    config = _resolve_doctor_config(config_path)

    auth_report = collect_auth_channel_report(probe=probe)
    auth_lines = _auth_human_lines(auth_report)

    gateway_path = (
        gateway_config if gateway_config is not None else default_gateway_config_path()
    )
    workspace, tool_profile = _hooks_workspace_and_profile(
        agent_config=config,
        gateway_path=gateway_path,
    )
    hooks_report = messaging_hooks_status(
        workspace=workspace,
        tool_profile=tool_profile,
    )
    gateway_lines, gateway_failed = _collect_gateway_section(gateway_path)

    all_lines = [
        *setup_lines,
        *auth_lines,
        *hooks_report.lines,
        *gateway_lines,
    ]
    exit_code = _doctor_exit_code(
        setup_failed=setup_failed,
        auth_report=auth_report,
        hooks_report=hooks_report,
        gateway_failed=gateway_failed,
        all_lines=all_lines,
    )

    if json_output:
        payload = _doctor_json_payload(
            setup_lines=setup_lines,
            setup_failed=setup_failed,
            auth_report=auth_report,
            hooks_report=hooks_report,
            gateway_lines=gateway_lines,
            gateway_failed=gateway_failed,
        )
        typer.echo(json.dumps(payload, indent=2))
    else:
        for line in all_lines:
            typer.echo(line)

    if exit_code != 0:
        raise typer.Exit(exit_code)
