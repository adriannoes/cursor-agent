---
name: issues
description: Triage, create, or update GitHub issues with clear titles, templates, and next actions.
---

# Issues

## When to use

Use when the operator wants to triage an issue backlog, file a new bug/feature request, or update an existing issue with status, labels, or a sharper write-up.

## Procedure

1. Confirm repo and intent (triage list, create, or update). Prefer `--profile full` with GitHub MCP.
2. For **triage:** skim open issues; group duplicates; propose priority and next owner/action per item.
3. For **create/update**, use a clear template:
   - **Title** (specific, searchable)
   - **Problem / goal**
   - **Repro or acceptance criteria** (steps, expected vs actual, or Done-when)
   - **Context** (version, env, links to PRs/logs)
   - **Labels / assignees** (only if known and allowed)
4. Prefer updating an existing issue over opening a duplicate; link related issues/PRs.
5. **Degrade gracefully** if GitHub MCP is missing: draft the issue markdown for paste, or use `gh` if available, and tell the user to enable `--profile full`.

## Tools to prefer

- Tool profile: `full` + GitHub MCP (preferred).
- `gh issue` as fallback; otherwise return copy-pasteable markdown.
- Do not invent issue numbers, labels, or project board state you did not fetch.

## Pitfalls

- Vague titles (“fix bug”) with no repro or acceptance criteria.
- Duplicating issues instead of linking.
- Silent failure when GitHub MCP is absent.
- Changing labels/assignees without operator consent when policy is unclear.

## Verification

- Each created/updated issue has a specific title and actionable body.
- Triage output lists next actions (not only “needs work”).
- Related links (PR, duplicate, docs) are included when known.
- Missing GitHub MCP case includes the `--profile full` hint.
