"""Unit tests for SDK wait-result → RunResult adapter (PRD-001 task 3.1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cursor_agent.sdk_facade import (
    RunResult,
    RunStatus,
    _extract_text_from_messages,
    _map_run_result,
)


def test_run_result_mapping_finished_status() -> None:
    """SDK status 'finished' maps to RunStatus.FINISHED."""
    wait_result = SimpleNamespace(
        id="run-abc",
        status="finished",
        result="done",
        duration_ms=120,
    )
    mapped = _map_run_result(wait_result, text="streamed")
    assert mapped == RunResult(
        run_id="run-abc",
        status=RunStatus.FINISHED,
        text="streamed",
        usage={"duration_ms": 120},
    )


def test_run_result_mapping_error_status() -> None:
    """Unknown terminal statuses map to RunStatus.ERROR."""
    wait_result = SimpleNamespace(id="run-err", status="failed", result=None)
    mapped = _map_run_result(wait_result, text=None)
    assert mapped.status is RunStatus.ERROR


def test_run_result_mapping_requires_run_id() -> None:
    """Adapter rejects wait results without a run identifier."""
    wait_result = SimpleNamespace(status="finished")
    with pytest.raises(ValueError, match="run_id"):
        _map_run_result(wait_result)


def test_extract_text_from_messages_concatenates_assistant_deltas() -> None:
    """Assistant message blocks are concatenated in order."""
    messages = [
        SimpleNamespace(
            type="assistant",
            message=SimpleNamespace(
                content=[
                    SimpleNamespace(type="text", text="Hel"),
                    SimpleNamespace(type="text", text="lo"),
                ],
            ),
        ),
        SimpleNamespace(type="tool_call", name="grep"),
    ]
    assert _extract_text_from_messages(messages) == "Hello"
