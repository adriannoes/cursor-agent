# Product skills pack

Starter [AgentSkills](https://agentskills.io/specification) shipped with cursor-agent. The catalog is **visible in git** under this `skills/` tree (and embedded in the wheel). Playbooks become **discoverable** to the agent only after you run `cursor-agent skills seed` and/or paste a skill into project or user `.cursor/skills/`. Empty `/skills` (and `skills list`) until then is expected — there is no auto-seed on install.

## Paste destinations (bring-your-own)

Copy a third-party skill folder so it contains `SKILL.md` at:

| Scope | Path | Prefer when |
|-------|------|-------------|
| **Project** | `{cwd}/.cursor/skills/<name>/` | Team repos (check into git) |
| **User** | `~/.cursor/skills/<name>/` | Personal globals across projects |

Project wins over user when the same `name` exists in both (same precedence as REPL `/skills`). Print absolute roots with:

```bash
cursor-agent skills path
```

That command prints `project:` and `user:` lines plus short paste hints. Confirm discovery with `cursor-agent skills list` (same listing as REPL `/skills`).

### Trust

Third-party skills are **untrusted instructions** the agent may follow. Only paste from sources you trust. Prefer reading each `SKILL.md` before enabling it.

## CLI

| Command | Purpose |
|---------|---------|
| `cursor-agent skills path` | Print absolute project and user skills roots + BYO paste hints |
| `cursor-agent skills list` | List discoverable skills (project + user roots; same as `/skills`) |
| `cursor-agent skills seed` | Copy missing starters from this pack into `~/.cursor/skills/<slug>/` (flat; categories are repo-only) |
| `cursor-agent skills seed --force` | Overwrite existing same-name dirs under the user skills root |

Bare `cursor-agent skills` shows Typer help. Seed is idempotent: existing destinations are skipped unless `--force`. Any seed failure exits non-zero; skips-only is success.

> **Note:** The `skills` CLI group (`path` / `list` / `seed`) lands with the PRD-016 CLI wave. Until then, paste manually into the destinations above; intended UX matches the table.

## Starter catalog

Fourteen starters, grouped by category in this tree. After seed, discovery uses a **flat** layout keyed by frontmatter `name` (not category folders).

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
