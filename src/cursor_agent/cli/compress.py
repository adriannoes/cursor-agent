"""Session context compression saga for /compress (PRD-004 / ADR-011)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cursor_agent.config.loader import CursorAgentConfig
from cursor_agent.errors import ConfigError
from cursor_agent.sdk_facade import RunStatus, SdkFacade
from cursor_agent.sessions.store import SessionStore

_COMPRESSING_STATUS = "compressing"
_METADATA_STATUS_KEY = "status"


@dataclass(frozen=True)
class CompressResult:
    """Outcome of a successful /compress saga."""

    session_id: str
    previous_agent_id: str
    new_agent_id: str


def _compress_prompt_paths() -> tuple[Path, ...]:
    """Return deterministic prompt locations (packaged first, then repo checkout)."""
    module_dir = Path(__file__).resolve().parent
    packaged = module_dir.parent / "prompts" / "compress.txt"
    checkout = module_dir.parents[2] / "docs" / "prompts" / "compress.txt"
    return (packaged, checkout)


def load_compress_prompt() -> str:
    """Load the versioned /compress summary prompt from a fixed project path.

    Example:
        >>> "## Goal" in load_compress_prompt()
        True
    """
    for path in _compress_prompt_paths():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                msg = (
                    f"compress prompt empty: received path={path!r}, "
                    "expected non-empty UTF-8 text"
                )
                raise ConfigError(msg)
            return text

    searched = ", ".join(str(path) for path in _compress_prompt_paths())
    msg = (
        f"compress prompt not found: searched [{searched}], "
        "expected docs/prompts/compress.txt in checkout or packaged prompts/"
    )
    raise ConfigError(msg)


async def _clear_compressing_status(
    store: SessionStore,
    session_key: str,
    session_id: str,
) -> None:
    """Remove ``metadata.status`` while preserving other metadata keys."""
    row = await store.resolve(session_key, session_id=session_id)
    if row is None:
        return
    cleaned = {
        key: value for key, value in row.metadata.items() if key != _METADATA_STATUS_KEY
    }
    await store.update_metadata(session_id, cleaned, merge=False)


async def _rollback_compress_state(
    store: SessionStore,
    session_key: str,
    session_id: str,
    previous_agent_id: str,
) -> None:
    """Restore prior agent id and clear compressing status after saga failure."""
    row = await store.resolve(session_key, session_id=session_id)
    if row is not None and row.agent_id != previous_agent_id:
        await store.update_agent_id(session_id, previous_agent_id)
    await _clear_compressing_status(store, session_key, session_id)


async def run_compress_session(
    *,
    store: SessionStore,
    facade: SdkFacade,
    config: CursorAgentConfig,
    session_key: str,
    session_id: str,
) -> CompressResult:
    """Run the /compress saga: summarize, swap agent_id on the same row, seed summary.

    On failure, restores the previous ``agent_id`` and clears ``metadata.status``.
    """
    if not session_id:
        msg = (
            f"invalid session_id: received {session_id!r}, "
            "expected non-empty active session id"
        )
        raise ConfigError(msg)

    row = await store.resolve(session_key, session_id=session_id)
    if row is None:
        msg = (
            f"session not found: received session_key={session_key!r}, "
            f"session_id={session_id!r}, expected existing session"
        )
        raise ConfigError(msg)

    previous_agent_id = row.agent_id
    prompt = load_compress_prompt()

    try:
        await store.update_metadata(
            session_id,
            {_METADATA_STATUS_KEY: _COMPRESSING_STATUS},
            merge=True,
        )

        await facade.resume_agent(
            previous_agent_id,
            workspace=row.workspace,
            model=config.model,
            tool_profile=row.tool_profile,
            runtime_mode=row.runtime,
        )

        summary_run = await facade.send(previous_agent_id, prompt)
        if summary_run.status is not RunStatus.FINISHED:
            msg = (
                f"compress summary failed: received status={summary_run.status!r}, "
                "expected RunStatus.FINISHED"
            )
            raise ConfigError(msg)

        summary = summary_run.text
        if not summary or not summary.strip():
            msg = (
                "compress summary empty: received no assistant text, "
                "expected non-empty summary from old agent"
            )
            raise ConfigError(msg)

        new_agent_id = await facade.create_agent(
            workspace=row.workspace,
            model=config.model,
            tool_profile=row.tool_profile,
            runtime_mode=row.runtime,
        )

        await store.update_agent_id(session_id, new_agent_id)

        await facade.resume_agent(
            new_agent_id,
            workspace=row.workspace,
            model=config.model,
            tool_profile=row.tool_profile,
            runtime_mode=row.runtime,
        )

        delivery_run = await facade.send(new_agent_id, summary)
        if delivery_run.status is not RunStatus.FINISHED:
            msg = (
                f"summary delivery failed: received status={delivery_run.status!r}, "
                "expected RunStatus.FINISHED"
            )
            raise ConfigError(msg)

        await _clear_compressing_status(store, session_key, session_id)

        return CompressResult(
            session_id=session_id,
            previous_agent_id=previous_agent_id,
            new_agent_id=new_agent_id,
        )
    except ConfigError:
        await _rollback_compress_state(
            store,
            session_key,
            session_id,
            previous_agent_id,
        )
        raise
    except Exception as exc:
        await _rollback_compress_state(
            store,
            session_key,
            session_id,
            previous_agent_id,
        )
        msg = f"compress saga failed: {exc}"
        raise ConfigError(msg) from exc
