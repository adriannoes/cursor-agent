---
name: pr-review
description: Review a pull request — read the diff, flag risks and test gaps, and return a concise actionable review.
---

# PR review

## When to use

Use when the operator wants a review of an open (or draft) pull request: correctness, risks, missing tests, and whether it is merge-ready.

## Procedure

1. Confirm repo and PR identity (number, URL, or branch). Prefer `--profile full` with GitHub MCP.
2. Read PR title, description, linked issues, and the full diff (not just the summary).
3. Structure the review:
   - **Summary** (what changed and why, in 2–4 sentences)
   - **Risks** (correctness, security, data, rollout)
   - **Test gaps** (what is untested or under-tested)
   - **Nits** (optional; keep short)
   - **Verdict** (approve / request changes / needs discussion)
4. Cite concrete files or hunks for every non-trivial finding.
5. **Degrade gracefully** if GitHub MCP is missing: ask for `--profile full`, or review a pasted diff/`gh pr diff` output, and state what you could not verify (CI status, review comments, checks).

## Tools to prefer

- Tool profile: `full` + GitHub MCP (preferred).
- Prefer `full` only on trusted **local** CLI. Never switch gateways/bots off `messaging` (SECURITY.md / ADR-029).
- Fall back to `gh` CLI or operator-pasted diff when MCP is unavailable — tell the user to enable `--profile full`.
- Local workspace reads only for context already checked out; do not invent remote state.

## Pitfalls

- Rubber-stamping without reading the diff.
- Style nits crowding out real risks or missing tests.
- Silent failure when GitHub MCP is absent.
- Claiming CI is green without checking status.

## Verification

- Verdict and top risks are clear without re-reading the PR.
- Every major finding points at a file or change.
- Test gaps are explicit (or “coverage looks adequate” with why).
- Missing GitHub MCP case includes the `--profile full` hint.
