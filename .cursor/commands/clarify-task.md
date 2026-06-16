# Clarify Task

Break down ambiguous work into clear, actionable steps **before** writing production code. Supports the LGTM gate in [ADR-023](../docs/decisions/ADR-023-long-running-agent-harness.md).

**Invoke when:** user request is vague, scope unclear, multiple interpretations exist, or starting a new PRD sub-task without explicit approval.

---

## Step 1 — Gather context

Before asking questions, read:

| Input | Path |
|-------|------|
| PRD ativo | `docs/prd/PRD-*.md` (check [prd/README.md](../docs/prd/README.md)) |
| Tasks | `engineering/tasks/tasks-PRD-*.md` |
| ADRs referenced | frontmatter `adrs:` of active PRD |
| Recent changes | `git diff` / `git status` |

---

## Step 2 — Identify ambiguity

- What is unclear or underspecified?
- What assumptions might we be making?
- What could go wrong if we guess wrong?
- Does this fit the active PRD scope, or is it out-of-scope?

---

## Step 3 — Ask clarifying questions

- One question at a time (use AskQuestion tool when available)
- Prefer multiple choice when possible
- Focus on: purpose, constraints, success criteria, phase in [STRATEGY.md](../docs/STRATEGY.md)

**cursor-agent-specific prompts:**

- Which PRD / FR does this map to?
- Unit test only, or integration test with `CURSOR_API_KEY`?
- Does this touch `cursor_sdk` directly? (should go through facade per ADR-002)
- Guided mode (pause per sub-task) or long-running mode?

---

## Step 4 — Present interpretations

If multiple interpretations exist:

- List each with tradeoffs
- Do NOT pick silently
- Get explicit confirmation before proceeding

---

## Step 5 — Define acceptance criteria

- What does "done" look like? (map to PRD §4 FR or §10 DoD)
- How will we verify? (`pytest`, `ruff`, `/code-review`)
- What are non-goals / boundaries?

---

## Step 6 — Produce actionable plan

Deliver a brief breakdown:

```markdown
## Clarified scope
...

## Assumptions
- ...

## Open questions (if any)
- ...

## Proposed steps
1. [ ] Step — verification: ...
2. [ ] Step — verification: ...

## LGTM required before coding
```

**Wait for explicit LGTM** ("yes", "LGTM", "go") before writing production code — except sub-tasks already approved in a prior session with unchanged scope ([development.md](./development.md)).

---

## Output rules

- Do NOT start implementation in the same turn as clarification
- Do NOT skip LGTM in long-running mode without an approved plan from a prior turn
- Link every step to a test or verification command
