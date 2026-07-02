"""Shared fakes for slash command handler unit tests."""

from __future__ import annotations

import json
import logging
from typing import Any

from cursor_agent.errors import InvalidAgentError
from cursor_agent.sdk_facade import FakeSdkFacade, RunResult, RunStatus, StreamCallbacks
from cursor_agent.sessions.store import SessionStore

_SUMMARY_REPLY = """\
## Goal
Ship /compress saga with rollback.

## Decisions made
- Use FakeSdkFacade in unit tests.

## Current state
SessionStore.update_agent_id exists.

## Open questions
None.

## Next steps
1. Wire handler in slash_commands.
"""


class SendCapturingFacade(FakeSdkFacade):
    """FakeSdkFacade that records outgoing messages passed to send()."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.captured_send_messages: list[str] = []

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Record the composed outgoing message before delegating."""
        self.captured_send_messages.append(message)
        return await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,  # type: ignore[arg-type]
        )


class CancelTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records cancel invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.cancel_calls: list[str] = []

    async def cancel(self, agent_id: str) -> None:
        """Record cancel parameters and delegate to the parent fake."""
        self.cancel_calls.append(agent_id)
        await super().cancel(agent_id)


class ResumeTrackingFacade(FakeSdkFacade):
    """FakeSdkFacade that records resume_agent invocations."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.resume_calls: list[dict[str, Any]] = []

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
        runtime_mode: str = "local",
    ) -> str:
        """Record resume parameters and delegate to the parent fake."""
        self.resume_calls.append(
            {
                "agent_id": agent_id,
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
                "runtime_mode": runtime_mode,
            }
        )
        return await super().resume_agent(
            agent_id,
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )


class UsageReportingFacade(FakeSdkFacade):
    """FakeSdkFacade that attaches usage data to every send result."""

    def __init__(self, *, usage: dict[str, Any], **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._usage = usage

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Return a finished run with scripted usage metadata."""
        _ = log_context
        result = await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,  # type: ignore[arg-type]
        )
        return RunResult(
            run_id=result.run_id,
            status=result.status,
            text=result.text,
            usage=self._usage,
        )


class _ListLogHandler(logging.Handler):
    """Capture log records as raw message strings for NDJSON assertions."""

    def __init__(self, records: list[str]) -> None:
        super().__init__()
        self._records = records

    def emit(self, record: logging.LogRecord) -> None:
        self._records.append(record.getMessage())


def _capture_command_logs() -> tuple[logging.Logger, list[str]]:
    """Return a logger and list that collect NDJSON command log lines."""
    logger = logging.getLogger("test.commands.ndjson")
    records: list[str] = []
    handler = _ListLogHandler(records)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger, records


def _command_log_payloads(records: list[str]) -> list[dict[str, Any]]:
    """Parse NDJSON lines whose events are command_start or command_end."""
    payloads: list[dict[str, Any]] = []
    for line in records:
        payload = json.loads(line)
        if payload.get("event") in {"command_start", "command_end"}:
            payloads.append(payload)
    return payloads


class CancelErrorFacade(FakeSdkFacade):
    """FakeSdkFacade that raises InvalidAgentError on cancel."""

    async def cancel(self, agent_id: str) -> None:
        """Raise a domain error so command boundary logging can record failure."""
        raise InvalidAgentError(f"cancel failed for agent_id={agent_id!r}")


class ErrorReturningFacade(FakeSdkFacade):
    """FakeSdkFacade that returns RunStatus.ERROR on send."""

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Return an error terminal status without raising."""
        _ = agent_id, message, callbacks, log_context
        return RunResult(
            run_id="fake-run-error",
            status=RunStatus.ERROR,
            text="",
            usage=None,
        )


class _CompressSendSpyFacade(FakeSdkFacade):
    """FakeSdkFacade that records sends and can fail on the summary delivery step."""

    def __init__(
        self,
        *,
        fail_on_summary_delivery: bool = False,
        store: SessionStore | None = None,
        session_key: str | None = None,
        session_id: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.fail_on_summary_delivery = fail_on_summary_delivery
        self._status_store = store
        self._status_session_key = session_key
        self._status_session_id = session_id
        self.send_calls: list[dict[str, str]] = []
        self.create_agent_calls: list[dict[str, object]] = []
        self.cancel_calls: list[str] = []
        self.metadata_at_send: list[dict[str, object]] = []
        self._summary_generated = False

    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str:
        """Record create_agent and delegate to the parent fake."""
        self.create_agent_calls.append(
            {
                "workspace": workspace,
                "model": model,
                "tool_profile": tool_profile,
                "runtime_mode": runtime_mode,
            }
        )
        return await super().create_agent(
            workspace=workspace,
            model=model,
            tool_profile=tool_profile,
            runtime_mode=runtime_mode,
        )

    async def cancel(self, agent_id: str) -> None:
        """Record cancel invocations and delegate to the parent fake."""
        self.cancel_calls.append(agent_id)
        await super().cancel(agent_id)

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
        log_context: object | None = None,
    ) -> RunResult:
        """Record sends; optionally fail when delivering the summary to the new agent."""
        if (
            not self._summary_generated
            and self._status_store is not None
            and self._status_session_key is not None
            and self._status_session_id is not None
        ):
            row = await self._status_store.resolve(
                self._status_session_key,
                session_id=self._status_session_id,
            )
            assert row is not None
            assert row.metadata.get("status") == "compressing"
            self.metadata_at_send.append(dict(row.metadata))
        self.send_calls.append({"agent_id": agent_id, "message": message})
        if self.fail_on_summary_delivery and self._summary_generated:
            msg = (
                "simulated summary delivery failure: "
                f"agent_id={agent_id!r}, expected successful second send"
            )
            raise RuntimeError(msg)
        result = await super().send(
            agent_id,
            message,
            callbacks=callbacks,
            log_context=log_context,  # type: ignore[arg-type]
        )
        if not self._summary_generated:
            self._summary_generated = True
        return result

    def messages_for(self, agent_id: str) -> list[dict[str, str]]:
        """Return recorded user/assistant messages for an agent."""
        return list(self._messages_by_agent.get(agent_id, []))
