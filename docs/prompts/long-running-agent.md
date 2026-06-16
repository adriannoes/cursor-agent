# Long-running agent — cursor-agent implementation harness

> Paste this prompt (or reference this file) when starting a **Cursor long-running agent** session on `adriannoes/cursor-agent`.
>
> **Mode:** autonomous follow-through after initial LGTM on the plan ([ADR-023](../decisions/ADR-023-long-running-agent-harness.md)).

---

## Mission

Implement **cursor-agent** end-to-end following the PRD chain, starting with **PRD-000** (SDK spike), then **PRD-001 … PRD-010** in dependency order ([docs/prd/README.md](../prd/README.md)).

You own the full loop: read context → plan → TDD implement → quality gates → code review → retro → generate tasks for next PRD → repeat.

**Motor:** [Cursor Python SDK](https://cursor.com/docs/sdk/python) + **Composer 2.5**. **Clean-room:** study reference codebases (Hermes, OpenClaw) for patterns only — zero copied code ([STRATEGY.md §1.4](../STRATEGY.md#14-relação-com-outros-projetos)).

---

## Language policy (effective immediately)

| Artifact | Language |
|----------|----------|
| All **new** source code (`src/`, `tests/`, `examples/`) | **English** |
| Comments, docstrings, error messages | **English** |
| Commit messages, PR titles, PR bodies | **English** (Conventional Commits) |
| **New or updated** documentation you write | **English** |
| Existing Portuguese planning docs | Read as-is; when you **edit** them (retro, tasks, PRDs), translate updated sections to **English** |

---

## Git & GitHub policy

**Author:** all commits and PRs must appear as **`adriannoes`** only.

- Before the first commit, verify: `git config user.name` and `git config user.email` match the repo owner. Do **not** change global git config without user approval; use local repo config if needed.
- **Never** add `Co-authored-by:`, `Signed-off-by:` for bots, or any trailer that attributes authorship to Cursor, Copilot, or other agents.
- **Never** commit `.env`, API keys, or tokens. Only `.env.example` placeholders.
- **Branches:** one feature branch per PRD — e.g. `feat/prd-000-sdk-spike`, `feat/prd-001-facade`.
- **Commits:** atomic, Conventional Commits — `feat:`, `fix:`, `test:`, `chore:`, `docs:` — one logical change per commit.
- **PRs:** open with `gh pr create` when a PRD DoD is complete and `/code-review` verdict is **Approved**. Merge to `main` only after CI green (when workflow exists) and review passed.
- **Do not** force-push `main`.

---

## Mandatory reading order (first session — do not skip)

Read fully before writing production code:

1. [AGENTS.md](../../AGENTS.md)
2. [docs/STRATEGY.md](../STRATEGY.md) — especially §1.4 references, §4 deploy, §7 Phase 0, §14.5 verification
3. [docs/DECISIONS.md](../DECISIONS.md) — skim index; deep-read ADRs listed in the active PRD frontmatter
4. [docs/prd/README.md](../prd/README.md) — PRD chain and retro rules
5. **Active PRD** — start with [PRD-000](../prd/PRD-000-sdk-spike.md)
6. [engineering/tasks/README.md](../../engineering/tasks/README.md)
7. **Active tasks file** — [tasks-PRD-000-sdk-spike.md](../../engineering/tasks/tasks-PRD-000-sdk-spike.md)
8. [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md) — read-only during PRD-000
9. Skills (read before implementing):
   - [.cursor/skills/test-driven-development/SKILL.md](../../.cursor/skills/test-driven-development/SKILL.md)
   - [.cursor/skills/verification-before-completion/SKILL.md](../../.cursor/skills/verification-before-completion/SKILL.md)
   - [.cursor/skills/systematic-debugging/SKILL.md](../../.cursor/skills/systematic-debugging/SKILL.md)
10. Commands (follow as protocols):
    - [.cursor/commands/development.md](../../.cursor/commands/development.md) — **long-running mode**
    - [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md)
    - [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc)

---

## Execution mode: long-running ([ADR-023](../decisions/ADR-023-long-running-agent-harness.md))

### Phase A — Bootstrap (this turn)

1. Read the mandatory list above.
2. Summarize: active PRD, next unchecked sub-task, risks, and estimated parent tasks remaining.
3. Propose the implementation plan for the **next parent task block** (or full PRD-000 if scope is clear).
4. **Wait for user LGTM** on the plan (unless user explicitly said "LGTM — run autonomously").

### Phase B — Autonomous execution (after LGTM)

1. Work **one sub-task at a time** from the active `engineering/tasks/tasks-PRD-*.md` file.
2. **TDD** ([ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)): failing pytest → implement → green.
3. After **each** sub-task:
   - Mark `[x]` in the tasks file; mark parent `[x]` when all children done.
   - Update **Relevant Files** in the tasks file.
   - Run the **canonical quality gate** when `tests/` or `src/` exist:

     ```bash
     ruff check src tests
     ruff format --check src tests
     mypy --strict src
     pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
     ```

     **PRD-000 note:** until `src/cursor_agent/` exists, scaffold the package in task 1.0 (`src/cursor_agent/__init__.py`) so mypy/coverage gates are meaningful. Integration tests: `pytest -m integration` only when `CURSOR_API_KEY` is set (never in CI PR gate).

4. **Do not pause** between sub-tasks for approval; report progress at parent-task boundaries.
5. Commit after each logical unit (sub-task or small group) with English Conventional Commit messages.

---

## PRD-000 starting point

**Tasks file:** [engineering/tasks/tasks-PRD-000-sdk-spike.md](../../engineering/tasks/tasks-PRD-000-sdk-spike.md) — Phase 2 complete (detailed sub-tasks ready).

**TDD order (from tasks Notes):**

`FR-1 test_pyproject_config` → smoke skeleton failing (4.1–4.2) **before** full REPL (2.0) → `async_repl` → smoke green → `tools_list` + snapshot.

**Out of scope for PRD-000:** `AsyncSdkFacade`, `SessionStore`, installable CLI — see PRD-001+.

**DoD (PRD §10):** API key + bridge OK; `docs/sdk-tools-snapshot.txt`; async path documented in examples.

---

## Closing a PRD (repeat for 000 → 010)

When all tasks are `[x]` and DoD is met:

1. Run **`/code-review`** ([code-review.md](../../.cursor/commands/code-review.md) + [code-review.mdc](../../.cursor/rules/code-review.mdc)).
2. Fix all blockers; re-run gates until **Approved**.
3. Open PR → merge to `main` (user policy: single author `adriannoes`).
4. **Retro** ([ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)): update next PRD §7, §9, §11 with learnings from code.
5. **Next PRD:**
   - Read PRD-(N+1) + its ADRs.
   - If `engineering/tasks/tasks-PRD-{NNN}-*.md` is missing, run **`/generate-tasks`** ([generate-tasks.md](../../.cursor/commands/generate-tasks.md)): parent tasks → LGTM → sub-tasks.
   - Update [engineering/tasks/README.md](../../engineering/tasks/README.md) index.
   - Create branch `feat/prd-{NNN}-{slug}` and continue.

**PRD execution order:**

```text
PRD-000 → 001 → 002 → 003 → 004
  ├─ 005 (gate) → 006 → 007 → 010
  └─ 008 | 009 (parallel after 004; retro after 007 for gateway learnings)
```

---

## SDK & secrets

- Pin `cursor-sdk==X.Y.Z` per [ADR-017](../decisions/ADR-017-sdk-version-pin.md); record actual pin in PRD-000 retro.
- `CURSOR_API_KEY` from environment only ([ADR-025](../decisions/ADR-025-secrets-policy.md)).
- Read [Cursor Python SDK skill](https://cursor.com/docs/sdk/python) / project SDK references — do not assume API from memory.

---

## Progress report format (parent-task checkpoints)

```markdown
## Checkpoint — PRD-000 / Task 1.0

**Done:** 1.1, 1.2, 1.3 (all [x])
**Gate:** ruff ✓ | format ✓ | mypy ✓ | pytest --cov ✓
**Commits:** `abc1234` chore: scaffold pyproject with pinned cursor-sdk
**Next:** Task 1.4 uv.lock
**Blockers:** none
```

---

## Hard constraints

- Do **not** copy code from Hermes, OpenClaw, or any reference repo.
- Do **not** implement outside active PRD scope without alignment.
- Do **not** skip TDD or `/code-review` before closing a PRD.
- Do **not** add co-authors to commits or PRs.
- Do **not** weaken security gates (messaging profile, gateway allowlist) when you reach PRD-005+.

---

## One-line kickoff (paste below LGTM)

After reading context and receiving LGTM, start with the first unchecked sub-task in `engineering/tasks/tasks-PRD-000-sdk-spike.md` (expected: **1.1**), TDD-first, long-running mode, English-only artifacts, commits as `adriannoes` only.
