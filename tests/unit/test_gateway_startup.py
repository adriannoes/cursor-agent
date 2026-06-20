"""Unit tests for gateway startup, profile validation, and CLI."""

from __future__ import annotations

import logging
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
from cursor_agent.gateway.runner import gateway_runtime
from cursor_agent.platforms.telegram import TelegramAdapter
from cursor_agent.pool import SessionAgentPool
from cursor_agent.sdk_facade import FakeSdkFacade
from cursor_agent.sessions.store import SessionStore

from tests.unit.gateway_fakes import (
    FakePlatformAdapter,
    NoopCronScheduler,
    OrderTrackingAdapter,
    gateway_config,
    write_gateway_yaml,
)
from tests.unit.telegram_adapter_fakes import FakeBot, FakeDispatcher


@pytest.fixture(autouse=True)
def _isolate_gateway_cron_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep gateway startup tests hermetic after cron startup wiring."""
    monkeypatch.setattr("cursor_agent.gateway.runner.CronScheduler", NoopCronScheduler)


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

    async def stub_run_default(
        _config: object,
        *,
        no_banner: bool = False,
    ) -> None:
        called["repl"] = True
        _ = no_banner
        return None

    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)
    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)

    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0
    assert called["gateway"] is False
    assert called["repl"] is True
