"""Shared helpers for maintainer release UAT integration tests."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from cursor_agent.gateway.config import GatewayConfig
from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import AsyncSdkFacade

from tests.unit.gateway_fakes import gateway_config
from tests.unit.telegram_adapter_fakes import FakeBot, FakeDispatcher

REPO_ROOT = Path(__file__).resolve().parents[2]
MINIMAL_SDK_PROMPT = "Reply with the single word OK."
SDK_TIMEOUT_SECONDS = 120.0
GATEWAY_STARTUP_SECONDS = 8.0
CLI_SUBPROCESS_TIMEOUT_SECONDS = 60.0
TELEGRAM_GET_ME_TIMEOUT_SECONDS = 15.0
DEFAULT_GATEWAY_CONFIG_PATH = Path.home() / ".cursor-agent" / "gateway.yaml"
RELEASE_UAT_ALLOWED_USER_ID = 10_180_039_55
RELEASE_UAT_BLOCKED_USER_ID = 999_888_777


def repo_workspace() -> str:
    """Return the repository root as the agent workspace path."""
    return str(REPO_ROOT.resolve())


def cursor_agent_argv(*args: str) -> list[str]:
    """Resolve the ``cursor-agent`` console script for subprocess UAT steps."""
    script = shutil.which("cursor-agent")
    if script is None:
        msg = (
            "cursor-agent console script not found on PATH; "
            "run `uv sync` before release UAT"
        )
        raise RuntimeError(msg)
    return [script, *args]


def run_cursor_agent_cli(
    *args: str,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    """Run a non-interactive ``cursor-agent`` CLI command for release UAT."""
    return subprocess.run(
        cursor_agent_argv(*args),
        cwd=cwd,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
        timeout=CLI_SUBPROCESS_TIMEOUT_SECONDS,
    )


async def repl_line_reader(*lines: str) -> AsyncIterator[str]:
    """Yield scripted REPL input lines in order."""
    for line in lines:
        yield line


async def wait_for_bot_reply_texts(
    fake_bot: FakeBot,
    *,
    min_calls: int,
    timeout_seconds: float = SDK_TIMEOUT_SECONDS,
) -> list[str]:
    """Poll fake Telegram bot sends until ``min_calls`` replies are captured."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        texts = [str(call.get("text", "")) for call in fake_bot.send_message_calls]
        if len(texts) >= min_calls:
            return texts
        await asyncio.sleep(0.25)
    raise TimeoutError(
        f"expected >= {min_calls} bot replies, got {len(fake_bot.send_message_calls)}: "
        f"{fake_bot.send_message_calls!r}"
    )


def telegram_get_me_username() -> str:
    """Call Telegram ``getMe`` and return the bot username (without ``@``)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        msg = "TELEGRAM_BOT_TOKEN is required for telegram getMe release UAT"
        raise RuntimeError(msg)
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/getMe")
    with urllib.request.urlopen(
        request, timeout=TELEGRAM_GET_ME_TIMEOUT_SECONDS
    ) as response:
        payload = json.loads(response.read().decode())
    if not payload.get("ok"):
        msg = f"telegram getMe failed: {payload!r}"
        raise RuntimeError(msg)
    username = payload.get("result", {}).get("username")
    if not isinstance(username, str) or not username.strip():
        msg = f"telegram getMe returned unexpected payload: {payload!r}"
        raise RuntimeError(msg)
    return username


def run_gateway_process_smoke(
    *,
    config_path: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    startup_seconds: float = GATEWAY_STARTUP_SECONDS,
) -> None:
    """Start the real gateway process, verify it stays alive, then SIGINT it."""
    if not config_path.is_file():
        msg = f"gateway config not found: expected file at {config_path!s}"
        raise FileNotFoundError(msg)

    log_path = Path(tempfile.gettempdir()) / "cursor-agent-gateway-release-uat.log"
    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cursor_agent_argv("gateway", "--config", str(config_path)),
            cwd=REPO_ROOT,
            env=os.environ.copy(),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            time.sleep(startup_seconds)
            if proc.poll() is not None:
                log_tail = log_path.read_text(encoding="utf-8")[-2000:]
                msg = (
                    f"gateway exited early with code={proc.returncode}; "
                    f"log tail={log_tail!r}"
                )
                raise RuntimeError(msg)
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                msg = "gateway did not exit within 15s after SIGINT"
                raise TimeoutError(msg) from None


@asynccontextmanager
async def telegram_gateway_with_real_sdk(
    tmp_path: Path,
    *,
    facade: AsyncSdkFacade,
    workspace: str,
    allowed_users: list[int],
) -> AsyncIterator[tuple[object, TelegramAdapter, FakeBot, FakeDispatcher]]:
    """Start gateway runtime with TelegramAdapter wired to fake bot/dispatcher."""
    config = gateway_config(workspace=workspace, allowed_users=allowed_users)
    fake_bot = FakeBot(token=config.platforms.telegram.bot_token)
    fake_dispatcher = FakeDispatcher()
    db_path = tmp_path / "telegram-gateway-release-uat.db"

    def factory(**kwargs: object) -> list[TelegramAdapter]:
        gateway_cfg = kwargs["gateway_config"]
        cursor_cfg = kwargs["config"]
        store = kwargs["store"]
        active_facade = kwargs["facade"]
        pool = kwargs["pool"]
        logger = kwargs["logger"]
        if not isinstance(gateway_cfg, GatewayConfig):
            msg = f"expected GatewayConfig, got {type(gateway_cfg)!r}"
            raise TypeError(msg)
        if not isinstance(active_facade, AsyncSdkFacade):
            msg = f"expected AsyncSdkFacade, got {type(active_facade)!r}"
            raise TypeError(msg)
        if not isinstance(pool, SessionAgentPool):
            msg = f"expected SessionAgentPool, got {type(pool)!r}"
            raise TypeError(msg)

        def bot_factory(token: str) -> FakeBot:
            fake_bot.token = token
            return fake_bot

        def dispatcher_factory() -> FakeDispatcher:
            return fake_dispatcher

        return [
            TelegramAdapter(
                platform_config=gateway_cfg.platforms.telegram,
                gateway_config=gateway_cfg,
                config=cursor_cfg,  # type: ignore[arg-type]
                store=store,  # type: ignore[arg-type]
                facade=active_facade,
                logger=logger,  # type: ignore[arg-type]
                bot_factory=bot_factory,
                dispatcher_factory=dispatcher_factory,
            ),
        ]

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.build_platform_adapters",
            side_effect=factory,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            facade=facade,
            store_path=db_path,
            register_signals=False,
            shutdown_timeout_seconds=0.05,
        ) as ctx:
            adapter = ctx.adapters[0]
            if not isinstance(adapter, TelegramAdapter):
                msg = f"expected TelegramAdapter, got {type(adapter)!r}"
                raise TypeError(msg)
            yield ctx, adapter, fake_bot, fake_dispatcher
