---
name: dispatching-parallel-agents
description: Use when facing 2+ independent cursor-agent tasks that can be worked on without shared state or sequential dependencies.
---

# Dispatching Parallel Agents

**Source:** [obra/superpowers](https://github.com/obra/superpowers) (MIT) — adapted for cursor-agent / Cursor Task tool.

## cursor-agent context

- **Cursor tool:** use `Task` with appropriate `subagent_type` (`explore`, `generalPurpose`, `shell`, etc.)
- **Parallel dispatch:** launch multiple Task calls in a **single message** when problems are independent
- **Context hygiene:** subagents should not inherit full session history — craft self-contained prompts with file paths, ADRs, and expected output
- **After return:** run `pytest -m "not integration" -v` and check for conflicting edits
- **Gateway/messaging profile:** do NOT parallelize write operations on shared files

## Overview

Delegate tasks to specialized agents with isolated context. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session's context or history — you construct exactly what they need. This also preserves your own context for coordination work.

When you have multiple unrelated failures (different test files, different subsystems, different bugs), investigating them sequentially wastes time. Each investigation is independent and can happen in parallel.

**Core principle:** Dispatch one agent per independent problem domain. Let them work concurrently.

## When to Use

**Use when:**

- 3+ test files failing with different root causes
- Multiple subsystems broken independently (e.g., config loader vs facade vs CLI)
- Each problem can be understood without context from others
- No shared state between investigations
- Broad codebase exploration across unrelated areas

**Don't use when:**

- Failures are related (fix one might fix others)
- Need to understand full system state
- Agents would edit the same files
- Working on a single PRD sub-task with tight scope (sequential is fine)

## The Pattern

### 1. Identify Independent Domains

Group failures by what's broken:

- File A: SessionStore persistence
- File B: Config loader validation
- File C: CLI argument parsing

Each domain is independent — fixing config validation doesn't affect CLI parsing.

### 2. Create Focused Agent Tasks

Each agent gets:

- **Specific scope:** One test file or subsystem
- **Clear goal:** Make these tests pass / return findings
- **Constraints:** Don't change other code; cite ADRs
- **Expected output:** Summary of root cause and changes

### 3. Dispatch in Parallel

Launch all independent agents in one message:

```
Task(subagent_type="generalPurpose", prompt="Fix tests in tests/unit/test_config_loader.py ...")
Task(subagent_type="generalPurpose", prompt="Fix tests in tests/unit/test_session_key.py ...")
```

Set `readonly: true` for exploration-only tasks.

### 4. Review and Integrate

When agents return:

- Read each summary
- Verify fixes don't conflict (`git diff` on overlapping paths)
- Run `pytest -m "not integration" -v`
- Integrate all changes

## Agent Prompt Structure

Good agent prompts are:

1. **Focused** — One clear problem domain
2. **Self-contained** — File paths, ADR links, error output pasted
3. **Specific about output** — "Return root cause + files changed"

Example for cursor-agent:

```markdown
Fix the 2 failing tests in tests/unit/test_session_key.py.

Context:
- ADR-004: session_key must include workspace_hash
- Contract: docs/contracts/async-sdk-facade.md (read-only)

Failures:
[paste pytest output]

Constraints:
- Do NOT touch sdk_facade.py
- Follow TDD if adding behavior
- Return: root cause summary + list of files changed
```

## Common Mistakes

**Too broad:** "Fix all the tests" — agent gets lost  
**Specific:** "Fix test_session_key.py" — focused scope

**No context:** "Fix the facade" — agent doesn't know contract  
**Context:** Paste ADR-002 + contract path + error output

**No constraints:** Agent might refactor everything  
**Constraints:** "Do NOT import cursor_sdk outside sdk_facade.py"

## Verification

After agents return:

1. **Review each summary** — Understand what changed
2. **Check for conflicts** — Did agents edit same code?
3. **Run full suite** — `pytest -m "not integration" -v`
4. **Spot check** — Agents can make systematic errors

## Related

- [systematic-debugging](../systematic-debugging/SKILL.md) — when failures may be related, investigate first
- [ADR-023](../../../docs/decisions/ADR-023-long-running-agent-harness.md) — long-running harness checkpoints
