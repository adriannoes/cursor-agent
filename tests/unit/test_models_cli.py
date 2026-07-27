"""Unit tests for PRD-017 ``cursor-agent models`` (Wave 5 / FR-5).

- **CLI** ``cursor-agent models [--json]`` registered on the root Typer app.
- Live catalog via facade module-level ``list_models`` (never ``cursor_sdk``
  from CLI). Ephemeral bridge + ``MODELS_LIST_TIMEOUT_SECONDS`` stay in the
  facade; CLI only awaits the facade helper.
- Soft-catalog ids from ``recommended_agent_model_ids()`` get a
  ``(recommended)`` suffix in human output; other ids do not.
- ``--json``: array of ``{id, display_name, description, recommended: bool}`` —
  no parameter schema dump, no ``--verbose``.
- Missing/empty ``CURSOR_API_KEY`` → ``AuthError`` + setup hint
  (``format_startup_error`` / ``CURSOR_API_KEY_SETUP_HINT``), exit 1.
- Bridge launch failure → ``ConfigError``, exit 1.
- ``AuthError`` from ``list_models`` → exit 1 with setup hint.
- Hermeticity: stub ``load_cwd_dotenv`` so a developer CWD ``.env`` cannot
  re-inject ``CURSOR_API_KEY`` into CliRunner invokes.

Pattern: ``tests/unit/test_skills_cli.py`` CliRunner + monkeypatch.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.errors import AuthError, ConfigError
from cursor_agent.first_party_models import recommended_agent_model_ids
from cursor_agent.product_copy import CURSOR_API_KEY_SETUP_HINT
from cursor_agent.sdk_facade import MODELS_LIST_TIMEOUT_SECONDS
from cursor_agent.sdk_facade_models import ModelCatalogEntry


_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

_FAKE_API_KEY: str = "sk-test-models-cli-key-never-print"


def _strip_ansi(text: str) -> str:
    """Remove Rich/ANSI SGR sequences so flag names are contiguous substrings."""
    return _ANSI_ESCAPE_RE.sub("", text)


def _sample_model_catalog() -> list[ModelCatalogEntry]:
    """Return a live-shaped catalog with recommended and non-recommended ids."""
    return [
        ModelCatalogEntry(
            id="grok-4.5",
            display_name="Grok 4.5",
            description="First-party default agent model",
        ),
        ModelCatalogEntry(
            id="composer-2.5",
            display_name="Composer 2.5",
            description="First-party coding model",
        ),
        ModelCatalogEntry(
            id="experimental-other",
            display_name="Experimental Other",
            description="Not in the soft recommended catalog",
        ),
    ]


def _stub_load_cwd_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent root Typer callback from reloading CWD ``.env`` into the process env."""
    # WHY: ``load_cwd_dotenv(override=False)`` can re-inject CURSOR_API_KEY from a
    # developer ``.env`` after tests ``delenv`` / set controlled values.
    monkeypatch.setattr("cursor_agent.cli.app.load_cwd_dotenv", lambda: None)


def _invoke_models(*args: str) -> Any:
    """Invoke the ``models`` subcommand via the root Typer app."""
    return CliRunner().invoke(app, ["models", *args])


def _install_fake_list_models(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: list[ModelCatalogEntry] | None = None,
    error: BaseException | None = None,
) -> list[dict[str, object]]:
    """Monkeypatch facade ``list_models`` at the CLI bind site and module path."""
    calls: list[dict[str, object]] = []
    rows = catalog if catalog is not None else _sample_model_catalog()

    async def _fake_list_models(
        *,
        api_key: str,
        timeout_seconds: float | None = None,
    ) -> list[ModelCatalogEntry]:
        calls.append({"api_key": api_key, "timeout_seconds": timeout_seconds})
        if error is not None:
            raise error
        return list(rows)

    monkeypatch.setattr(
        "cursor_agent.sdk_facade.list_models",
        _fake_list_models,
    )
    monkeypatch.setattr(
        "cursor_agent.cli.models_command.list_models",
        _fake_list_models,
    )
    return calls


# ---------------------------------------------------------------------------
# CLI: help / registration
# ---------------------------------------------------------------------------


def test_models_help_exposes_json_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """``models --help`` documents ``--json`` (no ``--verbose``)."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    result = CliRunner().invoke(app, ["models", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _strip_ansi(result.output)
    assert "--json" in help_text
    assert "--verbose" not in help_text


# ---------------------------------------------------------------------------
# CLI: successful human list + recommended markers
# ---------------------------------------------------------------------------


def test_cli_models_human_list_marks_recommended_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Human output marks soft-catalog ids with ``(recommended)``; others stay plain."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    calls = _install_fake_list_models(monkeypatch)

    result = _invoke_models()
    assert result.exit_code == 0, result.output
    output = result.output

    assert calls == [
        {
            "api_key": _FAKE_API_KEY,
            "timeout_seconds": MODELS_LIST_TIMEOUT_SECONDS,
        }
    ]

    recommended = set(recommended_agent_model_ids())
    assert "grok-4.5" in recommended
    assert "composer-2.5" in recommended

    assert "grok-4.5" in output
    assert "Grok 4.5" in output
    assert "(recommended)" in output
    # Both soft-catalog ids must carry the marker on their lines.
    for model_id in ("grok-4.5", "composer-2.5"):
        matching = [line for line in output.splitlines() if model_id in line]
        assert matching, f"expected a line for {model_id!r} in {output!r}"
        assert any("(recommended)" in line for line in matching), matching

    other_lines = [line for line in output.splitlines() if "experimental-other" in line]
    assert other_lines, f"expected a line for experimental-other in {output!r}"
    assert all("(recommended)" not in line for line in other_lines), other_lines
    assert "Experimental Other" in output
    assert _FAKE_API_KEY not in output


def test_cli_models_human_includes_id_and_display_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each human line includes model id and display_name."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    _install_fake_list_models(monkeypatch)

    result = _invoke_models()
    assert result.exit_code == 0, result.output
    for entry in _sample_model_catalog():
        assert entry.id in result.output
        assert entry.display_name in result.output


def test_cli_models_human_collapses_multiline_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Human one-line rows collapse embedded newlines in SDK descriptions."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    _install_fake_list_models(
        monkeypatch,
        catalog=[
            ModelCatalogEntry(
                id="multiline-demo",
                display_name="Multiline Demo",
                description="first line\nsecond line\nthird",
            ),
        ],
    )

    result = _invoke_models()
    assert result.exit_code == 0, result.output
    matching = [line for line in result.output.splitlines() if "multiline-demo" in line]
    assert len(matching) == 1, result.output
    assert "first line second line third" in matching[0]
    assert "\n" not in matching[0]


# ---------------------------------------------------------------------------
# CLI: --json shape
# ---------------------------------------------------------------------------


def test_cli_models_json_shape_includes_recommended_bool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--json`` is a list of objects with id/display_name/description/recommended."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    _install_fake_list_models(monkeypatch)

    result = _invoke_models("--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 3

    expected_keys = {"id", "display_name", "description", "recommended"}
    by_id = {row["id"]: row for row in payload}
    for entry in _sample_model_catalog():
        row = by_id[entry.id]
        assert set(row.keys()) == expected_keys
        assert row["display_name"] == entry.display_name
        assert row["description"] == entry.description
        assert isinstance(row["recommended"], bool)

    recommended = set(recommended_agent_model_ids())
    assert by_id["grok-4.5"]["recommended"] is True
    assert by_id["composer-2.5"]["recommended"] is True
    assert by_id["experimental-other"]["recommended"] is False
    assert set(by_id) & recommended == {"grok-4.5", "composer-2.5"}
    assert _FAKE_API_KEY not in result.output
    # No parameter-schema dump (FR-5 non-goal).
    assert "parameters" not in result.output.lower()
    assert "schema" not in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: missing / empty API key
# ---------------------------------------------------------------------------


def test_cli_models_missing_api_key_exits_one_with_setup_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unset ``CURSOR_API_KEY`` → exit 1 + AuthError setup hint; never prints a key."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    calls = _install_fake_list_models(monkeypatch)

    result = _invoke_models()
    assert result.exit_code == 1, result.output
    combined = f"{result.stdout}{result.stderr}"
    assert "CURSOR_API_KEY" in combined
    assert CURSOR_API_KEY_SETUP_HINT.strip() in combined or "setup" in combined.lower()
    assert calls == [], f"list_models must not run without a key: {calls}"
    assert "sk-" not in combined


def test_cli_models_empty_api_key_exits_one_with_setup_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty/whitespace ``CURSOR_API_KEY`` → exit 1 + setup hint path."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", "   ")
    calls = _install_fake_list_models(monkeypatch)

    result = _invoke_models()
    assert result.exit_code == 1, result.output
    combined = f"{result.stdout}{result.stderr}"
    assert "CURSOR_API_KEY" in combined or "api key" in combined.lower()
    assert CURSOR_API_KEY_SETUP_HINT.strip() in combined or "setup" in combined.lower()
    assert calls == [], f"list_models must not run with empty key: {calls}"


# ---------------------------------------------------------------------------
# CLI: facade error mapping
# ---------------------------------------------------------------------------


def test_cli_models_config_error_from_list_models_exits_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bridge launch failure (``ConfigError`` from ``list_models``) → exit 1."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    _install_fake_list_models(
        monkeypatch,
        error=ConfigError(
            "cursor models list: bridge launch failed: "
            "received spawn error, expected healthy AsyncClient"
        ),
    )

    result = _invoke_models()
    assert result.exit_code == 1, result.output
    combined = f"{result.stdout}{result.stderr}"
    assert (
        "bridge" in combined.lower()
        or "config" in combined.lower()
        or ("launch" in combined.lower())
    )
    assert _FAKE_API_KEY not in combined


def test_cli_models_auth_error_from_list_models_exits_one_with_setup_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AuthError`` from ``list_models`` → exit 1 with API-key setup hint."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    _install_fake_list_models(
        monkeypatch,
        error=AuthError("cursor models list: API key rejected by Cursor.models.list"),
    )

    result = _invoke_models()
    assert result.exit_code == 1, result.output
    combined = f"{result.stdout}{result.stderr}"
    assert CURSOR_API_KEY_SETUP_HINT.strip() in combined
    assert _FAKE_API_KEY not in combined


def test_cli_models_redacts_api_key_embedded_in_facade_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-025: error text that embeds the resolved API key must not reach stdout/stderr."""
    _stub_load_cwd_dotenv(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", _FAKE_API_KEY)
    _install_fake_list_models(
        monkeypatch,
        error=AuthError(
            f"cursor models list: API key rejected: received {_FAKE_API_KEY!r}, "
            "expected accepted Cursor credential"
        ),
    )

    result = _invoke_models()
    assert result.exit_code == 1, result.output
    combined = f"{result.stdout}{result.stderr}"
    assert _FAKE_API_KEY not in combined
    assert "sk-test-models-cli-key-never-print" not in combined
    assert "***" in combined or "[REDACTED]" in combined
    assert CURSOR_API_KEY_SETUP_HINT.strip() in combined
