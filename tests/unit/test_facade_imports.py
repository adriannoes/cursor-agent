"""FR-1: isolate cursor_sdk imports to sdk_facade.py only."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import cursor_agent
import pytest


def _package_source_dir() -> Path:
    """Return the filesystem directory for the cursor_agent package."""
    init_file = Path(cursor_agent.__file__)
    if init_file.name == "__init__.py":
        return init_file.parent
    msg = f"expected package __init__.py, got {init_file!r}"
    raise AssertionError(msg)


def _module_name_for_path(package_dir: Path, py_file: Path) -> str:
    """Map a .py file under the package to its dotted module name."""
    relative = py_file.relative_to(package_dir)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    suffix = ".".join(parts)
    if suffix:
        return f"cursor_agent.{suffix}"
    return "cursor_agent"


def _file_imports_cursor_sdk(py_file: Path) -> bool:
    """Return True if the module AST contains an import of cursor_sdk."""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "cursor_sdk" or alias.name.startswith("cursor_sdk.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module == "cursor_sdk" or node.module.startswith("cursor_sdk."):
                return True
    return False


def _modules_importing_cursor_sdk() -> set[str]:
    """Collect dotted module names under cursor_agent that import cursor_sdk."""
    package_dir = _package_source_dir()
    offenders: set[str] = set()
    for py_file in package_dir.rglob("*.py"):
        if _file_imports_cursor_sdk(py_file):
            offenders.add(_module_name_for_path(package_dir, py_file))
    return offenders


def _async_sdk_facade_exists() -> bool:
    """Return True when ``AsyncSdkFacade`` is available in ``sdk_facade``."""
    sdk_facade = importlib.import_module("cursor_agent.sdk_facade")
    return hasattr(sdk_facade, "AsyncSdkFacade")


def test_cursor_sdk_import_isolation() -> None:
    """Only ``cursor_agent.sdk_facade`` may import ``cursor_sdk``."""
    offenders = _modules_importing_cursor_sdk()
    if _async_sdk_facade_exists():
        assert offenders == {"cursor_agent.sdk_facade"}, (
            f"expected only sdk_facade to import cursor_sdk, got {sorted(offenders)!r}"
        )
    else:
        assert offenders == set(), (
            f"cursor_sdk must not be imported during scaffold; offenders: {sorted(offenders)!r}"
        )


_GATEWAY_BOUNDARY_MODULES: tuple[str, ...] = (
    "cursor_agent.platforms.telegram",
    "cursor_agent.platforms.factory",
    "cursor_agent.gateway.auth",
    "cursor_agent.gateway.config",
    "cursor_agent.gateway.context",
    "cursor_agent.gateway.dispatch",
    "cursor_agent.gateway.runner",
    "cursor_agent.gateway.shutdown",
)


@pytest.mark.parametrize("module_name", _GATEWAY_BOUNDARY_MODULES)
def test_gateway_and_telegram_modules_do_not_import_cursor_sdk(
    module_name: str,
) -> None:
    """Telegram adapter, factory, and gateway modules must not import cursor_sdk."""
    package_dir = _package_source_dir()
    module_path = package_dir.joinpath(*module_name.split(".")[1:]).with_suffix(".py")
    assert module_path.is_file(), (
        f"missing module file for {module_name!r}: {module_path}"
    )
    assert not _file_imports_cursor_sdk(module_path), (
        f"{module_name} must not import cursor_sdk; use cursor_agent.sdk_facade instead"
    )
