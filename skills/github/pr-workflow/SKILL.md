---
name: pr-workflow
description: Drive branch → commit → pull request → CI watch as a checklist until the change is review-ready.
---

# PR workflow

## When to use

Use when the operator wants help opening or finishing a change as a pull request: branch naming, commits, PR body, and watching CI until green or clearly failing.

## Procedure

1. Confirm goal, base branch, and whether a PR already exists. Prefer `--profile full` with GitHub MCP.
2. **Branch:** create or switch to a focused branch; keep scope to one logical change.
3. **Commit:** stage only relevant files; write a clear Conventional Commits-style message; do not commit secrets.
4. **Push + PR:** push with upstream tracking; open or update the PR with summary, test plan, and linked issues.
5. **CI watch:** poll checks; on failure, summarize the failing job and next fix; on success, note ready-for-review.
6. **Degrade gracefully** if GitHub MCP is missing: give a local `git`/`gh` checklist and tell the user to enable `--profile full` for MCP-backed status and PR creation.

## Tools to prefer

- Tool profile: `full` + GitHub MCP (preferred) for PR create/update and check status.
- Local `git` for branch/commit; `gh` as a fallback when MCP is unavailable.
- Never force-push or skip hooks unless the operator explicitly requests it.

## Pitfalls

- Mixing unrelated changes into one PR.
- Empty or vague PR descriptions with no test plan.
- Declaring “done” before CI results are known.
- Silent degradation when GitHub MCP is absent.

## Verification

- Branch, commits, and PR URL (or local next commands) are stated.
- PR body has summary + test plan.
- CI status is reported or explicitly still pending/unavailable.
- Missing GitHub MCP case includes the `--profile full` hint.
