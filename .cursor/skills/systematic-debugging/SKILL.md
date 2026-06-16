---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior in cursor-agent, before proposing fixes. Required for SDK bridge and integration issues.
---

# Systematic Debugging

**Source:** [obra/superpowers](https://github.com/obra/superpowers) (MIT) — adapted for cursor-agent.

## cursor-agent context

- **SDK failures:** check `CURSOR_API_KEY`, bridge startup, pin `cursor-sdk==X.Y.Z` ([ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md)).
- **Smoke repro:** `pytest tests/integration/test_sdk_smoke.py -m integration -v`
- **Unit vs integration:** if unit passes but integration fails, suspect bridge/runtime — not facade logic.
- **Facade boundary:** `rg "cursor_sdk" src/` must hit only `sdk_facade.py` once facade exists ([code-review gates](../rules/code-review.mdc)).

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue: test failures, bugs in production, unexpected behavior, performance problems, build failures, integration issues.

**Use this ESPECIALLY when:**

- Under time pressure
- "Just one quick fix" seems obvious
- You've already tried multiple fixes
- Previous fix didn't work
- You don't fully understand the issue
- Bridge or SDK errors are opaque

## The Four Phases

Complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully** — Don't skip past errors. Read stack traces completely. Note line numbers, file paths, error codes.

2. **Reproduce Consistently** — Can you trigger it reliably? What are the exact steps? If not reproducible → gather more data, don't guess.

3. **Check Recent Changes** — What changed that could cause this? Git diff, recent commits, new dependencies, config changes.

4. **Gather Evidence in Multi-Component Systems** — For each component boundary (CLI → facade → SDK → bridge): log what enters/exits, verify environment propagation, check state at each layer. Run once to gather evidence showing WHERE it breaks.

5. **Trace Data Flow** — Where does bad value originate? What called this with bad value? Keep tracing up until you find the source. Fix at source, not at symptom.

### Phase 2: Pattern Analysis

1. **Find Working Examples** — Locate similar working code in same codebase or `examples/`.
2. **Compare Against References** — If implementing a pattern, read reference implementation COMPLETELY (PRD, ADR, contract).
3. **Identify Differences** — What's different between working and broken? List every difference.
4. **Understand Dependencies** — What other components does this need? What settings, config, environment?

### Phase 3: Hypothesis and Testing

1. **Form Single Hypothesis** — State clearly: "I think X is the root cause because Y"
2. **Test Minimally** — Make the SMALLEST possible change to test hypothesis. One variable at a time.
3. **Verify Before Continuing** — Did it work? Yes → Phase 4. Didn't work? Form NEW hypothesis.
4. **When You Don't Know** — Say "I don't understand X". Don't pretend. Ask for help.

### Phase 4: Implementation

1. **Create Failing Test Case** — Simplest possible reproduction. MUST have before fixing ([TDD skill](../test-driven-development/SKILL.md)).
2. **Implement Single Fix** — Address the root cause. ONE change at a time. No "while I'm here" improvements.
3. **Verify Fix** — Test passes now? No other tests broken? Issue actually resolved?
4. **If 3+ Fixes Failed** — STOP. Question the architecture. Discuss with your human partner before attempting more fixes.

## Red Flags — STOP and Follow Process

- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- Proposing solutions before tracing data flow
- "One more fix attempt" (when already tried 2+)
- Bumping `cursor-sdk` pin without reading ADR-017

**ALL of these mean: STOP. Return to Phase 1.**

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|----------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Form theory, test minimally | Confirmed or new hypothesis |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |
