"""cursor-agent — clean-room orchestration for the Cursor Python SDK.

Delegates the agentic loop, tools, and inference to the SDK; adds sessions,
configuration, CLI UX, concurrency, and security policy (hooks, tool profiles).
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

__version__ = "1.0.0"

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
