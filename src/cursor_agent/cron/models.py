"""Pydantic models for declarative cron job definitions (PRD-010, FR-2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Final, Literal

from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

CronRuntime = Literal["local", "cloud"]

CRON_PROMPT_MAX_BYTES: Final[int] = 64 * 1024
CRON_JOBS_FILE_MAX_BYTES: Final[int] = 512 * 1024
MIN_SCHEDULE_INTERVAL_SECONDS: Final[int] = 60
JOBS_FILENAME: Final[str] = "jobs.yaml"


class CronTelegramDelivery(BaseModel):
    """Optional Telegram destination for cron job output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: str = Field(min_length=1)


class CronJobDelivery(BaseModel):
    """Delivery channels configured for a cron job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    telegram: CronTelegramDelivery | None = None


class CronJobMetadataBase(BaseModel):
    """Shared cron job metadata fields and validators for list and execute views."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    schedule: str = Field(min_length=1)
    runtime: CronRuntime = "local"
    delivery: CronJobDelivery | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = f"invalid job id: received {value!r}, expected non-empty string"
            raise ValueError(msg)
        if stripped != value:
            msg = (
                f"invalid job id: received {value!r}, expected id without leading "
                "or trailing whitespace"
            )
            raise ValueError(msg)
        return value

    @field_validator("schedule")
    @classmethod
    def _validate_schedule(cls, value: str) -> str:
        return validate_cron_schedule(value)


class CronJob(CronJobMetadataBase):
    """Validated cron job entry from ``jobs.yaml``.

    Example:
        >>> CronJob.model_validate(
        ...     {
        ...         "id": "daily-report",
        ...         "schedule": "0 9 * * *",
        ...         "prompt": "Summarize open tasks.",
        ...     }
        ... )
    """

    prompt: str

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, value: str, info: ValidationInfo) -> str:
        job_id = info.data.get("id", "unknown")
        return validate_cron_prompt(value, job_id=str(job_id))


class CronJobSummary(CronJobMetadataBase):
    """Metadata-only cron job entry for list views (no prompt body).

    Example:
        >>> CronJobSummary.model_validate(
        ...     {
        ...         "id": "daily-report",
        ...         "schedule": "0 9 * * *",
        ...     }
        ... )
    """


def validate_cron_schedule(schedule: str) -> str:
    """Parse and enforce the minimum one-minute firing interval for ``schedule``.

    Args:
        schedule: Five- or six-field cron expression understood by APScheduler.

    Returns:
        The trimmed schedule string.

    Raises:
        ValueError: Expression is invalid or fires more often than once per minute.
    """
    trimmed = schedule.strip()
    if not trimmed:
        msg = f"invalid schedule: received {schedule!r}, expected non-empty cron expression"
        raise ValueError(msg)

    parts = trimmed.split()
    try:
        trigger = _cron_trigger_from_expression(trimmed, parts)
    except ValueError as exc:
        msg = (
            f"invalid schedule: received {schedule!r}, expected valid APScheduler "
            f"cron expression ({exc})"
        )
        raise ValueError(msg) from exc

    base = datetime.now(timezone.utc)
    first_fire = trigger.get_next_fire_time(None, base)
    if first_fire is None:
        msg = f"invalid schedule: received {schedule!r}, expected expression that fires"
        raise ValueError(msg)

    second_fire = trigger.get_next_fire_time(first_fire, first_fire)
    if second_fire is not None:
        interval_seconds = (second_fire - first_fire).total_seconds()
        if interval_seconds < MIN_SCHEDULE_INTERVAL_SECONDS:
            msg = (
                f"invalid schedule: received {schedule!r}, fires every "
                f"{interval_seconds} seconds, expected at least "
                f"{MIN_SCHEDULE_INTERVAL_SECONDS} seconds between runs"
            )
            raise ValueError(msg)
    return trimmed


def validate_cron_prompt(prompt: str, *, job_id: str) -> str:
    """Reject prompt bodies larger than ``CRON_PROMPT_MAX_BYTES``.

    Args:
        prompt: Job prompt text from ``jobs.yaml``.
        job_id: Job identifier for error messages.

    Returns:
        The prompt unchanged when within the size cap.

    Raises:
        ValueError: Prompt exceeds the MVP byte cap.
    """
    if not prompt.strip():
        msg = (
            f"invalid prompt for job {job_id!r}: received {prompt!r}, "
            "expected non-empty prompt text"
        )
        raise ValueError(msg)
    return _validate_cron_prompt_size(prompt, job_id=job_id)


def _validate_cron_prompt_size(prompt: str, *, job_id: str) -> str:
    """Reject prompt bodies larger than ``CRON_PROMPT_MAX_BYTES`` (size only)."""
    prompt_bytes = len(prompt.encode("utf-8"))
    if prompt_bytes > CRON_PROMPT_MAX_BYTES:
        msg = (
            f"invalid prompt for job {job_id!r}: size {prompt_bytes} bytes exceeds "
            f"maximum {CRON_PROMPT_MAX_BYTES} bytes (64 KiB)"
        )
        raise ValueError(msg)
    return prompt


def cron_trigger_for_schedule(schedule: str) -> CronTrigger:
    """Build a UTC ``CronTrigger`` for a validated schedule expression."""
    parts = schedule.split()
    return _cron_trigger_from_expression(schedule, parts)


def _cron_trigger_from_expression(schedule: str, parts: list[str]) -> CronTrigger:
    """Build an APScheduler cron trigger from a cron expression."""
    if len(parts) == 5:
        return CronTrigger.from_crontab(schedule, timezone=timezone.utc)
    if len(parts) == 6:
        second, minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            second=second,
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=timezone.utc,
        )
    msg = (
        f"invalid schedule {schedule!r}: expected 5 or 6 cron fields, "
        f"received {len(parts)}"
    )
    raise ValueError(msg)
