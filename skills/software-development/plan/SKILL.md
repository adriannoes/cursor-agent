---
name: plan
description: Write an implementation plan for a change — goals, steps, risks, and verification — without coding unless asked.
---

# Plan

## When to use

Use when the operator wants a written plan before (or instead of) coding: a feature, refactor, bug investigation path, or multi-file change that needs agreement on approach.

## Procedure

1. Restate the goal, success criteria, and constraints (language, repo conventions, deadlines, out of scope).
2. Skim the relevant code and docs enough to name real modules/paths — do not invent APIs.
3. Produce a short plan:
   - **Goal** and non-goals
   - **Approach** (options only if tradeoffs matter; pick a default)
   - **Steps** in order (files/areas touched, tests to add)
   - **Risks / open questions**
   - **Verification** (commands or checks that prove done)
4. Stop after the plan. Do **not** implement, refactor, or open PRs unless the operator explicitly asks.
5. If a decision is blocked on missing info, list the questions and the cheapest way to answer them (spike, readme, owner).

## Tools to prefer

- Tool profile: any local (`coding` or `full`); SDK-native read/search of the workspace is enough.
- Prefer grep and targeted file reads over broad rewrites.
- Skip browser/search MCP unless the plan depends on external docs the operator named.

## Pitfalls

- Starting to implement “just the first step” without being asked.
- Vague steps (“update the service”) with no concrete files or checks.
- Planning a rewrite when a small change would do.
- Ignoring existing tests, ADRs, or project conventions already in the repo.

## Verification

- A reader could execute the plan without re-deriving the approach.
- Non-goals and risks are explicit.
- Verification commands or acceptance checks are listed.
- No production code was changed unless the operator requested implementation.
