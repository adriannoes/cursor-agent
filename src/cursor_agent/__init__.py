"""Minimal package scaffold for the PRD-000 SDK spike.

The real orchestration modules start in PRD-001; this package only gives the
ADR-026 quality gate a typed import target during Phase 0.
"""

from cursor_agent.sdk_facade import (
    AsyncSdkFacade,
    FakeSdkFacade,
    LogContext,
    RunResult,
    RunStatus,
    SdkFacade,
    StreamCallbacks,
)

__version__ = "0.0.0"

__all__ = [
    "AsyncSdkFacade",
    "FakeSdkFacade",
    "LogContext",
    "RunResult",
    "RunStatus",
    "SdkFacade",
    "StreamCallbacks",
    "__version__",
]
