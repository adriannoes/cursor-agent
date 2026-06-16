"""Structural tests for pyproject.toml pytest configuration (PRD-000 FR-1)."""

from pathlib import Path
import tomllib


def _load_pyproject() -> dict[str, object]:
    """Load the repository root pyproject.toml as a dict."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject_path.open("rb") as pyproject_file:
        return tomllib.load(pyproject_file)


def _pytest_ini_options(config: dict[str, object]) -> dict[str, object]:
    """Return [tool.pytest.ini_options] with runtime shape checks."""
    tool = config["tool"]
    assert isinstance(tool, dict)
    pytest_tool = tool["pytest"]
    assert isinstance(pytest_tool, dict)
    ini_options = pytest_tool["ini_options"]
    assert isinstance(ini_options, dict)
    return ini_options


def test_integration_marker_registered() -> None:
    """integration marker must be declared for ADR-005 integration test split."""
    ini_options = _pytest_ini_options(_load_pyproject())
    markers = ini_options["markers"]
    assert isinstance(markers, list)
    assert any("integration" in marker for marker in markers)


def test_asyncio_mode_is_auto() -> None:
    """asyncio_mode auto enables pytest-asyncio without per-test decorators."""
    ini_options = _pytest_ini_options(_load_pyproject())
    assert ini_options["asyncio_mode"] == "auto"
