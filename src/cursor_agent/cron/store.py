"""Atomic persistence for declarative cron jobs (PRD-010, FR-5, FR-6)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.cron.loader import CronJobsCatalog, cron_jobs_from_config
from cursor_agent.cron.models import (
    JOBS_FILENAME,
    CronJob,
    CronJobDelivery,
    CronTelegramDelivery,
)
from cursor_agent.errors import ConfigError

_DEFAULT_CRON_ROOT = Path.home() / ".cursor-agent" / "cron"


def default_cron_root() -> Path:
    """Return the operator cron config directory."""
    return _DEFAULT_CRON_ROOT


def load_cron_jobs_catalog(
    config: CursorAgentConfig,
    cron_root: Path,
    *,
    include_prompt: bool = True,
) -> CronJobsCatalog:
    """Load cron jobs from an injectable cron root."""
    return cron_jobs_from_config(
        config,
        override_cron_root=cron_root,
        include_prompt=include_prompt,
    )


def build_cron_job(
    *,
    job_id: str,
    schedule: str,
    prompt: str,
    runtime: str = "local",
    chat_id: str | None = None,
) -> CronJob:
    """Validate CLI flag values and return a ``CronJob`` instance.

    Raises:
        ConfigError: Validation failed; message cites job id and field name.
    """
    delivery: CronJobDelivery | None = None
    if chat_id is not None:
        delivery = CronJobDelivery(telegram=CronTelegramDelivery(chat_id=chat_id))

    payload: dict[str, object] = {
        "id": job_id,
        "schedule": schedule,
        "prompt": prompt,
        "runtime": runtime,
    }
    if delivery is not None:
        payload["delivery"] = delivery.model_dump()

    try:
        return CronJob.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        msg = _format_job_validation_error(job_id=job_id, exc=exc)
        raise ConfigError(msg) from exc


def add_cron_job_atomic(
    config: CursorAgentConfig,
    cron_root: Path,
    job: CronJob,
) -> None:
    """Append a validated job to ``jobs.yaml`` with an atomic replace write."""
    catalog = load_cron_jobs_catalog(config, cron_root, include_prompt=True)
    existing = catalog.list_jobs()
    if catalog.get_job(job.id) is not None:
        msg = (
            f"cron job id already exists: received {job.id!r}, "
            "expected a unique case-sensitive job id"
        )
        raise ConfigError(msg)
    write_cron_jobs_atomic(cron_root, [*existing, job])


def remove_cron_job_atomic(
    config: CursorAgentConfig,
    cron_root: Path,
    job_id: str,
) -> None:
    """Remove a job by id from ``jobs.yaml`` with an atomic replace write."""
    catalog = load_cron_jobs_catalog(config, cron_root, include_prompt=True)
    existing = catalog.list_jobs()
    if catalog.get_job(job_id) is None:
        msg = (
            f"cron job not found: received id {job_id!r}, "
            "expected an existing case-sensitive job id"
        )
        raise ConfigError(msg)
    remaining = [job for job in existing if job.id != job_id]
    write_cron_jobs_atomic(cron_root, remaining)


def write_cron_jobs_atomic(cron_root: Path, jobs: list[CronJob]) -> None:
    """Serialize validated jobs and atomically replace ``jobs.yaml``."""
    cron_root.mkdir(parents=True, exist_ok=True)
    jobs_path = cron_root / JOBS_FILENAME
    payload = {"jobs": [_job_to_yaml_mapping(job) for job in jobs]}
    serialized = yaml.safe_dump(
        payload,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )

    fd, temp_path_str = tempfile.mkstemp(
        prefix=f".{JOBS_FILENAME}.",
        suffix=".tmp",
        dir=cron_root,
    )
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, jobs_path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        msg = (
            f"failed to write cron jobs file {jobs_path!s}: {exc}, "
            "expected atomic replace under the configured cron directory"
        )
        raise ConfigError(msg) from exc


def _job_to_yaml_mapping(job: CronJob) -> dict[str, object]:
    """Convert a validated job into a YAML-friendly mapping."""
    mapping = job.model_dump(mode="python", exclude_none=True)
    runtime = mapping.pop("runtime", "local")
    if runtime != "local":
        mapping["runtime"] = runtime
    return mapping


def _format_job_validation_error(*, job_id: str, exc: Exception) -> str:
    """Flatten validation failures for CLI operators."""
    if isinstance(exc, ValidationError):
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(part) for part in first.get("loc", ()))
            message = first.get("msg", "validation failed")
            if loc:
                return (
                    f"invalid cron job {job_id!r}: field {loc}: {message}, "
                    f"received offending value from CLI flags"
                )
    if isinstance(exc, ValueError):
        text = str(exc)
        if job_id in text:
            return text
        return f"invalid cron job {job_id!r}: {text}"
    return f"invalid cron job {job_id!r}: {exc}"
