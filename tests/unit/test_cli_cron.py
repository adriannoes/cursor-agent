"""Unit tests for CLI cron subcommands (PRD-010)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.config.loader import load_config
from cursor_agent.cron import cron_jobs_from_config


@pytest.fixture
def cron_root(tmp_path: Path) -> Path:
    """Injectable cron config directory under ``tmp_path``."""
    root = tmp_path / "cron"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def cron_cli_env(
    cron_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Point cron CLI commands at ``tmp_path/cron`` instead of operator home."""
    monkeypatch.setattr(
        "cursor_agent.cli.cron_commands.resolve_cron_root",
        lambda _config: cron_root,
    )
    return cron_root


def _load_jobs(cron_root: Path) -> list[str]:
    """Return job ids from injectable cron root via loader."""
    config = load_config(config_path=Path("/nonexistent/config.yaml"))
    catalog = cron_jobs_from_config(config, override_cron_root=cron_root)
    return [job.id for job in catalog.list_jobs()]


def test_cron_list_empty(cron_cli_env: Path) -> None:
    """cron list prints a friendly empty message when no jobs exist."""
    result = CliRunner().invoke(app, ["cron", "list"])
    assert result.exit_code == 0
    assert "No cron jobs configured" in result.stdout


def test_cron_add_persists_job_with_flags(cron_cli_env: Path) -> None:
    """cron add writes a validated job to injectable jobs.yaml using flags."""
    result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "daily-report",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            "Generate the daily report.",
            "--runtime",
            "cloud",
            "--chat-id",
            "123456789",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (cron_cli_env / "jobs.yaml").is_file()
    assert _load_jobs(cron_cli_env) == ["daily-report"]


def test_cron_list_renders_metadata_without_prompt_body(cron_cli_env: Path) -> None:
    """cron list renders schedule and delivery metadata without the prompt body."""
    secret_prompt = "Do not leak this prompt in cron list output."
    add_result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "daily-report",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            secret_prompt,
            "--runtime",
            "cloud",
            "--chat-id",
            "123456789",
        ],
    )
    assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["cron", "list"])

    assert result.exit_code == 0
    assert "daily-report" in result.stdout
    assert "0 9 * * *" in result.stdout
    assert "cloud" in result.stdout
    assert "123456789" in result.stdout
    assert secret_prompt not in result.stdout


def test_cron_list_shows_added_job(cron_cli_env: Path) -> None:
    """cron list renders metadata for a persisted job."""
    add_result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "daily-report",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            "Generate the daily report.",
            "--runtime",
            "cloud",
            "--chat-id",
            "123456789",
        ],
    )
    assert add_result.exit_code == 0, add_result.stdout

    result = CliRunner().invoke(app, ["cron", "list"])
    assert result.exit_code == 0
    assert "daily-report" in result.stdout
    assert "0 9 * * *" in result.stdout
    assert "cloud" in result.stdout
    assert "123456789" in result.stdout


def test_cron_remove_deletes_job(cron_cli_env: Path) -> None:
    """cron remove deletes the job from jobs.yaml."""
    add_result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "daily-report",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            "Generate the daily report.",
        ],
    )
    assert add_result.exit_code == 0, add_result.stdout

    remove_result = CliRunner().invoke(app, ["cron", "remove", "daily-report"])
    assert remove_result.exit_code == 0, remove_result.stdout
    assert _load_jobs(cron_cli_env) == []

    list_result = CliRunner().invoke(app, ["cron", "list"])
    assert list_result.exit_code == 0
    assert "No cron jobs configured" in list_result.stdout


def test_cron_add_invalid_schedule_cites_field_name(cron_cli_env: Path) -> None:
    """Invalid cron add flags surface the offending field in the error message."""
    result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "fast-job",
            "--schedule",
            "* * * * * *",
            "--prompt",
            "Runs too frequently.",
        ],
    )
    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "schedule" in combined.lower()


def _add_daily_report(prompt: str = "Generate the daily report.") -> None:
    """Add a baseline cron job through the CLI for show/error tests."""
    result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "daily-report",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            prompt,
            "--runtime",
            "cloud",
            "--chat-id",
            "123456789",
        ],
    )
    assert result.exit_code == 0, result.stdout


def test_cron_show_displays_job_detail(cron_cli_env: Path) -> None:
    """cron show renders full metadata including the prompt body."""
    _add_daily_report(prompt="Audit the backlog.")

    result = CliRunner().invoke(app, ["cron", "show", "daily-report"])

    assert result.exit_code == 0, result.stdout
    assert "id: daily-report" in result.stdout
    assert "schedule: 0 9 * * *" in result.stdout
    assert "runtime: cloud" in result.stdout
    assert "telegram_chat_id: 123456789" in result.stdout
    assert "prompt: Audit the backlog." in result.stdout


def test_cron_show_unknown_id_exits_error(cron_cli_env: Path) -> None:
    """cron show for a missing id exits non-zero with a clear message."""
    result = CliRunner().invoke(app, ["cron", "show", "ghost"])

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "not found" in combined.lower()


def test_cron_add_duplicate_id_exits_error(cron_cli_env: Path) -> None:
    """A second add with the same id surfaces a duplicate error."""
    _add_daily_report()

    result = CliRunner().invoke(
        app,
        [
            "cron",
            "add",
            "daily-report",
            "--schedule",
            "0 9 * * *",
            "--prompt",
            "Another prompt.",
        ],
    )

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "already exists" in combined.lower()


def test_cron_remove_unknown_id_exits_error(cron_cli_env: Path) -> None:
    """Removing a missing id exits non-zero with a clear message."""
    result = CliRunner().invoke(app, ["cron", "remove", "ghost"])

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "not found" in combined.lower()


def test_cron_list_skips_invalid_job_with_warning(cron_cli_env: Path) -> None:
    """cron list warns and skips invalid jobs while listing healthy entries."""
    cron_cli_env.mkdir(parents=True, exist_ok=True)
    (cron_cli_env / "jobs.yaml").write_text(
        "jobs:\n"
        "  - id: healthy\n"
        '    schedule: "0 9 * * *"\n'
        '    prompt: "ok"\n'
        "  - id: broken\n"
        '    schedule: "bad"\n'
        '    prompt: "ignored"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["cron", "list"])

    assert result.exit_code == 0
    assert "healthy" in result.stdout
    assert "broken" not in result.stdout
    combined = f"{result.stdout}\n{result.stderr}"
    assert "warning:" in combined.lower()
    assert "broken" in combined.lower()


def test_cron_list_strict_fails_on_invalid_job(cron_cli_env: Path) -> None:
    """cron list --strict exits non-zero when any job entry is invalid."""
    cron_cli_env.mkdir(parents=True, exist_ok=True)
    (cron_cli_env / "jobs.yaml").write_text(
        'jobs:\n  - id: broken\n    schedule: "bad"\n    prompt: "x"\n',
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["cron", "list", "--strict"])

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "broken" in combined.lower()


def test_cron_list_corrupt_jobs_yaml_exits_error(cron_cli_env: Path) -> None:
    """A malformed jobs.yaml makes cron list exit non-zero without a traceback."""
    (cron_cli_env / "jobs.yaml").write_text(
        "jobs:\n  - id: [unclosed\n", encoding="utf-8"
    )

    result = CliRunner().invoke(app, ["cron", "list"])

    assert result.exit_code == 1
    combined = f"{result.stdout}\n{result.stderr}"
    assert "yaml" in combined.lower()


def test_cron_add_help_documents_prompt_limit() -> None:
    """CLI help documents the 64 KiB prompt cap for operators."""
    result = CliRunner().invoke(app, ["cron", "add", "--help"])

    assert result.exit_code == 0
    assert "64" in result.stdout
    assert "KiB" in result.stdout
