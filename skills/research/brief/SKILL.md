---
name: brief
description: Turn a topic or pasted notes into a short executive brief — context, key points, risks, and next actions.
---

# Executive brief

## When to use

Use when the operator wants a scannable brief for a decision: a topic name, pasted notes, meeting dump, or research trail that must fit on one screen.

## Procedure

1. Confirm audience and decision (what they need to do after reading).
2. If only a topic is given and search MCP is available, pull a light refresh (a few high-signal sources). If search is missing, stay on pasted material and tell the user to enable `--profile full` for a web-backed brief.
3. Structure the brief:
   - **Bottom line** (2–3 sentences)
   - **Context** (why it matters now)
   - **Key points** (bullets, each with source or “from notes”)
   - **Risks / unknowns**
   - **Recommended next actions**
4. Keep it short: prefer clarity over completeness; link out instead of dumping quotes.
5. Label confidence: high / medium / low based on source quality and freshness.

## Tools to prefer

- Tool profile: `full` when a web refresh helps; otherwise SDK-native reads of pasted/local notes.
- Prefer `full` only on trusted **local** CLI. Never switch gateways/bots off `messaging` (SECURITY.md / ADR-029).
- Brave (or equivalent) search MCP for optional refresh.
- Skip Playwright unless a single critical page will not yield text via fetch/search snippets.

## Pitfalls

- Writing a long essay instead of an executive brief.
- Mixing unverified web claims with operator notes without labels.
- Omitting risks or next actions.
- Silent failure when search MCP is absent — always tell the user about `--profile full`.

## Verification

- A reader can act from the bottom line and next actions alone.
- Every non-obvious point is tagged with a source or “from notes”.
- Length stays brief (roughly one screen).
- Missing-search case includes the `--profile full` hint when web refresh was needed.
