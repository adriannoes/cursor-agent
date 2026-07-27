"""Package artifact smoke tests for the installed wheel.

Builds the wheel, installs into a fresh virtualenv, and verifies the
console script (including ``skills --help`` / ``models --help``), bundled
messaging hook scripts, and skills_pack catalog. No CURSOR_API_KEY.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from cursor_agent.messaging_hooks import MESSAGING_HOOK_FILENAMES

pytestmark = pytest.mark.package_smoke

REPO_ROOT = Path(__file__).resolve().parents[2]
SMOKE_TIMEOUT_SECONDS = 55
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove Rich/ANSI SGR so flag names are contiguous (PR #72 / #75 lesson)."""
    return _ANSI_ESCAPE_RE.sub("", text)


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


def _build_wheel(out_dir: Path) -> Path:
    """Build the project wheel into ``out_dir`` and return the sole artifact path.

    WHY (PR #69): ``sorted(dist/*.whl)[-1]`` can pick a stale wheel from a dirty
    repo ``dist/``; isolate builds under a temp out-dir instead.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    build = _run_command(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir), "--clear"],
    )
    _assert_success(build, step="uv build --wheel")
    wheels = sorted(out_dir.glob("*.whl"))
    assert len(wheels) == 1, (
        f"expected exactly one wheel under {out_dir}, "
        f"received {len(wheels)}: {[path.name for path in wheels]!r}"
    )
    wheel_path = wheels[0]
    # WHY: resolve both sides so a symlinked out_dir cannot false-fail (PR #70).
    assert wheel_path.resolve().is_relative_to(out_dir.resolve()), (
        f"wheel must live under smoke out-dir: received {wheel_path}, expected under {out_dir}"
    )
    return wheel_path


def _create_smoke_venv(venv_dir: Path) -> Path:
    """Create an isolated virtualenv via ``uv venv`` for installed-package verification.

    WHY (PR #69): ``python -m venv`` depends on ensurepip; ``uv venv`` matches
    the project toolchain and avoids that fragility.
    """
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    create = _run_command(["uv", "venv", "--seed", "--clear", str(venv_dir)])
    _assert_success(create, step="uv venv")
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


def _verify_setup_help(console_script: Path) -> None:
    """Installed package must expose ``cursor-agent setup --help`` (FR-26)."""
    help_result = _run_command([str(console_script), "setup", "--help"])
    _assert_success(help_result, step="cursor-agent setup --help")
    combined = f"{help_result.stdout}\n{help_result.stderr}"
    assert "Examples" in combined, (
        "cursor-agent setup --help did not include Examples epilog: "
        f"stdout={help_result.stdout!r}, stderr={help_result.stderr!r}"
    )


def _verify_skills_help(console_script: Path) -> None:
    """Installed package must expose registered ``skills`` subcommands.

    WHY: substring checks on group help can match prose in the description;
    per-subcommand ``--help`` proves Typer registered path/list/seed.
    """
    group_help = _run_command([str(console_script), "skills", "--help"])
    _assert_success(group_help, step="cursor-agent skills --help")
    for subcommand in ("path", "list", "seed"):
        sub_help = _run_command([str(console_script), "skills", subcommand, "--help"])
        _assert_success(
            sub_help,
            step=f"cursor-agent skills {subcommand} --help",
        )


def _verify_models_help(console_script: Path) -> None:
    """Installed package must expose ``cursor-agent models --help`` (PRD-017 FR-5).

    WHY: Rich help may style ``--json`` as separate ANSI-colored ``-`` tokens, so
    substring checks must strip SGR first (same lesson as PR #72 auth help).
    """
    help_result = _run_command([str(console_script), "models", "--help"])
    _assert_success(help_result, step="cursor-agent models --help")
    combined = _strip_ansi(f"{help_result.stdout}\n{help_result.stderr}")
    assert "--json" in combined, (
        "cursor-agent models --help must document --json: "
        f"stdout={help_result.stdout!r}, stderr={help_result.stderr!r}"
    )
    assert "--verbose" not in combined, (
        "cursor-agent models --help must not document --verbose: "
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


def _verify_packaged_skills_pack(python_bin: Path) -> None:
    """Installed wheel must embed skills under skills_pack, never the Python package.

    WHY: unit tests can pass via checkout fallback; smoke must lock the installed
    ``cursor_agent/skills_pack`` contract on a real wheel.
    """
    probe = "\n".join(
        [
            "from pathlib import Path",
            "import cursor_agent.skills as skills_pkg",
            "from cursor_agent.skills.pack_paths import bundled_skills_pack_root",
            "pack_root = bundled_skills_pack_root()",
            "assert pack_root.is_dir(), pack_root",
            "assert pack_root.name == 'skills_pack', (",
            "    f'expected installed pack under skills_pack, received {pack_root!r}'",
            ")",
            "skill_files = sorted(pack_root.rglob('SKILL.md'))",
            "assert len(skill_files) == 14, (",
            "    f'expected 14 SKILL.md under skills_pack, received {len(skill_files)}: '",
            "    f'{[str(p.relative_to(pack_root)) for p in skill_files]!r}'",
            ")",
            "python_skills = Path(skills_pkg.__file__).resolve().parent",
            "leaked = sorted(python_skills.rglob('SKILL.md'))",
            "assert not leaked, (",
            "    f'SKILL.md must not ship under cursor_agent/skills package: '",
            "    f'{[str(p) for p in leaked]!r}'",
            ")",
        ]
    )
    check = _run_command([str(python_bin), "-c", probe])
    _assert_success(check, step="packaged skills_pack probe")


def test_installed_wheel_exposes_cli_and_hooks(tmp_path: Path) -> None:
    """Wheel install smoke: CLI help, setup/skills/models help, hooks, skills pack."""
    wheel_path = _build_wheel(tmp_path / "dist")
    python_bin = _create_smoke_venv(tmp_path / "smoke-venv")
    console_script = _install_wheel(python_bin, wheel_path)
    _verify_console_help(console_script)
    _verify_setup_help(console_script)
    _verify_skills_help(console_script)
    _verify_models_help(console_script)
    _verify_packaged_hooks(python_bin)
    _verify_packaged_skills_pack(python_bin)
    assert MESSAGING_HOOK_FILENAMES, "expected non-empty hook filename manifest"
