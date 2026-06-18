"""Unit tests for gateway runner startup and inbound dispatch."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.errors import ConfigError
from cursor_agent.gateway.config import (
    load_gateway_config,
    resolve_gateway_startup_config,
)
from cursor_agent.gateway.runner import gateway_runtime, run_gateway
from cursor_agent.memory.store import (
    MEMORY_SECTION_MARKER,
    USER_MEMORY_SECTION_MARKER,
)
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.platforms.telegram_chunking import telegram_session_key
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore
from cursor_agent.platforms.base import InboundMessage, OutboundMessage

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    OrderTrackingAdapter,
    SendSpyPool,
    gateway_config,
    memory_enabled_pool_factory,
    seed_session,
    write_gateway_yaml,
)
from tests.unit.test_memory_injection import (
    SendCapturingFacade,
    _write_memory_files,
)
from tests.unit.test_telegram_adapter import (
    FakeBot,
    FakeDispatcher,
    INTEGRATION_CHAT_ID,
    _private_message,
    _registered_handler,
    _telegram_gateway_runtime,
)


async def _wait_for_condition(
    condition: Callable[[], bool],
    *,
    description: str,
    attempts: int = 20,
) -> None:
    """Wait for a background dispatch assertion to become true."""
    for _attempt in range(attempts):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"condition did not become true: {description}")


def _expected_injected_message(
    *,
    user_text: str,
    memory_text: str,
    user_message: str,
) -> str:
    """Build the locked first-turn injection message shape used in production."""
    return (
        f"{USER_MEMORY_SECTION_MARKER}\n"
        f"{user_text}\n\n"
        f"{MEMORY_SECTION_MARKER}\n"
        f"{memory_text}\n\n"
        f"{user_message}"
    )


async def _wait_for_memory_injected_metadata(
    store: SessionStore,
    session_key: str,
    *,
    attempts: int = 50,
) -> None:
    """Wait until the session row records memory_injected=true after first send."""
    for _attempt in range(attempts):
        row = await store.resolve(session_key)
        if row is not None and row.metadata.get("memory_injected") is True:
            return
        await asyncio.sleep(0.01)
    msg = f"memory_injected metadata did not persist for session_key={session_key!r}"
    raise AssertionError(msg)


def test_resolve_gateway_startup_config_rejects_coding_profile() -> None:
    """Coding tool_profile raises ConfigError with the received profile."""
    config = gateway_config(tool_profile="coding")
    with pytest.raises(ConfigError, match="coding"):
        resolve_gateway_startup_config(config)


def test_resolve_gateway_startup_config_accepts_messaging_profile() -> None:
    """Messaging tool_profile converts to CursorAgentConfig."""
    config = gateway_config(tool_profile="messaging")
    cursor_config = resolve_gateway_startup_config(config)
    assert cursor_config.tool_profile == "messaging"
    assert cursor_config.runtime.local.cwd == config.workspace


async def test_gateway_profile_coding_fails_before_hooks_store_and_adapters(
    tmp_path: Path,
) -> None:
    """Coding profile aborts before hooks, store, or adapters start."""
    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file, tool_profile="coding")
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()

    with (
        patch(
            "cursor_agent.gateway.runner.bootstrap_messaging_hooks",
        ) as mock_hooks,
        patch.object(SessionStore, "initialize", autospec=True) as mock_init,
    ):
        with pytest.raises(ConfigError, match="coding"):
            async with gateway_runtime(
                config_path=config_file,
                adapters=[adapter],
                facade=facade,
                store_path=tmp_path / "sessions.db",
            ):
                pytest.fail("gateway_runtime must not start with coding profile")

        mock_hooks.assert_not_called()
        mock_init.assert_not_called()
        assert adapter.lifecycle == []


async def test_gateway_profile_messaging_proceeds_past_profile_gate(
    tmp_path: Path,
) -> None:
    """Messaging profile passes validation and reaches hook bootstrap."""
    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file, tool_profile="messaging")
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()

    with patch(
        "cursor_agent.gateway.runner.bootstrap_messaging_hooks",
    ) as mock_hooks:
        async with gateway_runtime(
            config_path=config_file,
            adapters=[adapter],
            facade=facade,
            store_path=tmp_path / "sessions.db",
        ) as _ctx:
            mock_hooks.assert_called_once()
            assert adapter.started is True


async def test_gateway_hooks_bootstrap_called_once_before_adapters(
    tmp_path: Path,
) -> None:
    """Messaging startup calls bootstrap_messaging_hooks once before adapters."""
    config = gateway_config()
    order: list[str] = []
    adapter = OrderTrackingAdapter(order)
    facade = FakeSdkFacade()

    def _record_hooks(*_args: object, **_kwargs: object) -> None:
        order.append("hooks")

    with patch(
        "cursor_agent.gateway.runner.bootstrap_messaging_hooks",
        side_effect=_record_hooks,
    ) as mock_hooks:
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=tmp_path / "sessions.db",
        ):
            mock_hooks.assert_called_once()

    assert order == ["hooks", "adapter_start"]


async def test_gateway_hooks_config_error_aborts_startup(tmp_path: Path) -> None:
    """Hook-source ConfigError aborts startup before adapters start."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()

    with patch(
        "cursor_agent.gateway.runner.bootstrap_messaging_hooks",
        side_effect=ConfigError("missing messaging hook sources"),
    ):
        with pytest.raises(ConfigError, match="missing messaging hook sources"):
            async with gateway_runtime(
                gateway_config=config,
                adapters=[adapter],
                facade=facade,
                store_path=tmp_path / "sessions.db",
            ):
                pytest.fail("gateway_runtime must abort on hook bootstrap failure")

    assert adapter.lifecycle == []


async def test_gateway_runtime_yields_pool_store_and_closes_facade(
    tmp_path: Path,
) -> None:
    """gateway_runtime initializes store, starts adapters, and closes facade."""
    config = gateway_config()
    adapter = FakePlatformAdapter()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
    ) as ctx:
        assert isinstance(ctx.pool, SessionAgentPool)
        assert isinstance(ctx.store, SessionStore)
        assert ctx.facade is facade
        assert ctx.gateway_config == config
        assert db_path.exists()
        assert adapter.started is True
        assert facade._closed is False

    assert facade._closed is True
    assert adapter.stopped is True


async def test_dispatch_allowed_inbound_sends_assistant_reply(
    tmp_path: Path,
) -> None:
    """Allowed inbound dispatches through the pool and returns assistant text."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="hello from agent")
    session_key = "telegram:123456789:deadbeef"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="ping",
            )
        )
        await _wait_for_condition(
            lambda: len(adapter.outbound_messages) == 1,
            description="assistant reply outbound",
        )

    assert len(adapter.outbound_messages) == 1
    outbound = adapter.outbound_messages[0]
    assert outbound == OutboundMessage(
        platform="telegram",
        sender_id="123456789",
        session_key=session_key,
        text="hello from agent",
    )


async def test_dispatch_blocked_inbound_skips_pool_and_emits_auth_log(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Blocked inbound does not call the pool and emits gateway_auth_blocked."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade()
    session_key = "telegram:999888777:deadbeef"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        with caplog.at_level(logging.INFO, logger="cursor_agent.gateway.runner"):
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="999888777",
                    session_key=session_key,
                    text="unauthorized",
                )
            )
            await _wait_for_condition(
                lambda: any(
                    record.message.startswith("{")
                    and "gateway_auth_blocked" in record.message
                    for record in caplog.records
                ),
                description="blocked auth log",
            )

        assert ctx.pool.send_calls == []
        assert adapter.outbound_messages == []

    payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
    ]
    blocked = [p for p in payloads if p.get("event") == "gateway_auth_blocked"]
    assert len(blocked) == 1
    assert blocked[0]["platform"] == "telegram"
    assert blocked[0]["sender_id"] == "999888777"
    assert blocked[0]["session_key"] == session_key


async def test_gateway_runtime_builds_adapters_via_factory_when_adapters_omitted(
    tmp_path: Path,
) -> None:
    """Production startup calls the factory when adapters= is not supplied."""
    config = gateway_config()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"
    factory_adapter = FakePlatformAdapter(platform="telegram")
    captured_kwargs: dict[str, object] = {}

    def _capture_factory(**kwargs: object) -> list[FakePlatformAdapter]:
        captured_kwargs.update(kwargs)
        return [factory_adapter]

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.build_platform_adapters",
            side_effect=_capture_factory,
        ) as mock_factory,
    ):
        async with gateway_runtime(
            gateway_config=config,
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ) as ctx:
            mock_factory.assert_called_once()
            assert captured_kwargs["gateway_config"] == config
            assert captured_kwargs["facade"] is facade
            assert isinstance(captured_kwargs["store"], SessionStore)
            assert isinstance(captured_kwargs["pool"], SessionAgentPool)
            assert captured_kwargs["pool"] is ctx.pool
            assert factory_adapter.started is True

    assert factory_adapter.stopped is True


async def test_gateway_runtime_injected_adapters_bypass_factory(
    tmp_path: Path,
) -> None:
    """Explicit adapters= bypasses factory construction for deterministic tests."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.gateway.runner.build_platform_adapters",
        ) as mock_factory,
    ):
        async with gateway_runtime(
            gateway_config=config,
            adapters=[adapter],
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ):
            mock_factory.assert_not_called()
            assert adapter.started is True


async def test_gateway_runtime_enabled_telegram_with_factory_passes_validation(
    tmp_path: Path,
) -> None:
    """Enabled Telegram with factory-built adapter passes startup validation.

    Exercises the real factory + TelegramAdapter but injects offline aiogram
    bot/dispatcher doubles so the runner suite never touches the network.
    """
    config = gateway_config()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        patch(
            "cursor_agent.platforms.telegram._default_bot_factory",
            lambda token: FakeBot(token=token),
        ),
        patch(
            "cursor_agent.platforms.telegram._default_dispatcher_factory",
            FakeDispatcher,
        ),
    ):
        async with gateway_runtime(
            gateway_config=config,
            facade=facade,
            store_path=db_path,
            register_signals=False,
        ) as ctx:
            assert len(ctx.adapters) == 1
            assert isinstance(ctx.adapters[0], TelegramAdapter)
            assert ctx.adapters[0].platform == "telegram"


async def test_gateway_enabled_platform_without_adapter_fails_fast(
    tmp_path: Path,
) -> None:
    """Enabled platforms in YAML require a matching adapter at startup."""
    config = gateway_config()
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        with pytest.raises(ConfigError, match="no adapter registered"):
            async with gateway_runtime(
                gateway_config=config,
                adapters=[],
                facade=facade,
                store_path=db_path,
            ):
                pytest.fail("gateway_runtime must not start without required adapters")


async def test_gateway_disabled_platforms_without_adapters_logs_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All-disabled platform config may start with zero adapters after a warning."""
    config = gateway_config()
    disabled_config = config.model_copy(
        update={
            "platforms": config.platforms.model_copy(
                update={
                    "telegram": config.platforms.telegram.model_copy(
                        update={"enabled": False},
                    ),
                },
            ),
        },
    )
    facade = FakeSdkFacade()
    db_path = tmp_path / "sessions.db"

    with (
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
        caplog.at_level(logging.WARNING, logger="cursor_agent.gateway.runner"),
    ):
        async with gateway_runtime(
            gateway_config=disabled_config,
            adapters=[],
            facade=facade,
            store_path=db_path,
        ):
            pass

    assert any(
        "no platform adapters registered" in record.message for record in caplog.records
    )


async def test_dispatch_missing_session_does_not_auto_create_or_call_pool(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing session rows do not auto-create sessions or invoke the pool."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade()
    session_key = "telegram:123456789:missing"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        with (
            patch.object(ctx.store, "create", autospec=True) as mock_create,
            caplog.at_level(logging.WARNING, logger="cursor_agent.gateway.runner"),
        ):
            await adapter.simulate_inbound(
                InboundMessage(
                    platform="telegram",
                    sender_id="123456789",
                    session_key=session_key,
                    text="hello",
                )
            )
            await _wait_for_condition(
                lambda: any(
                    "no session row" in record.message and session_key in record.message
                    for record in caplog.records
                ),
                description="missing session warning log",
            )
            mock_create.assert_not_called()

        assert ctx.pool.send_calls == []
        assert adapter.outbound_messages == []


@pytest.mark.asyncio
async def test_dispatch_injects_memory_through_blocking_false_pool_send(
    tmp_path: Path,
) -> None:
    """Gateway dispatch injects memory through pool.send(..., blocking=False)."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv and pytest"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = SendCapturingFacade(default_reply="ok")
    session_key = "telegram:123456789:mem00001"
    db_path = tmp_path / "sessions.db"
    user_message = "what is the test command?"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=memory_enabled_pool_factory(memory_root),
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text=user_message,
            )
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1 and len(facade.send_calls) == 1,
            description="memory-injected pool send",
        )

    assert len(ctx.pool.send_calls) == 1
    assert ctx.pool.send_calls[0]["blocking"] is False
    assert ctx.pool.send_calls[0]["session_key"] == session_key
    assert ctx.pool.send_calls[0]["message"] == user_message
    expected = _expected_injected_message(
        user_text=user_text,
        memory_text=memory_text,
        user_message=user_message,
    )
    assert facade.send_calls[0]["message"] == expected


async def test_dispatch_uses_blocking_false_pool_send(tmp_path: Path) -> None:
    """Inbound dispatch calls pool.send with blocking=False."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="ok")
    session_key = "telegram:123456789:abc12345"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="status",
            )
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1,
            description="pool send call",
        )

        assert len(ctx.pool.send_calls) == 1
        assert ctx.pool.send_calls[0]["blocking"] is False
        assert ctx.pool.send_calls[0]["session_key"] == session_key
        assert ctx.pool.send_calls[0]["message"] == "status"


async def test_dispatch_rejects_inbound_when_shutting_down(tmp_path: Path) -> None:
    """Inbound messages are ignored after the shutdown flag is set."""
    config = gateway_config()
    adapter = FakePlatformAdapter(platform="telegram")
    facade = FakeSdkFacade(default_reply="should not send")
    session_key = "telegram:123456789:shutdown"
    db_path = tmp_path / "sessions.db"

    async with gateway_runtime(
        gateway_config=config,
        adapters=[adapter],
        facade=facade,
        store_path=db_path,
        pool_factory=SendSpyPool,
    ) as ctx:
        await seed_session(
            ctx.store,
            facade,
            session_key,
            workspace=config.workspace,
            tool_profile="messaging",
        )
        ctx.shutting_down = True
        await adapter.simulate_inbound(
            InboundMessage(
                platform="telegram",
                sender_id="123456789",
                session_key=session_key,
                text="late message",
            )
        )

        assert ctx.pool.send_calls == []
        assert adapter.outbound_messages == []


def test_load_gateway_config_round_trip_for_runner_fixtures(tmp_path: Path) -> None:
    """Runner fixtures use the same loader as production gateway startup."""
    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file)
    loaded = load_gateway_config(config_file)
    assert loaded.tool_profile == "messaging"


def test_help_shows_gateway_command() -> None:
    """Root --help lists the gateway subcommand."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "gateway" in result.stdout


def test_gateway_command_invokes_run_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cursor-agent gateway runs the gateway runner without blocking."""
    captured: dict[str, object] = {"invoked": False, "config_path": "unset"}

    async def stub_run_gateway(config_path: Path | None = None) -> int:
        captured["invoked"] = True
        captured["config_path"] = config_path
        return 0

    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)

    result = CliRunner().invoke(app, ["gateway"])
    assert result.exit_code == 0
    assert captured["invoked"] is True
    assert captured["config_path"] is None


def test_gateway_command_passes_config_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """cursor-agent gateway --config PATH forwards the config path to the runner."""
    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file)
    captured: dict[str, object] = {"config_path": "unset"}

    async def stub_run_gateway(config_path: Path | None = None) -> int:
        captured["config_path"] = config_path
        return 0

    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)

    result = CliRunner().invoke(app, ["gateway", "--config", str(config_file)])
    assert result.exit_code == 0
    assert captured["config_path"] == config_file


def test_gateway_command_config_error_exits_nonzero(tmp_path: Path) -> None:
    """Gateway config validation failures map to exit code 1."""
    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file, tool_profile="coding")

    with patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"):
        result = CliRunner().invoke(app, ["gateway", "--config", str(config_file)])

    assert result.exit_code == 1


def test_gateway_command_maps_cursor_agent_error_to_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CursorAgentError from the runner maps to exit code 1."""

    async def stub_run_gateway(config_path: Path | None = None) -> int:
        _ = config_path
        raise ConfigError("gateway startup failed")

    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)

    result = CliRunner().invoke(app, ["gateway"])
    assert result.exit_code == 1


def test_default_cli_invocation_does_not_run_gateway_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invoking without a subcommand does not start the gateway runner."""
    called = {"gateway": False, "repl": False}

    async def stub_run_gateway(config_path: Path | None = None) -> int:
        called["gateway"] = True
        _ = config_path
        return 0

    async def stub_run_default(_config: object) -> None:
        called["repl"] = True
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)
    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert called["gateway"] is False
    assert called["repl"] is True


async def test_run_gateway_returns_zero_after_shutdown(tmp_path: Path) -> None:
    """run_gateway blocks until shutdown_complete and returns exit code 0."""
    from contextlib import asynccontextmanager

    import cursor_agent.gateway.runner as runner_module
    from cursor_agent.gateway.context import GatewayContext

    config_file = tmp_path / "gateway.yaml"
    write_gateway_yaml(config_file)
    entered = asyncio.Event()
    contexts: list[GatewayContext] = []
    original_runtime = runner_module.gateway_runtime

    @asynccontextmanager
    async def tracing_runtime(*args: object, **kwargs: object):
        kwargs.setdefault("adapters", [FakePlatformAdapter(platform="telegram")])
        kwargs.setdefault("facade", FakeSdkFacade())
        kwargs.setdefault("store_path", tmp_path / "run-gateway-sessions.db")
        async with original_runtime(*args, **kwargs) as ctx:
            contexts.append(ctx)
            entered.set()
            yield ctx

    with (
        patch.object(runner_module, "gateway_runtime", tracing_runtime),
        patch("cursor_agent.gateway.runner.bootstrap_messaging_hooks"),
    ):
        task = asyncio.create_task(run_gateway(config_path=config_file))
        await entered.wait()
        ctx = contexts[0]
        await ctx.shutdown_coordinator.shutdown(ctx)
        exit_code = await task

    assert exit_code == 0
    assert ctx.shutting_down is True


@pytest.mark.asyncio
async def test_telegram_first_message_memory_injected_through_shared_send_path(
    tmp_path: Path,
) -> None:
    """Telegram /new followed by first free text injects memory once via pool.send."""
    memory_root = tmp_path / "memory"
    user_text = "prefer concise answers"
    memory_text = "project uses uv and pytest"
    _write_memory_files(memory_root, user_text=user_text, memory_text=memory_text)

    user_message = "first question after /new"
    facade = SendCapturingFacade(default_reply="hello after first turn")

    async with _telegram_gateway_runtime(
        tmp_path,
        facade=facade,
        pool_factory=memory_enabled_pool_factory(memory_root),
    ) as (ctx, _adapter, fake_bot, fake_dispatcher, config):
        session_key = telegram_session_key(INTEGRATION_CHAT_ID, config.workspace)
        handler = await _registered_handler(fake_dispatcher)
        await handler(_private_message(chat_id=INTEGRATION_CHAT_ID, text="/new"))
        await handler(
            _private_message(
                chat_id=INTEGRATION_CHAT_ID,
                text=user_message,
            ),
        )
        await _wait_for_condition(
            lambda: len(ctx.pool.send_calls) == 1 and len(facade.send_calls) == 1,
            description="telegram first-message memory injection",
            attempts=50,
        )
        await _wait_for_memory_injected_metadata(ctx.store, session_key)

        expected = _expected_injected_message(
            user_text=user_text,
            memory_text=memory_text,
            user_message=user_message,
        )
        assert ctx.pool.send_calls[0]["blocking"] is False
        assert ctx.pool.send_calls[0]["session_key"] == session_key
        assert ctx.pool.send_calls[0]["message"] == user_message
        assert facade.send_calls[0]["message"] == expected

        row = await ctx.store.resolve(session_key)
        assert row is not None
        assert row.metadata.get("memory_injected") is True

    reply_calls = [
        call
        for call in fake_bot.send_message_calls
        if call.get("text") == "hello after first turn"
    ]
    assert len(reply_calls) == 1
