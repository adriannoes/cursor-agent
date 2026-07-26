---
name: deep-research
description: Multi-query web research — broaden then deepen, triage sources, cite URLs, and state uncertainty in a synthesis.
---

# Deep research

## When to use

Use when the operator needs a grounded answer across the open web: competing claims, unfamiliar domains, or a question that needs more than one search pass.

## Procedure

1. Restate the question and list 2–4 sub-questions that would falsify a weak answer.
2. **Broaden:** run several distinct search queries (synonyms, date/scope variants, opposing viewpoints). Collect candidate URLs with short notes.
3. **Deepen:** open the best sources; extract claims, dates, and who is speaking. Prefer primary docs over secondary summaries.
4. Triage: drop thin or circular pages; flag conflicts and paywalled gaps.
5. Synthesize: answer first, then evidence. Cite concrete URLs for every non-obvious claim. Call out remaining uncertainty and what would resolve it.
6. If search MCP is unavailable, tell the operator to re-run with `--profile full` (Brave search) and, until then, work only from pasted notes / known URLs — do not invent citations.

## Tools to prefer

- Tool profile: `full` (curated MCP).
- Prefer `full` only on trusted **local** CLI. Never switch gateways/bots off `messaging` (SECURITY.md / ADR-029).
- Brave (or equivalent) search MCP for discovery.
- Playwright / browser MCP only when a page needs rendering or interaction.
- SDK read tools for local notes the operator provides.

## Pitfalls

- Stopping after one query or one domain.
- Citing without opening the page, or inventing URLs.
- Presenting contested claims as settled.
- Ignoring that `messaging` / non-`full` profiles lack search MCP.

## Verification

- Multiple query angles appear in the trail.
- Every key claim has a URL (or an explicit “uncited / unknown”).
- Uncertainty and next checks are stated in plain language.
- If search was missing, the reply told the user to enable `--profile full`.
