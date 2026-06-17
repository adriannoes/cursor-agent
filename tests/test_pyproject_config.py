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


def _project_section(config: dict[str, object]) -> dict[str, object]:
    """Return [project] with runtime shape checks."""
    project = config["project"]
    assert isinstance(project, dict)
    return project


def test_console_script_entry_point() -> None:
    """cursor-agent console script must target cli.app:main (PRD-003 FR-1)."""
    project = _project_section(_load_pyproject())
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts["cursor-agent"] == "cursor_agent.cli.app:main"


def test_project_declares_mit_license() -> None:
    """Project metadata must declare MIT license (PRD-003 FR-12, ADR-019)."""
    project = _project_section(_load_pyproject())
    license_value = project["license"]
    if isinstance(license_value, str):
        license_text = license_value
    elif isinstance(license_value, dict):
        license_text = str(license_value.get("text", ""))
    else:
        raise AssertionError(
            f"unexpected project.license shape: {license_value!r}, expected str or dict"
        )
    assert "MIT" in license_text


def test_project_readme_is_readme_md() -> None:
    """PyPI-style readme field must point at README.md (PRD-003 FR-12)."""
    project = _project_section(_load_pyproject())
    assert project["readme"] == "README.md"


def test_typer_is_runtime_dependency() -> None:
    """CLI stack requires typer as a runtime dependency (PRD-003 FR-1)."""
    project = _project_section(_load_pyproject())
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    assert any("typer" in dep for dep in dependencies)
