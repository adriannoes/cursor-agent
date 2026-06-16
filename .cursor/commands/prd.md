# Generating a Product Requirements Document (PRD)

## Goal

To guide an AI assistant in creating a detailed Product Requirements Document (PRD) in Markdown format, based on an initial user prompt. The PRD should be clear, actionable, and suitable for a junior developer to understand and implement the feature.

## Process

1.  **Receive Initial Prompt:** The user provides a brief description or request for a new feature or functionality.
2.  **Ask Clarifying Questions:** Before writing the PRD, the AI *must* ask clarifying questions to gather sufficient detail. The goal is to understand the "what" and "why" of the feature, not necessarily the "how" (which the developer will figure out).
3.  **Generate PRD:** Based on the initial prompt and the user's answers to the clarifying questions, generate a PRD using the structure outlined below.
4.  **Save PRD:** Save the generated document as `PRD-XXX-[feature-name].md` inside the `docs/prd/` directory (follow the numbering chain in [docs/prd/README.md](../../docs/prd/README.md)).

## Clarifying Questions (Examples)

The AI should adapt its questions based on the prompt, but here are some common areas to explore:

*   **Problem/Goal:** "What problem does this feature solve for the user?" or "What is the main goal we want to achieve with this feature?"
*   **Target User:** "Who is the primary user of this feature?"
*   **Core Functionality:** "Can you describe the key actions a user should be able to perform with this feature?"
*   **User Stories:** "Could you provide a few user stories? (e.g., As a [type of user], I want to [perform an action] so that [benefit].)"
*   **Acceptance Criteria:** "How will we know when this feature is successfully implemented? What are the key success criteria?"
*   **Scope/Boundaries:** "Are there any specific things this feature *should not* do (non-goals)?"
*   **Data Requirements:** "What kind of data does this feature need to display or manipulate?"
*   **Edge Cases:** "Are there any potential edge cases or error conditions we should consider?"
*   **Stack / ADRs:** "Does this feature touch SDK integration, sessions, gateway, or config? Which phase in [STRATEGY.md](../../docs/STRATEGY.md) does it belong to?"

## PRD Structure

The generated PRD should include YAML frontmatter and the following sections (compatible with existing PRDs in `docs/prd/`):

**Frontmatter (YAML):**

```yaml
---
id: PRD-XXX
title: [Short title]
status: draft
phase: [0–4]
depends_on: [PRD-YYY]
adrs:
  - ADR-XXX
related:
  - path: ../STRATEGY.md
    section: "[N]"
---
```

**Body sections:**

1.  **Introdução / Visão geral:** Briefly describe the feature and the problem it solves. State the goal.
2.  **Objetivos:** List the specific, measurable objectives for this feature.
3.  **User Stories:** Detail the user narratives describing feature usage and benefits.
4.  **Requisitos funcionais:** List the specific functionalities the feature must have. Number these requirements (FR-1, FR-2, …).
5.  **Não-objetivos (fora de escopo):** Clearly state what this feature will *not* include to manage scope.
6.  **Considerações de design (opcional):** UI/UX for CLI (Rich), gateway messaging, or other UX constraints.
7.  **Considerações técnicas (opcional):**
    *   Mention known technical constraints, dependencies, or suggestions.
    *   **Consult:** [STRATEGY.md](../../docs/STRATEGY.md) for architecture, phases, and stack (Python 3.11+, `cursor-sdk`, `pytest`, `ruff`, `uv`).
    *   **Consult:** [DECISIONS.md](../../docs/DECISIONS.md) for accepted ADRs (config, sessions, facade, testing, etc.).
    *   **Consult:** [.cursor/rules/python-best-practices.mdc](../rules/python-best-practices.mdc) for coding conventions.
8.  **Métricas de sucesso:** How will the success of this feature be measured?
9.  **Perguntas em aberto:** List any remaining questions or areas needing further clarification.
10. **Implementation Tasks (§10):** Definition of Done, task table, sub-task checklists, and demo commands — aligned with [docs/prd/README.md](../../docs/prd/README.md).
11. **Desenvolvimento — TDD e retroalimentação (§11):** Mandatory per [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md):
    *   **TDD:** For each FR, specify which pytest test to write first (failing → implement → green). Prefer unit tests with fakes; integration tests per [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md).
    *   **Retroalimentação:** After PRD-N is done, checklist to update PRD-(N+1) §7, §9, and §11 with learnings (SDK quirks, timings, deps, risks). State the target PRD explicitly (e.g. PRD-000 → revisar PRD-001).
    *   Placeholder bullets for learnings to fill during development.

## Target Audience

Assume the primary reader of the PRD is a **junior developer**. Therefore, requirements should be explicit, unambiguous, and avoid jargon where possible. Provide enough detail for them to understand the feature's purpose and core logic.

## Output

*   **Format:** Markdown (`.md`) with YAML frontmatter
*   **Location:** `docs/prd/`
*   **Filename:** `PRD-XXX-[feature-name].md` (e.g. `PRD-001-facade.md`)

## Final instructions

1. Do NOT start implementing the PRD
2. Make sure to ask the user clarifying questions
3. Take the user's answers to the clarifying questions and improve the PRD
