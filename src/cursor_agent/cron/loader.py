"""Load and validate ``~/.cursor-agent/cron/jobs.yaml`` (PRD-010, FR-2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.cron.models import (
    CRON_JOBS_FILE_MAX_BYTES,
    JOBS_FILENAME,
    CronJob,
    validate_cron_prompt,
)
from cursor_agent.errors import ConfigError
from cursor_agent.utf8_io import read_utf8_file_tail

_DEFAULT_CRON_ROOT = Path.home() / ".cursor-agent" / "cron"


@dataclass(frozen=True, slots=True)
class CronJobsCatalog:
    """Indexed cron jobs loaded from disk.

    Example:
        >>> catalog = CronJobsCatalog(())
        >>> catalog.list_jobs()
        []
    """

    _jobs: tuple[CronJob, ...]

    def list_jobs(self) -> list[CronJob]:
        """Return jobs in file order."""
        return list(self._jobs)

    def get_job(self, job_id: str) -> CronJob | None:
        """Return the case-sensitive job entry for ``job_id``, if present."""
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None


def cron_jobs_from_config(
    config: CursorAgentConfig,
    *,
    override_cron_root: Path | None = None,
    include_prompt: bool = True,
) -> CronJobsCatalog:
    """Load cron jobs from config with optional test/runtime overrides.

    Jobs are read from ``{cron_root}/jobs.yaml``. Missing or empty files yield an
    empty catalog. ``override_cron_root`` wins for hermetic tests; otherwise the
    default ``~/.cursor-agent/cron`` directory applies.

    When ``include_prompt`` is ``False``, metadata listing omits prompt bodies and
    skips prompt size validation — mirroring PRD-009 ``include_content=False``.

    Example:
        >>> from cursor_agent.config.loader import load_config
        >>> catalog = cron_jobs_from_config(load_config())
    """
    _ = config
    cron_root = (
        override_cron_root if override_cron_root is not None else _DEFAULT_CRON_ROOT
    )
    jobs_path = _resolve_jobs_file_path(cron_root)
    if jobs_path is None:
        return CronJobsCatalog(())

    raw_yaml = _read_bounded_jobs_yaml(jobs_path)
    if not raw_yaml.strip():
        return CronJobsCatalog(())

    parsed = _parse_jobs_yaml(raw_yaml, jobs_path=jobs_path)
    jobs = _validate_jobs(
        parsed,
        include_prompt=include_prompt,
        jobs_path=jobs_path,
    )
    return CronJobsCatalog(tuple(jobs))


def _resolve_jobs_file_path(cron_root: Path) -> Path | None:
    """Return ``jobs.yaml`` when present and contained by ``cron_root``."""
    jobs_path = cron_root / JOBS_FILENAME
    if not jobs_path.exists():
        return None
    if jobs_path.is_symlink():
        msg = (
            f"cron jobs file {jobs_path!s} must not be a symlink, "
            f"expected regular file contained under {cron_root!s}"
        )
        raise ConfigError(msg)
    try:
        resolved_root = cron_root.resolve(strict=False)
        resolved_jobs = jobs_path.resolve(strict=True)
    except OSError as exc:
        msg = (
            f"invalid cron jobs path: could not resolve {jobs_path!s} under "
            f"{cron_root!s}: {exc}"
        )
        raise ConfigError(msg) from exc
    if not resolved_jobs.is_relative_to(resolved_root):
        msg = (
            f"cron jobs file {jobs_path!s} escapes cron root {cron_root!s}, "
            "expected path contained under the configured cron directory"
        )
        raise ConfigError(msg)
    return jobs_path


def _read_bounded_jobs_yaml(jobs_path: Path) -> str:
    """Read ``jobs.yaml`` with a file-size cap and UTF-8 validation."""
    file_size = jobs_path.stat().st_size
    if file_size == 0:
        return ""
    if file_size > CRON_JOBS_FILE_MAX_BYTES:
        msg = (
            f"cron jobs file {jobs_path!s} exceeds maximum size "
            f"{CRON_JOBS_FILE_MAX_BYTES} bytes, received {file_size} bytes"
        )
        raise ConfigError(msg)
    try:
        text, _ = read_utf8_file_tail(jobs_path, file_size)
    except ValueError as exc:
        msg = (
            f"invalid UTF-8 in cron jobs file {jobs_path!s}: {exc}, "
            "expected valid UTF-8 YAML text"
        )
        raise ConfigError(msg) from exc
    return text


def _parse_jobs_yaml(raw_yaml: str, *, jobs_path: Path) -> list[dict[str, Any]]:
    """Parse the top-level ``jobs`` list without normalizing mapping keys."""
    try:
        loaded = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in cron jobs file {jobs_path!s}: {exc}"
        raise ConfigError(msg) from exc

    if loaded is None:
        return []
    if not isinstance(loaded, dict):
        msg = (
            f"invalid cron jobs YAML shape in {jobs_path!s}: expected top-level "
            f"mapping, received {type(loaded).__name__!r}"
        )
        raise ConfigError(msg)

    raw_jobs = loaded.get("jobs")
    if raw_jobs is None:
        return []
    if not isinstance(raw_jobs, list):
        msg = (
            f"invalid cron jobs YAML shape in {jobs_path!s}: expected ``jobs`` "
            f"list, received {type(raw_jobs).__name__!r}"
        )
        raise ConfigError(msg)
    if not all(isinstance(job, dict) for job in raw_jobs):
        msg = (
            f"invalid cron jobs YAML shape in {jobs_path!s}: expected each job to "
            "be a mapping"
        )
        raise ConfigError(msg)
    return raw_jobs


def _validate_jobs(
    raw_jobs: list[dict[str, Any]],
    *,
    include_prompt: bool,
    jobs_path: Path,
) -> list[CronJob]:
    """Validate job mappings and enforce case-sensitive unique ids."""
    jobs: list[CronJob] = []
    seen_ids: dict[str, int] = {}

    for index, raw_job in enumerate(raw_jobs):
        job_payload = dict(raw_job)
        job_id = job_payload.get("id")
        if isinstance(job_id, str) and include_prompt:
            prompt_value = job_payload.get("prompt")
            if isinstance(prompt_value, str):
                try:
                    validate_cron_prompt(prompt_value, job_id=job_id)
                except ValueError as exc:
                    raise ConfigError(str(exc)) from exc
        if not include_prompt:
            job_payload["prompt"] = ""

        try:
            job = CronJob.model_validate(job_payload)
        except ValidationError as exc:
            location = (
                f"job[{index}]" if not isinstance(job_id, str) else f"job {job_id!r}"
            )
            msg = (
                f"invalid cron job in {jobs_path!s} at {location}: "
                f"{_format_validation_error(exc)}"
            )
            raise ConfigError(msg) from exc

        if job.id in seen_ids:
            msg = (
                f"duplicate cron job id in {jobs_path!s}: received {job.id!r}, "
                "expected each job id to be unique (case-sensitive)"
            )
            raise ConfigError(msg)
        seen_ids[job.id] = index
        jobs.append(job)

    return jobs


def _format_validation_error(exc: ValidationError) -> str:
    """Flatten the first Pydantic validation error for operator-facing messages."""
    errors = exc.errors()
    if not errors:
        return str(exc)
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", "validation failed")
    if loc:
        return f"field {loc}: {message}"
    return str(message)
