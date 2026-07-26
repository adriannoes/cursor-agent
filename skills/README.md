# Product skills pack

Starter [AgentSkills](https://agentskills.io/specification) shipped with cursor-agent. The catalog is **visible in git** under this `skills/` tree (and embedded in the wheel).

**How to use today:** **paste** a skill folder into project or user `.cursor/skills/` (bring-your-own). Playbooks are **not** auto-discovered from this tree — empty `/skills` (and an empty skills list) until you paste (or later seed) is expected.

## Paste destinations (bring-your-own)

Copy a third-party skill folder so it contains `SKILL.md` at:

| Scope | Path | Prefer when |
|-------|------|-------------|
| **Project** | `{cwd}/.cursor/skills/<name>/` | Team repos (check into git) |
| **User** | `~/.cursor/skills/<name>/` | Personal globals across projects |

Project wins over user when the same `name` exists in both (same precedence as REPL `/skills`).

### Trust

Third-party skills are **untrusted instructions** the agent may follow. Only paste from sources you trust. Prefer reading each `SKILL.md` before enabling it.

## CLI (intended UX)

| Command | Purpose |
|---------|---------|
| `cursor-agent skills path` | Print absolute project and user skills roots + BYO paste hints |
| `cursor-agent skills list` | List discoverable skills (project + user roots; same as `/skills`) |
| `cursor-agent skills seed` | Copy missing starters from this pack into `~/.cursor/skills/<slug>/` (flat; categories are repo-only) |
| `cursor-agent skills seed --force` | Overwrite existing same-name dirs under the user skills root |

> **Until the CLI wave lands:** paste manually into the destinations above. Do not assume `skills seed` / `skills list` / `skills path` are available yet — those commands are the intended UX for this pack.

Bare `cursor-agent skills` will show Typer help once the group exists. Seed is idempotent: existing destinations are skipped unless `--force`. Any seed failure exits non-zero; skips-only is success.

## Starter catalog

Fourteen starters, grouped by category in this tree. After seed (or equivalent flat paste), discovery uses a **flat** layout keyed by frontmatter `name` (not category folders).

| Category | Skills |
|----------|--------|
| `research` | `deep-research`, `brief`, `compare-sources`, `summarize-url` |
| `software-development` | `plan`, `debug`, `tdd`, `spike`, `dogfood`, `simplify` |
| `github` | `pr-review`, `pr-workflow`, `issues` |
| `meta` | `build-skill` |

Format reference: [Agent Skills specification](https://agentskills.io/specification).

## This tree vs contributor `.cursor/skills/`

| Location | Audience |
|----------|----------|
| Repo-root `skills/` (this pack) | **Product** starters shipped with cursor-agent |
| Repo `.cursor/skills/` (when present) | **Contributor engineering** playbooks for developing this repository |

Do not confuse the two. Product discovery reads project/user `.cursor/skills/` after seed or BYO paste — not this catalog directory directly.
