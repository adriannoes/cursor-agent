"""Package metadata tests for cursor-agent public release."""

from __future__ import annotations

import ast
import re
import tomllib
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT_TOML = _REPO_ROOT / "pyproject.toml"
_EXAMPLES_DIR = _REPO_ROOT / "examples"
_EXAMPLES_README = _EXAMPLES_DIR / "README.md"


def _project_version_from_pyproject() -> str:
    """Return ``[project].version`` from the repo-root ``pyproject.toml``."""
    with _PYPROJECT_TOML.open("rb") as handle:
        loaded: dict[str, Any] = tomllib.load(handle)
    project = loaded.get("project")
    if not isinstance(project, dict):
        raise AssertionError(
            f"invalid pyproject [project]: received {project!r}, expected mapping"
        )
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise AssertionError(
            f"invalid pyproject [project].version: received {version!r}, "
            "expected non-empty string"
        )
    return version


# Commands documented in examples/README.md — kept in sync by smoke tests.
_DOCUMENTED_CLI_COMMANDS: tuple[tuple[list[str], str], ...] = (
    (["--help"], "cursor-agent --help"),
    (["--profile", "messaging"], "cursor-agent --profile messaging"),
    (["sessions", "list"], "cursor-agent sessions list"),
    (["gateway"], "cursor-agent gateway"),
    (["cron", "list"], "cursor-agent cron list"),
)


def test_package_version_matches_pyproject() -> None:
    """Runtime ``__version__`` stays in sync with ``[project].version`` (no SDK).

    WHY: release closeouts bump dual sources (pyproject + ``__init__``); hardcoding
    the version string cannot catch the next cut shipping mismatched wheel metadata.
    """
    assert find_spec("cursor_agent") is not None
    cursor_agent = import_module("cursor_agent")
    pyproject_version = _project_version_from_pyproject()
    assert cursor_agent.__version__ == pyproject_version, (
        f"version drift: __version__={cursor_agent.__version__!r}, "
        f"pyproject [project].version={pyproject_version!r}, "
        f"expected identical strings"
    )


def test_examples_readme_exists_and_documents_product_commands() -> None:
    """Public examples index exists and lists the documented CLI surface."""
    assert _EXAMPLES_README.is_file(), (
        f"missing product examples index: {_EXAMPLES_README!r}"
    )
    text = _EXAMPLES_README.read_text(encoding="utf-8")
    for fragment in (
        "cursor-agent",
        "gateway.yaml.example",
        "messaging",
        "cron list",
        "sdk-spikes",
    ):
        assert fragment in text, (
            f"examples/README.md must document {fragment!r} for PRD-012 Task 6.1"
        )


def test_public_examples_do_not_import_cursor_sdk() -> None:
    """Public examples/ must not import cursor_sdk directly (orchestration layer only)."""
    py_files = list(_EXAMPLES_DIR.rglob("*.py"))
    offenders: list[str] = []
    for py_file in py_files:
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name == "cursor_sdk" or alias.name.startswith("cursor_sdk.")
                    for alias in node.names
                ):
                    offenders.append(str(py_file.relative_to(_REPO_ROOT)))
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module == "cursor_sdk" or node.module.startswith("cursor_sdk."):
                    offenders.append(str(py_file.relative_to(_REPO_ROOT)))
    assert offenders == [], (
        f"public examples must not import cursor_sdk; offenders: {offenders!r}"
    )


@pytest.mark.parametrize(
    ("argv", "label"),
    _DOCUMENTED_CLI_COMMANDS,
    ids=[label for _, label in _DOCUMENTED_CLI_COMMANDS],
)
def test_documented_cli_commands_are_registered(
    argv: list[str],
    label: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Static smoke: documented example commands resolve to registered Typer commands."""
    _ = label

    async def stub_run_default(
        *_args: object,
        **_kwargs: object,
    ) -> None:
        return None

    async def stub_run_gateway(*, config_path: Path | None = None) -> int:
        _ = config_path
        return 0

    monkeypatch.setattr("cursor_agent.cli.app.run_default", stub_run_default)
    monkeypatch.setattr("cursor_agent.cli.app.run_gateway", stub_run_gateway)

    async def stub_list_sessions(_config: object) -> list[object]:
        return []

    monkeypatch.setattr(
        "cursor_agent.cli.app._list_sessions_for_config",
        stub_list_sessions,
    )
    cron_root = tmp_path / "cron"
    cron_root.mkdir()
    monkeypatch.setattr(
        "cursor_agent.cli.cron_commands.resolve_cron_root",
        lambda _config: cron_root,
    )

    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, (
        f"documented command failed: cursor-agent {' '.join(argv)!r}; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_examples_readme_links_gateway_yaml_example() -> None:
    """examples/README.md links to the bundled gateway sample config."""
    text = _EXAMPLES_README.read_text(encoding="utf-8")
    assert re.search(r"gateway\.yaml\.example", text) is not None
    assert (_EXAMPLES_DIR / "gateway.yaml.example").is_file()
