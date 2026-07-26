---
name: compare-sources
description: Side-by-side comparison of sources on one claim or topic, with agreement map and confidence.
---

# Compare sources

## When to use

Use when the operator names two or more sources (URLs, docs, or pasted excerpts) — or a claim — and needs a structured comparison, not a blended paraphrase.

## Procedure

1. Lock the comparison axis: the claim, question, or decision criteria.
2. For each source, capture: title/URL, date, author/org, and the stance on the axis.
3. Build a side-by-side table (or aligned bullets): agree / disagree / silent on each criterion.
4. Score **confidence** per cell and overall (high / medium / low): primary data and independent outlets beat blogs and undated pages.
5. Call out gaps (missing dates, paywalls, conflicts) and what evidence would raise confidence.
6. If sources must be discovered via search and MCP is missing, tell the user to re-run with `--profile full`; do not fabricate sources. Compare only what was pasted or already known.

## Tools to prefer

- Tool profile: `full` + Brave (or equivalent) search when discovery or corroboration is needed.
- Prefer `full` only on trusted **local** CLI. Never switch gateways/bots off `messaging` (SECURITY.md / ADR-029).
- Playwright / browser when a source is JS-heavy or behind a soft gate the fetch cannot clear.
- Plain fetch/read for static pages and pasted text.

## Pitfalls

- Averaging sources into one “truth” without showing disagreement.
- Treating SEO blogs as equal to primary documents.
- Ignoring publication dates and vested interests.
- Inventing URLs when search MCP is unavailable.

## Verification

- Output is explicitly side-by-side (table or mirrored sections).
- Overall confidence is stated with reasons.
- Conflicts are listed, not smoothed away.
- If discovery failed for lack of MCP, the reply mentions `--profile full`.
