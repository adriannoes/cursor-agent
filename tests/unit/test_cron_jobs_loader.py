"""Unit tests for cron jobs.yaml schema and loader (PRD-010, FR-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.cron import (
    CRON_PROMPT_MAX_BYTES,
    CronJob,
    CronJobsCatalog,
    cron_jobs_from_config,
)
from cursor_agent.errors import ConfigError


def _load_cron_config(tmp_path: Path) -> CursorAgentConfig:
    """Build minimal config for cron loader tests."""
    return load_config(config_path=tmp_path / "missing.yaml")


def _cron_root(tmp_path: Path) -> Path:
    """Return injectable cron config directory under ``tmp_path``."""
    root = tmp_path / "cron"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_jobs_yaml(cron_root: Path, content: str) -> Path:
    """Write ``jobs.yaml`` under an injectable cron root."""
    jobs_path = cron_root / "jobs.yaml"
    jobs_path.write_text(content, encoding="utf-8")
    return jobs_path


def _write_jobs_bytes(cron_root: Path, payload: bytes) -> Path:
    """Write raw bytes to ``jobs.yaml`` for UTF-8 edge cases."""
    jobs_path = cron_root / "jobs.yaml"
    jobs_path.write_bytes(payload)
    return jobs_path


def _single_job_yaml(
    *,
    job_id: str = "daily-report",
    schedule: str = "0 9 * * *",
    prompt: str = "Generate the daily report.",
    runtime: str | None = None,
    chat_id: str | None = None,
) -> str:
    """Build a minimal valid single-job YAML document."""
    lines = [
        "jobs:",
        f"  - id: {job_id}",
        f'    schedule: "{schedule}"',
        f'    prompt: "{prompt}"',
    ]
    if runtime is not None:
        lines.append(f"    runtime: {runtime}")
    if chat_id is not None:
        lines.extend(
            [
                "    delivery:",
                "      telegram:",
                f'        chat_id: "{chat_id}"',
            ]
        )
    return "\n".join(lines) + "\n"


def _catalog_from_yaml(
    tmp_path: Path,
    yaml_content: str,
    *,
    include_prompt: bool = True,
) -> CronJobsCatalog:
    """Load cron jobs from injectable ``tmp_path/cron`` fixture."""
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root, yaml_content)
    return cron_jobs_from_config(
        _load_cron_config(tmp_path),
        override_cron_root=cron_root,
        include_prompt=include_prompt,
    )


def test_valid_single_job_loads(tmp_path: Path) -> None:
    """FR-2: a valid single job is parsed with defaults and delivery metadata."""
    catalog = _catalog_from_yaml(
        tmp_path,
        _single_job_yaml(chat_id="123456789", runtime="cloud"),
    )
    jobs = catalog.list_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "daily-report"
    assert job.schedule == "0 9 * * *"
    assert job.prompt == "Generate the daily report."
    assert job.runtime == "cloud"
    assert job.delivery is not None
    assert job.delivery.telegram is not None
    assert job.delivery.telegram.chat_id == "123456789"
    assert catalog.get_job("daily-report") == job


def test_multiple_jobs_load_in_file_order(tmp_path: Path) -> None:
    """FR-2: multiple jobs in one file are all returned preserving order."""
    yaml_content = (
        "jobs:\n"
        "  - id: alpha\n"
        '    schedule: "0 8 * * *"\n'
        '    prompt: "First job."\n'
        "  - id: beta\n"
        '    schedule: "30 14 * * 1"\n'
        '    prompt: "Second job."\n'
        "    runtime: cloud\n"
    )
    jobs = _catalog_from_yaml(tmp_path, yaml_content).list_jobs()

    assert [job.id for job in jobs] == ["alpha", "beta"]
    assert jobs[0].runtime == "local"
    assert jobs[1].runtime == "cloud"


def test_missing_jobs_file_returns_empty_catalog(tmp_path: Path) -> None:
    """Missing ``jobs.yaml`` yields an empty catalog without error."""
    cron_root = _cron_root(tmp_path)
    catalog = cron_jobs_from_config(
        _load_cron_config(tmp_path),
        override_cron_root=cron_root,
    )

    assert catalog.list_jobs() == []
    assert catalog.get_job("missing") is None


def test_empty_jobs_file_returns_empty_catalog(tmp_path: Path) -> None:
    """Whitespace-only ``jobs.yaml`` yields an empty catalog."""
    cron_root = _cron_root(tmp_path)
    _write_jobs_yaml(cron_root, "   \n")
    catalog = cron_jobs_from_config(
        _load_cron_config(tmp_path),
        override_cron_root=cron_root,
    )

    assert catalog.list_jobs() == []


def test_invalid_schedule_raises_config_error(tmp_path: Path) -> None:
    """Invalid cron expressions are rejected with schedule context."""
    with pytest.raises(ConfigError, match="schedule"):
        _catalog_from_yaml(
            tmp_path,
            _single_job_yaml(schedule="not-a-cron-expression"),
        )


def test_missing_required_field_raises_config_error(tmp_path: Path) -> None:
    """Jobs missing required fields cite the offending job and field."""
    yaml_content = 'jobs:\n  - id: incomplete\n    schedule: "0 9 * * *"\n'
    with pytest.raises(ConfigError, match="prompt"):
        _catalog_from_yaml(tmp_path, yaml_content)


def test_duplicate_job_ids_raise_config_error(tmp_path: Path) -> None:
    """Duplicate ``id`` values in one file are rejected."""
    yaml_content = (
        "jobs:\n"
        "  - id: dup\n"
        '    schedule: "0 9 * * *"\n'
        '    prompt: "First."\n'
        "  - id: dup\n"
        '    schedule: "0 10 * * *"\n'
        '    prompt: "Second."\n'
    )
    with pytest.raises(ConfigError, match="duplicate.*dup"):
        _catalog_from_yaml(tmp_path, yaml_content)


def test_job_ids_are_case_sensitive(tmp_path: Path) -> None:
    """``foo`` and ``Foo`` are distinct job ids."""
    yaml_content = (
        "jobs:\n"
        "  - id: foo\n"
        '    schedule: "0 9 * * *"\n'
        '    prompt: "lowercase."\n'
        "  - id: Foo\n"
        '    schedule: "0 10 * * *"\n'
        '    prompt: "capitalized."\n'
    )
    jobs = _catalog_from_yaml(tmp_path, yaml_content).list_jobs()

    assert [job.id for job in jobs] == ["foo", "Foo"]
    assert jobs[0].prompt == "lowercase."
    assert jobs[1].prompt == "capitalized."


def test_min_frequency_rejects_sub_minute_schedule(tmp_path: Path) -> None:
    """Schedules firing more often than once per minute are rejected."""
    with pytest.raises(ConfigError, match="minute|frequency|60"):
        _catalog_from_yaml(
            tmp_path,
            _single_job_yaml(schedule="* * * * * *"),
        )


def test_prompt_over_64_kib_raises_config_error(tmp_path: Path) -> None:
    """Prompt bodies larger than 64 KiB are rejected."""
    oversized_prompt = "x" * (CRON_PROMPT_MAX_BYTES + 1)
    with pytest.raises(ConfigError, match="prompt|64"):
        _catalog_from_yaml(
            tmp_path,
            _single_job_yaml(prompt=oversized_prompt),
        )


def test_malformed_yaml_raises_config_error(tmp_path: Path) -> None:
    """Malformed YAML syntax raises ConfigError."""
    with pytest.raises(ConfigError, match="YAML|yaml"):
        _catalog_from_yaml(tmp_path, "jobs:\n  - id: [unclosed\n")


def test_invalid_utf8_raises_config_error(tmp_path: Path) -> None:
    """Invalid UTF-8 bytes in ``jobs.yaml`` are rejected."""
    cron_root = _cron_root(tmp_path)
    _write_jobs_bytes(cron_root, b"jobs:\n  - id: bad\n\xff\xfe")
    with pytest.raises(ConfigError, match="UTF-8|utf-8"):
        cron_jobs_from_config(
            _load_cron_config(tmp_path),
            override_cron_root=cron_root,
        )


def test_jobs_yaml_symlink_outside_root_is_rejected(tmp_path: Path) -> None:
    """A symlinked ``jobs.yaml`` escaping the cron root is rejected."""
    cron_root = _cron_root(tmp_path)
    outside = tmp_path / "outside-jobs.yaml"
    outside.write_text(
        _single_job_yaml(job_id="leaked"),
        encoding="utf-8",
    )
    (cron_root / "jobs.yaml").symlink_to(outside)
    with pytest.raises(ConfigError, match="symlink|escape|contained"):
        cron_jobs_from_config(
            _load_cron_config(tmp_path),
            override_cron_root=cron_root,
        )


def test_metadata_listing_omits_prompt_when_include_prompt_false(
    tmp_path: Path,
) -> None:
    """``cron list`` can load metadata without validating oversized prompt bodies."""
    oversized_prompt = "p" * (CRON_PROMPT_MAX_BYTES + 1)
    yaml_content = (
        "jobs:\n"
        "  - id: metadata-only\n"
        '    schedule: "0 9 * * *"\n'
        f'    prompt: "{oversized_prompt}"\n'
        "    runtime: cloud\n"
        "    delivery:\n"
        "      telegram:\n"
        '        chat_id: "999"\n'
    )
    catalog = _catalog_from_yaml(tmp_path, yaml_content, include_prompt=False)
    jobs = catalog.list_jobs()

    assert len(jobs) == 1
    job = jobs[0]
    assert isinstance(job, CronJob)
    assert job.id == "metadata-only"
    assert job.schedule == "0 9 * * *"
    assert job.runtime == "cloud"
    assert job.delivery is not None
    assert job.delivery.telegram is not None
    assert job.delivery.telegram.chat_id == "999"
    assert job.prompt == ""
