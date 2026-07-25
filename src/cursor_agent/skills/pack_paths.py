"""Resolve bundled pack and project/user skills roots (PRD-016 FR-1, FR-3).

WHY: the wheel embeds product skills at ``cursor_agent/skills_pack``, never at
``cursor_agent/skills`` — that path is the Python discovery package (Q5).
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from cursor_agent.errors import ConfigError


def _packaged_skills_pack_dir() -> Path:
    """Return the wheel-packaged skills pack directory (``skills_pack``)."""
    # Never map onto cursor_agent/skills — that is the Python package for discovery.
    packaged = resources.files("cursor_agent").joinpath("skills_pack")
    return Path(str(packaged))


def _checkout_skills_pack_dir() -> Path:
    """Return the repository checkout skills pack directory (repo-root ``skills/``)."""
    # pack_paths.py lives at src/cursor_agent/skills/ → parents[2] is repo root.
    module_dir = Path(__file__).resolve().parent
    return module_dir.parents[2] / "skills"


def bundled_skills_pack_root() -> Path:
    """Resolve the bundled product skills pack from package or checkout.

    Prefers the packaged ``cursor_agent/skills_pack`` tree, then falls back to
    the repository ``skills/`` directory. Returns the first candidate that
    exists as a directory.

    Example:
        >>> root = bundled_skills_pack_root()
        >>> root.is_dir()
        True
    """
    candidates: tuple[Path, Path] = (
        _packaged_skills_pack_dir(),
        _checkout_skills_pack_dir(),
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()

    searched = ", ".join(str(path) for path in candidates)
    raise ConfigError(
        f"bundled skills pack not found: searched [{searched}], "
        f"expected an existing directory at packaged "
        f"cursor_agent/skills_pack or checkout skills/"
    )


def project_skills_root(cwd: Path) -> Path:
    """Return the project-scoped skills root without touching disk.

    Example:
        >>> project_skills_root(Path("/ws"))
        PosixPath('/ws/.cursor/skills')
    """
    return cwd / ".cursor" / "skills"


def user_skills_root(home: Path) -> Path:
    """Return the user-scoped skills root without touching disk.

    Example:
        >>> user_skills_root(Path("/home/me"))
        PosixPath('/home/me/.cursor/skills')
    """
    return home / ".cursor" / "skills"
