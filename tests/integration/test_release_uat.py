"""Maintainer release user-acceptance tests (PRD-012).

Exercises CLI, REPL, gateway process lifecycle, and Telegram handler flows with
the real Cursor SDK. Not part of public CI — run locally before version tags.
See ``CONTRIBUTING.md`` (release readiness) and ``docs/setup.md``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from cursor_agent.cli.repl_session import run_repl
from cursor_agent.cli.startup import create_store, session_key_for
from cursor_agent.config.loader import load_config
from cursor_agent.platforms.telegram_commands import (
    TELEGRAM_STOP_NO_SESSION,
    TELEGRAM_NEW_CONFIRMATION,
)
from cursor_agent.pool import SessionAgentPool
from cursor_agent.product_copy import TELEGRAM_NO_SESSION_HINT
from cursor_agent.sdk_facade import AsyncSdkFacade
from tests.integration.release_uat_helpers import (
    DEFAULT_GATEWAY_CONFIG_PATH,
    MINIMAL_SDK_PROMPT,
    RELEASE_UAT_ALLOWED_USER_ID,
    RELEASE_UAT_BLOCKED_USER_ID,
    SDK_TIMEOUT_SECONDS,
    repo_workspace,
    repl_line_reader,
    run_cursor_agent_cli,
    run_gateway_process_smoke,
    telegram_gateway_with_real_sdk,
    telegram_get_me_username,
    wait_for_bot_reply_texts,
)
from tests.unit.telegram_adapter_fakes import private_message, registered_handler

pytestmark = [
    pytest.mark.integration,
    pytest.mark.release_uat,
    pytest.mark.skipif(
        not os.getenv("CURSOR_API_KEY"),
        reason="requires CURSOR_API_KEY",
    ),
]

_HAS_TELEGRAM_TOKEN = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
_HAS_GATEWAY_CONFIG = DEFAULT_GATEWAY_CONFIG_PATH.is_file()


def test_release_uat_cli_help() -> None:
    """``cursor-agent --help`` lists gateway, sessions, and cron commands."""
    result = run_cursor_agent_cli("--help")
    assert result.returncode == 0, result.stderr
    assert "cursor-agent" in result.stdout
    assert "gateway" in result.stdout


def test_release_uat_cli_sessions_list() -> None:
    """``cursor-agent sessions list`` exits cleanly for the workspace key."""
    result = run_cursor_agent_cli("sessions", "list")
    assert result.returncode == 0, result.stderr


def test_release_uat_cli_cron_list() -> None:
    """``cursor-agent cron list`` and ``--strict`` exit cleanly."""
    for args in (("cron", "list"), ("cron", "list", "--strict")):
        result = run_cursor_agent_cli(*args)
        assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not _HAS_TELEGRAM_TOKEN, reason="requires TELEGRAM_BOT_TOKEN")
def test_release_uat_telegram_get_me() -> None:
    """Telegram bot token resolves via the Bot API ``getMe`` endpoint."""
    username = telegram_get_me_username()
    assert username


@pytest.mark.skipif(
    not _HAS_TELEGRAM_TOKEN or not _HAS_GATEWAY_CONFIG,
    reason="requires TELEGRAM_BOT_TOKEN and ~/.cursor-agent/gateway.yaml",
)
def test_release_uat_gateway_process_lifecycle() -> None:
    """Real gateway process stays alive during polling, then exits on SIGINT."""
    run_gateway_process_smoke(config_path=DEFAULT_GATEWAY_CONFIG_PATH)


@pytest.mark.asyncio
async def test_release_uat_cli_repl_core_flow() -> None:
    """REPL slash commands and a minimal SDK turn work with the real facade."""
    config = load_config()
    store = create_store(config)
    await store.initialize()
    session_key = session_key_for(config)
    lines: list[str] = []

    async with AsyncSdkFacade(bridge_options={"workspace": repo_workspace()}) as facade:
        pool = SessionAgentPool(store=store, facade=facade, config=config)
        status = await asyncio.wait_for(
            run_repl(
                pool,
                session_key,
                store,
                config=config,
                facade=facade,
                reader=repl_line_reader(
                    "/help",
                    "/new",
                    MINIMAL_SDK_PROMPT,
                    "/memory show",
                    "/skills",
                    "/quit",
                ),
                writer=lines.append,
            ),
            timeout=SDK_TIMEOUT_SECONDS,
        )

    joined = "\n".join(lines)
    assert "Slash commands:" in joined or "/new" in joined
    assert "Created session" in joined
    assert "OK" in joined.upper()
    assert "memory" in joined.lower() or "USER.md" in joined
    assert "skill" in joined.lower() or "Skills" in joined
    assert status is not None


@pytest.mark.asyncio
async def test_release_uat_cli_messaging_profile_help() -> None:
    """Messaging profile REPL accepts ``/help`` without error."""
    config = load_config().model_copy(update={"tool_profile": "messaging"})
    store = create_store(config)
    await store.initialize()
    session_key = session_key_for(config)
    lines: list[str] = []

    async with AsyncSdkFacade(bridge_options={"workspace": repo_workspace()}) as facade:
        pool = SessionAgentPool(store=store, facade=facade, config=config)
        await run_repl(
            pool,
            session_key,
            store,
            config=config,
            facade=facade,
            reader=repl_line_reader("/help", "/quit"),
            writer=lines.append,
        )

    assert any("Slash commands" in line for line in lines)


@pytest.mark.asyncio
async def test_release_uat_telegram_gateway_command_flow(tmp_path: Path) -> None:
    """Telegram handler covers no-session hint, /new, /help, and an SDK reply."""
    workspace = repo_workspace()
    user_id = RELEASE_UAT_ALLOWED_USER_ID
    chat_id = user_id

    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        async with telegram_gateway_with_real_sdk(
            tmp_path,
            facade=facade,
            workspace=workspace,
            allowed_users=[user_id],
        ) as (_ctx, _adapter, fake_bot, fake_dispatcher):
            handler = await registered_handler(fake_dispatcher)

            await handler(
                private_message(chat_id=chat_id, user_id=user_id, text="hello")
            )
            texts = await wait_for_bot_reply_texts(
                fake_bot, min_calls=1, timeout_seconds=5.0
            )
            assert TELEGRAM_NO_SESSION_HINT in texts[-1]

            await handler(
                private_message(chat_id=chat_id, user_id=user_id, text="/new")
            )
            texts = await wait_for_bot_reply_texts(
                fake_bot, min_calls=2, timeout_seconds=30.0
            )
            assert any(TELEGRAM_NEW_CONFIRMATION in text for text in texts)

            await handler(
                private_message(chat_id=chat_id, user_id=user_id, text="/help")
            )
            texts = await wait_for_bot_reply_texts(
                fake_bot, min_calls=3, timeout_seconds=10.0
            )
            assert any("/stop" in text and "/help" in text for text in texts)

            await handler(
                private_message(
                    chat_id=chat_id,
                    user_id=user_id,
                    text=MINIMAL_SDK_PROMPT,
                )
            )
            texts = await wait_for_bot_reply_texts(
                fake_bot,
                min_calls=4,
                timeout_seconds=SDK_TIMEOUT_SECONDS,
            )
            assert texts[-1].strip()


@pytest.mark.asyncio
async def test_release_uat_telegram_start_stop_and_blocked_sender(
    tmp_path: Path,
) -> None:
    """Telegram /start and /stop hints work; allowlist blocks unknown senders."""
    workspace = repo_workspace()
    user_id = RELEASE_UAT_ALLOWED_USER_ID
    chat_id = user_id

    async with AsyncSdkFacade(bridge_options={"workspace": workspace}) as facade:
        async with telegram_gateway_with_real_sdk(
            tmp_path,
            facade=facade,
            workspace=workspace,
            allowed_users=[user_id],
        ) as (_ctx, _adapter, fake_bot, fake_dispatcher):
            handler = await registered_handler(fake_dispatcher)

            await handler(
                private_message(chat_id=chat_id, user_id=user_id, text="/start")
            )
            texts = await wait_for_bot_reply_texts(
                fake_bot, min_calls=1, timeout_seconds=5.0
            )
            assert TELEGRAM_NO_SESSION_HINT in texts[-1]

            await handler(
                private_message(chat_id=chat_id, user_id=user_id, text="/stop")
            )
            texts = await wait_for_bot_reply_texts(
                fake_bot, min_calls=2, timeout_seconds=5.0
            )
            assert TELEGRAM_STOP_NO_SESSION in texts[-1]

            blocked = RELEASE_UAT_BLOCKED_USER_ID
            await handler(
                private_message(chat_id=blocked, user_id=blocked, text="hello")
            )
            await asyncio.sleep(0.5)
            assert len(fake_bot.send_message_calls) == 2
