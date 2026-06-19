"""Package artifact smoke tests (PRD-012 Task 8.1).

Builds the wheel, installs into a fresh virtualenv, and verifies the
console script and bundled messaging hook scripts. No CURSOR_API_KEY.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cursor_agent.messaging_hooks import MESSAGING_HOOK_FILENAMES

pytestmark = pytest.mark.package_smoke

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_TIMEOUT_SECONDS = 55


def _run_command(
    cmd: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with a hard timeout for package smoke steps."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=SMOKE_TIMEOUT_SECONDS,
    )


def _assert_success(
    result: subprocess.CompletedProcess[str],
    *,
    step: str,
) -> None:
    """Fail with command output when a smoke step exits non-zero."""
    assert result.returncode == 0, (
        f"{step} failed with exit code {result.returncode}: "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )


def _build_wheel() -> Path:
    """Build the project wheel and return the artifact path."""
    build = _run_command(["uv", "build", "--wheel"])
    _assert_success(build, step="uv build --wheel")
    wheels = sorted((REPO_ROOT / "dist").glob("*.whl"))
    assert wheels, f"expected wheel under {REPO_ROOT / 'dist'}, got none"
    return wheels[-1]


def _create_smoke_venv(venv_dir: Path) -> Path:
    """Create an isolated virtualenv for installed-package verification."""
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    create = _run_command([sys.executable, "-m", "venv", str(venv_dir)])
    _assert_success(create, step="python -m venv")
    python_bin = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    assert python_bin.is_file(), f"expected venv python at {python_bin!r}"
    return python_bin


def _install_wheel(python_bin: Path, wheel_path: Path) -> Path:
    """Install the built wheel and return the console script path."""
    install = _run_command(
        [str(python_bin), "-m", "pip", "install", "--no-cache-dir", str(wheel_path)],
    )
    _assert_success(install, step="pip install wheel")
    script_dir = python_bin.parent
    console_script = script_dir / "cursor-agent"
    if sys.platform == "win32":
        console_script = script_dir / "cursor-agent.exe"
    assert console_script.is_file(), (
        f"expected cursor-agent console script at {console_script!r}"
    )
    return console_script


def _verify_console_help(console_script: Path) -> None:
    """Installed console script must expose Typer help without API key."""
    help_result = _run_command([str(console_script), "--help"])
    _assert_success(help_result, step="cursor-agent --help")
    combined = f"{help_result.stdout}\n{help_result.stderr}".lower()
    assert "usage" in combined or "cursor-agent" in combined, (
        "cursor-agent --help did not print CLI usage text: "
        f"stdout={help_result.stdout!r}, stderr={help_result.stderr!r}"
    )


def _verify_packaged_hooks(python_bin: Path) -> None:
    """Installed package must ship complete messaging hook sources."""
    probe = "\n".join(
        [
            "from cursor_agent.messaging_hooks import (",
            "    MESSAGING_HOOK_FILENAMES,",
            "    resolve_messaging_hook_source_dir,",
            ")",
            "source_dir = resolve_messaging_hook_source_dir()",
            "assert source_dir.is_dir(), source_dir",
            "missing = [",
            "    name for name in MESSAGING_HOOK_FILENAMES",
            "    if not (source_dir / name).is_file()",
            "]",
            "assert not missing, missing",
        ]
    )
    check = _run_command([str(python_bin), "-c", probe])
    _assert_success(check, step="packaged hook source probe")


def test_installed_wheel_exposes_cli_and_hooks(tmp_path: Path) -> None:
    """Wheel install smoke: CLI help and messaging hooks are present."""
    wheel_path = _build_wheel()
    python_bin = _create_smoke_venv(tmp_path / "smoke-venv")
    console_script = _install_wheel(python_bin, wheel_path)
    _verify_console_help(console_script)
    _verify_packaged_hooks(python_bin)
    assert MESSAGING_HOOK_FILENAMES, "expected non-empty hook filename manifest"
