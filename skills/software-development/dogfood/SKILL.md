---
name: dogfood
description: Exploratory QA of a web UI — walk critical flows, capture evidence, and return a prioritized bug list.
---

# Dogfood

## When to use

Use when the operator wants hands-on exploratory testing of a web UI or local web app: smoke a release, exercise a new flow, or hunt UX/functional bugs before users do.

## Procedure

1. Confirm target URL (or how to start the app), environment, and flows in scope (and out of scope).
2. Prefer **`--profile full`** with Playwright / browser MCP for real navigation, clicks, and screenshots. Walk happy paths first, then likely failure cases (empty states, auth, validation, refresh, back button).
3. For each issue: title, severity (blocker / major / minor), steps to reproduce, expected vs actual, and evidence (screenshot path, console error, URL).
4. Deliver a short summary plus a **prioritized bug list** — not a vague “seems fine”.
5. **Degrade gracefully** if Playwright or `full` is unavailable: say so, ask for `--profile full` or pasted screenshots/HAR, and limit findings to what static fetch or operator-provided evidence supports. Do not invent UI states you did not see.

## Tools to prefer

- Tool profile: `full` + Playwright / browser MCP (preferred).
- Screenshots and console capture for evidence.
- If only `coding` / no browser MCP: document the gap, use any reachable HTTP checks, and rely on operator-supplied artifacts.

## Pitfalls

- Claiming coverage of flows you did not exercise.
- Filing vibes without repro steps or expected/actual.
- Ignoring console/network errors that explain a UI symptom.
- Silent degradation when browser tools are missing.

## Verification

- In-scope flows are listed with pass/fail (or blocked + why).
- Every bug has repro steps and severity.
- Evidence is attached or explicitly unavailable.
- If Playwright/`full` was missing, the reply told the user how to re-run with better tooling.
