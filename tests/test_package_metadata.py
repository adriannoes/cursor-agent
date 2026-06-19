"""Package metadata tests for cursor-agent public release."""

from importlib import import_module
from importlib.util import find_spec


def test_package_exposes_initial_version() -> None:
    """The package scaffold exposes the project version without SDK access."""
    assert find_spec("cursor_agent") is not None
    cursor_agent = import_module("cursor_agent")
    assert cursor_agent.__version__ == "1.0.0"
