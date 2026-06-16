# Run All Tests and Fix Failures

Execute the full test suite and systematically fix any failures. Use at CI recovery, after merges, or when checkpoints fail in [development.md](./development.md).

**Related:** [systematic-debugging skill](../skills/systematic-debugging/SKILL.md) — root cause before blind fixes.

---

## Step 1 — Run test suite

**Unit / structural (no API key required):**

```bash
pytest -m "not integration" -v
```

This is the default gate for every sub-task checkpoint ([ADR-023](../docs/decisions/ADR-023-long-running-agent-harness.md)).

**Lint (run in parallel or immediately after):**

```bash
ruff check src tests
```

**Integration (only when PRD or failing area requires it):**

```bash
export CURSOR_API_KEY="your-key"
pytest -m integration -v
```

Capture full output. Identify every failure — do not stop at the first error.

---

## Step 2 — Analyze failures

Categorize each failure:

| Type | Signal | Action |
|------|--------|--------|
| **New regression** | Fails on current branch, passed on main | Check recent diff first |
| **Pre-existing** | Also fails on main | Note separately; don't block unrelated fixes |
| **Flaky integration** | Intermittent bridge/SDK | Re-run once; if persistent, use systematic-debugging |
| **Environment** | Missing `CURSOR_API_KEY`, wrong Python | Fix env before code |

Prioritize: unit test regressions → lint → integration.

---

## Step 3 — Fix systematically

1. Pick **one** failure (most critical or root cause first)
2. Apply [systematic-debugging](../skills/systematic-debugging/SKILL.md) — no fix without root cause
3. Re-run the **specific test** that failed
4. Re-run full unit suite: `pytest -m "not integration" -v`
5. Repeat until green

**Do NOT:** batch unrelated fixes, skip re-run after each fix, or claim green without fresh output.

---

## Recovery checklist

- [ ] `pytest -m "not integration" -v` — 0 failures
- [ ] `ruff check src tests` — 0 errors
- [ ] Integration suite run if PRD requires it
- [ ] Root causes documented (not symptom patches)
- [ ] Task list updated if scope changed

---

## When done

If closing a PRD or branch, continue with `/code-review` — passing tests alone is not sufficient for PRD completion.
