"""Unit tests for CLI ``skills path|list|seed`` (PRD-016 FR-3 / FR-7, Wave 3 / 4.1).

WHY: lock Typer registration, hermetic root injection, BYO list visibility, and
seed exit codes before ``skills_commands.py`` exists (TDD RED for Task 4.1).

Hermetic: destinations, pack, and cwd live under ``tmp_path`` only — never touch
real ``~/.cursor/skills/``.

Expected public hooks on ``cursor_agent.cli.skills_commands`` (Task 4.2 must
implement these exact names so fixtures can monkeypatch them):

- ``resolve_skills_cwd(config) -> Path``
  default: ``Path(config.runtime.local.cwd).resolve()``
- ``resolve_skills_home() -> Path``
  default: ``Path.home()``
- ``resolve_skills_pack_root() -> Path``
  default: ``bundled_skills_pack_root()``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from cursor_agent.cli.app import app
from cursor_agent.cli.rich_display import format_skills_list_output
from cursor_agent.config.loader import load_config
from cursor_agent.errors import ConfigError
from cursor_agent.skills.pack_paths import project_skills_root, user_skills_root

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

# Exact empty-list copy from ``format_skills_list_output`` (CLI list must reuse it).
_EMPTY_SKILLS_LIST_MESSAGE = (
    "No skills discovered in the configured workspace and user paths."
)

# Dotted paths for injectable hooks (Task 4.2 contract).
_RESOLVE_SKILLS_CWD = "cursor_agent.cli.skills_commands.resolve_skills_cwd"
_RESOLVE_SKILLS_HOME = "cursor_agent.cli.skills_commands.resolve_skills_home"
_RESOLVE_SKILLS_PACK_ROOT = "cursor_agent.cli.skills_commands.resolve_skills_pack_root"


@dataclass(frozen=True)
class SkillsCliEnv:
    """Hermetic roots for skills CLI tests under ``tmp_path``."""

    tmp_path: Path
    workspace: Path
    home: Path
    pack_root: Path
    project_skills: Path
    user_skills: Path
    outside_probe: Path


def _write_skill_md(skill_dir: Path, *, name: str, description: str) -> Path:
    """Create a minimal AgentSkills SKILL.md and return its path."""
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path: Path = skill_dir / "SKILL.md"
    skill_path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nBody for {name}.\n",
        encoding="utf-8",
    )
    return skill_path


def _mini_pack_with_two_skills(pack_root: Path) -> Path:
    """Build a controllable mini pack with category nesting (flatten contract)."""
    _write_skill_md(
        pack_root / "research" / "alpha-skill",
        name="alpha-skill",
        description="Mini pack research skill",
    )
    _write_skill_md(
        pack_root / "meta" / "beta-skill",
        name="beta-skill",
        description="Mini pack meta skill",
    )
    return pack_root


def _paths_touched_outside_tmp(
    tmp_path: Path,
    *,
    before: set[Path],
    after: set[Path],
) -> set[Path]:
    """Return newly created paths that are not under ``tmp_path``."""
    created = after - before
    resolved_tmp = tmp_path.resolve()
    return {path for path in created if not path.resolve().is_relative_to(resolved_tmp)}


def _snapshot_sibling_tree(tmp_path: Path) -> set[Path]:
    """Snapshot files/dirs under ``tmp_path.parent`` for hermetic write checks."""
    parent = tmp_path.parent
    return {path for path in parent.rglob("*") if path.exists()}


@pytest.fixture
def skills_cli_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> SkillsCliEnv:
    """Point skills CLI hooks at ``tmp_path`` workspace/home/pack (cron-style).

    Task 4.2 must expose ``resolve_skills_cwd``, ``resolve_skills_home``, and
    ``resolve_skills_pack_root`` on ``cursor_agent.cli.skills_commands`` so this
    fixture can monkeypatch them without patching ``Path.home`` alone.
    """
    workspace: Path = tmp_path / "workspace"
    home: Path = tmp_path / "home"
    pack_root: Path = tmp_path / "mini-pack"
    workspace.mkdir()
    home.mkdir()
    _mini_pack_with_two_skills(pack_root)

    project_skills: Path = project_skills_root(workspace)
    user_skills: Path = user_skills_root(home)
    outside_probe: Path = tmp_path.parent / f".skills-cli-outside-{tmp_path.name}"

    # WHY: prefer injectable hooks over Path.home alone (Task 4.1 contract).
    monkeypatch.setattr(_RESOLVE_SKILLS_CWD, lambda _config: workspace.resolve())
    monkeypatch.setattr(_RESOLVE_SKILLS_HOME, lambda: home.resolve())
    monkeypatch.setattr(_RESOLVE_SKILLS_PACK_ROOT, lambda: pack_root.resolve())

    # WHY C1: real load_config() reads operator ~/.cursor-agent + ambient
    # CURSOR_AGENT__* (e.g. setting_sources) and breaks hermetic discovery.
    hermetic_config = load_config(
        config_path=tmp_path / "missing.yaml",
        cli_overrides={
            "runtime": {
                "local": {
                    "cwd": str(workspace.resolve()),
                    "setting_sources": ["project", "user"],
                }
            }
        },
    )
    monkeypatch.setattr(
        "cursor_agent.cli.skills_commands.load_config",
        lambda **_kwargs: hermetic_config,
    )
    # WHY C1: root Typer callback always runs load_cwd_dotenv() on invoke.
    monkeypatch.setattr("cursor_agent.cli.app.load_cwd_dotenv", lambda: None)

    return SkillsCliEnv(
        tmp_path=tmp_path,
        workspace=workspace.resolve(),
        home=home.resolve(),
        pack_root=pack_root.resolve(),
        project_skills=project_skills,
        user_skills=user_skills,
        outside_probe=outside_probe,
    )


def _assert_no_writes_outside_tmp(
    env: SkillsCliEnv,
    *,
    before: set[Path],
) -> None:
    """Assert CLI work left no new paths outside ``tmp_path`` and no outside probe."""
    after = _snapshot_sibling_tree(env.tmp_path)
    leaked = _paths_touched_outside_tmp(env.tmp_path, before=before, after=after)
    assert not leaked, (
        f"skills CLI must not write outside tmp_path={env.tmp_path!r}, "
        f"leaked paths={sorted(str(path) for path in leaked)!r}"
    )
    assert not env.outside_probe.exists(), (
        f"outside probe must not be created: {env.outside_probe!r}"
    )


# --- Help smoke (registration) -------------------------------------------------


def test_skills_help_lists_path_list_seed() -> None:
    """``skills --help`` exits 0 and lists path, list, and seed subcommands."""
    result = CliRunner().invoke(app, ["skills", "--help"])
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}".lower()
    assert "path" in combined
    assert "list" in combined
    assert "seed" in combined


def test_skills_bare_invokes_help_with_subcommands() -> None:
    """Bare ``skills`` shows help that mentions path, list, and seed."""
    result = CliRunner().invoke(app, ["skills"])
    assert result.exit_code == 0, result.output
    combined = f"{result.stdout}\n{result.output}".lower()
    assert "path" in combined
    assert "list" in combined
    assert "seed" in combined


def test_skills_registered_on_root_help() -> None:
    """Root ``--help`` lists the ``skills`` command group."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "skills" in result.stdout.lower()


# --- path ---------------------------------------------------------------------


def test_skills_path_prints_labeled_absolute_roots(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """``skills path`` prints project:/user: absolute roots under tmp_path + paste hint."""
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    result = CliRunner().invoke(app, ["skills", "path"])

    assert result.exit_code == 0, result.output
    stdout = result.stdout
    project_label = f"project: {skills_cli_env.project_skills.resolve()}"
    user_label = f"user: {skills_cli_env.user_skills.resolve()}"
    assert project_label in stdout, (
        f"expected labeled project root {project_label!r} in stdout={stdout!r}"
    )
    assert user_label in stdout, (
        f"expected labeled user root {user_label!r} in stdout={stdout!r}"
    )
    assert str(skills_cli_env.workspace) in stdout
    assert str(skills_cli_env.home) in stdout
    assert "paste" in stdout.lower(), (
        f"skills path must include a short BYO paste blurb, received {stdout!r}"
    )
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


# --- list ---------------------------------------------------------------------


def test_skills_list_empty_uses_format_skills_list_output(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """Empty discovery must print the shared ``format_skills_list_output`` message."""
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)
    expected_empty = format_skills_list_output([])
    assert expected_empty == _EMPTY_SKILLS_LIST_MESSAGE

    result = CliRunner().invoke(app, ["skills", "list"])

    assert result.exit_code == 0, result.output
    assert _EMPTY_SKILLS_LIST_MESSAGE in result.stdout, (
        f"skills list must reuse format_skills_list_output empty copy, "
        f"received stdout={result.stdout!r}"
    )
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


def test_skills_list_sees_pasted_project_byo_skill(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """After pasting a project skill under ``.cursor/skills/``, list shows it as project."""
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)
    _write_skill_md(
        skills_cli_env.project_skills / "my-byo",
        name="my-byo",
        description="Pasted third-party BYO skill",
    )

    result = CliRunner().invoke(app, ["skills", "list"])

    assert result.exit_code == 0, result.output
    assert "my-byo" in result.stdout
    assert "Source: project" in result.stdout, (
        f"BYO under project root must show Source: project, "
        f"received stdout={result.stdout!r}"
    )
    assert "Pasted third-party BYO skill" in result.stdout
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


# --- seed ---------------------------------------------------------------------


def test_skills_seed_copies_mini_pack_into_user_root(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """``skills seed`` flattens injectable pack into user skills root under tmp_path."""
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    result = CliRunner().invoke(app, ["skills", "seed"])

    assert result.exit_code == 0, result.output
    assert (skills_cli_env.user_skills / "alpha-skill" / "SKILL.md").is_file(), (
        f"expected seeded alpha-skill under {skills_cli_env.user_skills!r}"
    )
    assert (skills_cli_env.user_skills / "beta-skill" / "SKILL.md").is_file(), (
        f"expected seeded beta-skill under {skills_cli_env.user_skills!r}"
    )
    assert not (skills_cli_env.user_skills / "research").exists(), (
        f"category dir must not appear under flat user root "
        f"{skills_cli_env.user_skills!r}"
    )
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


def test_skills_seed_second_run_skips_and_exits_zero(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """Idempotent re-seed without ``--force`` skips existing dirs and exits 0."""
    first = CliRunner().invoke(app, ["skills", "seed"])
    assert first.exit_code == 0, first.output
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    second = CliRunner().invoke(app, ["skills", "seed"])

    assert second.exit_code == 0, (
        f"skips-only seed must exit 0, received exit_code={second.exit_code!r} "
        f"output={second.output!r}"
    )
    combined = f"{second.stdout}\n{second.output}".lower()
    assert "skip" in combined or "skipped" in combined, (
        f"second seed should report skips, received output={second.output!r}"
    )
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


def test_skills_seed_force_overwrites_existing_user_skill(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """``skills seed --force`` overwrites an existing slug under the user root."""
    first = CliRunner().invoke(app, ["skills", "seed"])
    assert first.exit_code == 0, first.output
    target = skills_cli_env.user_skills / "alpha-skill" / "SKILL.md"
    target.write_text(
        "---\nname: alpha-skill\ndescription: mutated\n---\n\nMUTATED\n",
        encoding="utf-8",
    )
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    forced = CliRunner().invoke(app, ["skills", "seed", "--force"])

    assert forced.exit_code == 0, forced.output
    restored = target.read_text(encoding="utf-8")
    assert "MUTATED" not in restored, (
        f"--force must restore pack contents, received {restored!r}"
    )
    assert "Mini pack research skill" in restored
    combined = f"{forced.stdout}\n{forced.output}".lower()
    assert "overwrite" in combined or "overwritten" in combined, (
        f"--force should report overwrite, received output={forced.output!r}"
    )
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


def test_skills_seed_then_list_shows_bundled_names(
    skills_cli_env: SkillsCliEnv,
) -> None:
    """After seed into injected user root, ``skills list`` shows seeded names."""
    seed_result = CliRunner().invoke(app, ["skills", "seed"])
    assert seed_result.exit_code == 0, seed_result.output
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    list_result = CliRunner().invoke(app, ["skills", "list"])

    assert list_result.exit_code == 0, list_result.output
    assert "alpha-skill" in list_result.stdout
    assert "beta-skill" in list_result.stdout
    assert "Source: user" in list_result.stdout
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


def test_skills_seed_exits_nonzero_when_any_failed(
    skills_cli_env: SkillsCliEnv,
    monkeypatch: MonkeyPatch,
) -> None:
    """Any seed failure must make the CLI exit with code 1 and Failed: lines."""
    broken_pack = skills_cli_env.tmp_path / "broken-pack"
    _write_skill_md(
        broken_pack / "escape" / "bad",
        name="../x",
        description="Invalid slug that must fail seed",
    )
    _write_skill_md(
        broken_pack / "ok" / "good-skill",
        name="good-skill",
        description="Valid sibling still attempts seed",
    )
    monkeypatch.setattr(_RESOLVE_SKILLS_PACK_ROOT, lambda: broken_pack.resolve())
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    result = CliRunner().invoke(app, ["skills", "seed"])

    assert result.exit_code == 1, (
        f"seed with failed entries must exit 1, "
        f"received exit_code={result.exit_code!r} output={result.output!r}"
    )
    combined = f"{result.stdout}\n{result.stderr}\n{result.output}"
    assert "Failed: ../x (" in combined, (
        f"failed seed must print 'Failed: <slug> (<reason>)', "
        f"received output={combined!r}"
    )
    assert "invalid" in combined.lower(), (
        f"failed seed must include invalid-slug reason, received output={combined!r}"
    )
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)


def _raise_config_error(message: str) -> None:
    """Raise ConfigError for monkeypatched CLI hooks (C2 coverage)."""
    raise ConfigError(message)


def test_skills_path_exits_one_on_config_error(
    skills_cli_env: SkillsCliEnv,
    monkeypatch: MonkeyPatch,
) -> None:
    """``skills path`` maps ConfigError from load_config to exit code 1."""
    monkeypatch.setattr(
        "cursor_agent.cli.skills_commands.load_config",
        lambda **_kwargs: _raise_config_error(
            "invalid config: received broken skills path fixture, "
            "expected loadable CursorAgentConfig"
        ),
    )

    result = CliRunner().invoke(app, ["skills", "path"])

    assert result.exit_code == 1, result.output
    combined = f"{result.stderr}\n{result.output}"
    assert "invalid config" in combined.lower(), (
        f"expected actionable ConfigError on stderr, received {combined!r}"
    )


def test_skills_list_exits_one_on_config_error(
    skills_cli_env: SkillsCliEnv,
    monkeypatch: MonkeyPatch,
) -> None:
    """``skills list`` maps ConfigError from load_config to exit code 1."""
    monkeypatch.setattr(
        "cursor_agent.cli.skills_commands.load_config",
        lambda **_kwargs: _raise_config_error(
            "invalid config: received broken skills list fixture, "
            "expected loadable CursorAgentConfig"
        ),
    )

    result = CliRunner().invoke(app, ["skills", "list"])

    assert result.exit_code == 1, result.output
    combined = f"{result.stderr}\n{result.output}"
    assert "invalid config" in combined.lower(), (
        f"expected actionable ConfigError on stderr, received {combined!r}"
    )


def test_skills_seed_exits_one_on_pack_root_config_error(
    skills_cli_env: SkillsCliEnv,
    monkeypatch: MonkeyPatch,
) -> None:
    """``skills seed`` maps ConfigError from pack-root resolution to exit code 1."""
    missing_pack = skills_cli_env.tmp_path / "missing-pack-root"

    def _missing_pack() -> Path:
        _raise_config_error(
            f"bundled skills pack root not found: received {missing_pack!r}, "
            "expected packaged cursor_agent/skills_pack or checkout skills/"
        )
        raise AssertionError("unreachable")

    monkeypatch.setattr(_RESOLVE_SKILLS_PACK_ROOT, _missing_pack)

    result = CliRunner().invoke(app, ["skills", "seed"])

    assert result.exit_code == 1, result.output
    combined = f"{result.stderr}\n{result.output}"
    assert "pack" in combined.lower(), (
        f"expected pack-root ConfigError on stderr, received {combined!r}"
    )
    assert str(missing_pack) in combined, (
        f"error must include offending path {missing_pack!r}, received {combined!r}"
    )


def test_skills_cli_seed_writes_only_under_injected_user_root(
    skills_cli_env: SkillsCliEnv,
    monkeypatch: MonkeyPatch,
) -> None:
    """Seed must use injected home hook and never fall back to real Path.home."""

    def _forbid_real_home() -> Path:
        raise AssertionError(
            "skills seed must not call Path.home(); "
            f"expected resolve_skills_home hook → {skills_cli_env.home!r}"
        )

    monkeypatch.setattr(Path, "home", _forbid_real_home)
    before = _snapshot_sibling_tree(skills_cli_env.tmp_path)

    result = CliRunner().invoke(app, ["skills", "seed"])

    assert result.exit_code == 0, result.output
    assert skills_cli_env.user_skills.resolve().is_relative_to(
        skills_cli_env.tmp_path.resolve()
    )
    assert (skills_cli_env.user_skills / "alpha-skill" / "SKILL.md").is_file()
    assert (skills_cli_env.user_skills / "beta-skill" / "SKILL.md").is_file()
    _assert_no_writes_outside_tmp(skills_cli_env, before=before)
