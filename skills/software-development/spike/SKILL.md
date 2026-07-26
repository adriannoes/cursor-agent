---
name: spike
description: Time-boxed throwaway experiment to answer a design question before committing to an implementation.
---

# Spike

## When to use

Use when the team is blocked by uncertainty: unknown API shape, library fit, performance ballpark, or “will this approach even work?” — before investing in a real design or PR.

## Procedure

1. Write the **question** and a **time box** (e.g. 30–90 minutes or N attempts). Success = a clear yes/no or measured result, not polished code.
2. Build the smallest experiment that answers it (script, scratch branch, throwaway module). Prefer isolation over integrating into production paths.
3. Record observations: what worked, what failed, numbers, and links to docs or samples tried.
4. Recommend a path: adopt, abandon, or follow-up spike with a narrower question.
5. **Do not merge** spike code as the final design. If useful fragments remain, re-implement cleanly under normal plan/TDD after the spike ends.

## Tools to prefer

- Tool profile: any local (`coding` or `full`).
- Scratch files, throwaway branches, and quick scripts; avoid expanding production modules.
- External docs/search only when the question depends on upstream APIs.

## Pitfalls

- Letting the spike become the production implementation without a rewrite.
- Expanding scope past the question (“while we’re here…”).
- Skipping a written answer when the time box ends.
- Treating a happy-path demo as proof of edge-case readiness.

## Verification

- The original question has an explicit answer or measured outcome.
- Time box (or attempt limit) was respected or explicitly extended with operator consent.
- Recommendation and discarded options are stated.
- Production tree is unchanged, or spike artifacts are clearly marked for deletion/rewrite.
