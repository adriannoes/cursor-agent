"""Unit tests for cron jobs.yaml persistence hardening (PRD-010, review)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cursor_agent.config.loader import CursorAgentConfig, load_config
from cursor_agent.cron.store import (
    add_cron_job_atomic,
    build_cron_job,
    remove_cron_job_atomic,
    write_cron_jobs_atomic,
)
from cursor_agent.errors import ConfigError


def _config(tmp_path: Path) -> CursorAgentConfig:
    """Minimal config rooted at tmp_path."""
    return load_config(config_path=tmp_path / "missing.yaml")


def _cron_root(tmp_path: Path) -> Path:
    """Injectable cron config directory."""
    root = tmp_path / "cron"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _job(job_id: str = "daily-report") -> object:
    """Build a valid cron job via the CLI builder."""
    return build_cron_job(
        job_id=job_id,
        schedule="0 9 * * *",
        prompt="Generate the daily report.",
    )


def test_build_cron_job_rejects_blank_prompt(tmp_path: Path) -> None:
    """build_cron_job rejects a whitespace-only prompt with a clear error."""
    with pytest.raises(ConfigError, match="prompt"):
        build_cron_job(job_id="blank", schedule="0 9 * * *", prompt="   ")


def test_add_duplicate_job_id_is_rejected(tmp_path: Path) -> None:
    """Adding an existing case-sensitive id raises a clear ConfigError."""
    config = _config(tmp_path)
    root = _cron_root(tmp_path)
    add_cron_job_atomic(config, root, _job())  # type: ignore[arg-type]
    with pytest.raises(ConfigError, match="already exists"):
        add_cron_job_atomic(config, root, _job())  # type: ignore[arg-type]


def test_remove_missing_job_id_is_rejected(tmp_path: Path) -> None:
    """Removing an unknown id raises a clear ConfigError."""
    config = _config(tmp_path)
    root = _cron_root(tmp_path)
    with pytest.raises(ConfigError, match="not found"):
        remove_cron_job_atomic(config, root, "ghost")  # type: ignore[arg-type]


def test_write_rejects_symlinked_jobs_file(tmp_path: Path) -> None:
    """Atomic write refuses to follow a symlinked jobs.yaml escaping the root."""
    root = _cron_root(tmp_path)
    outside = tmp_path / "outside.yaml"
    outside.write_text("jobs: []\n", encoding="utf-8")
    (root / "jobs.yaml").symlink_to(outside)
    with pytest.raises(ConfigError, match="symlink|escape|contained"):
        write_cron_jobs_atomic(root, [_job()])  # type: ignore[list-item]


@pytest.mark.asyncio
async def test_concurrent_adds_do_not_lose_updates(tmp_path: Path) -> None:
    """Two concurrent cron adds serialize via the write lock without lost writes."""
    config = _config(tmp_path)
    root = _cron_root(tmp_path)

    async def _add(job_id: str) -> None:
        await asyncio.to_thread(add_cron_job_atomic, config, root, _job(job_id))

    await asyncio.gather(_add("job-a"), _add("job-b"))

    from cursor_agent.cron import cron_jobs_from_config

    catalog = cron_jobs_from_config(config, override_cron_root=root)
    ids = sorted(job.id for job in catalog.list_jobs())
    assert ids == ["job-a", "job-b"]
