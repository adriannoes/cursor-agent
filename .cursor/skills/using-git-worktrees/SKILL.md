---
name: using-git-worktrees
description: Use when starting cursor-agent feature work that needs isolation or before executing implementation plans — creates isolated git worktrees.
---

# Using Git Worktrees

**Source:** [obra/superpowers](https://github.com/obra/superpowers) (MIT) — adapted for cursor-agent.

## cursor-agent context

- **Preferred directory:** `.worktrees/` (listed in `.gitignore`)
- **Setup:** `uv sync` when `pyproject.toml` exists
- **Baseline:** `pytest -m "not integration" -v` must pass before starting work
- **Pairs with:** [finishing-a-development-branch](../finishing-a-development-branch/SKILL.md)

## Overview

Git worktrees create isolated workspaces sharing the same repository, allowing work on multiple branches simultaneously without switching.

**Core principle:** Systematic directory selection + safety verification = reliable isolation.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Directory Selection

Follow this priority order:

1. **Check existing:** `.worktrees/` or `worktrees/` (prefer `.worktrees`)
2. **Check project config:** [AGENTS.md](../../../AGENTS.md) specifies `.worktrees/`
3. **Ask user** if no directory exists and no preference found

## Safety Verification (Project-Local)

**MUST verify directory is ignored before creating worktree:**

```bash
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```

**If NOT ignored:** Add `.worktrees/` to `.gitignore`, commit, then proceed. Prevents accidentally committing worktree contents.

## Creation Steps

### 1. Create Worktree

```bash
# Determine path (e.g., .worktrees/<branch-name>)
git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

### 2. Run Project Setup

```bash
if [ -f pyproject.toml ]; then uv sync; fi
cp .env.example .env 2>/dev/null || true  # integration tests need CURSOR_API_KEY
```

### 3. Verify Clean Baseline

```bash
pytest -m "not integration" -v
ruff check src tests
```

**If tests fail:** Report failures, ask whether to proceed or investigate.

**If tests pass:** Report ready.

### 4. Report Location

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Red Flags

**Never:**

- Create worktree without verifying it's ignored (project-local)
- Skip baseline test verification
- Proceed with failing tests without asking

**Always:**

- Verify directory is ignored for project-local
- Run `uv sync` after worktree creation
- Verify clean test baseline

## Integration

**Pairs with:** finishing-a-development-branch — cleanup worktree after work complete.
