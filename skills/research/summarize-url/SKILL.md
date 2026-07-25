---
name: summarize-url
description: Fetch and summarize a URL or thread; use browser tools when a static fetch is not enough.
---

# Summarize URL

## When to use

Use when the operator pastes a URL, article, docs page, or public thread and wants a faithful summary — not new research beyond that resource (and light context if needed).

## Procedure

1. Confirm the target URL (or thread root) and the desired depth: TL;DR, section outline, or detailed notes.
2. Fetch the page. If content is empty, blocked, or clearly client-rendered, retry with Playwright / browser MCP.
3. Summarize in the operator’s requested depth:
   - **TL;DR** (3–5 sentences)
   - **Outline** of main sections or claims
   - **Quotes** only when wording matters (keep short)
4. Separate **what the page says** from **your caveats** (outdated, marketing tone, missing methods).
5. If neither fetch nor browser MCP can load the page (or `full` profile / Brave+browser tools are unavailable), tell the user to enable `--profile full` and/or paste the text; do not invent page content.

## Tools to prefer

- Tool profile: `full` so curated fetch/search/browser MCP is available.
- Static fetch first; Playwright / browser when needed for threads or JS apps.
- Brave search only for light context (author, date) — not a substitute for reading the URL.

## Pitfalls

- Summarizing from search snippets instead of the page.
- Hallucinating sections when the fetch failed.
- Dumping the whole article instead of a summary.
- Ignoring that non-`full` profiles may lack browser/search MCP.

## Verification

- Summary reflects the loaded page (or explicitly says load failed).
- Caveats are separate from the author’s claims.
- Depth matches the request (TL;DR vs detailed).
- On tool/profile gaps, the reply mentions `--profile full` or asks for a paste.
