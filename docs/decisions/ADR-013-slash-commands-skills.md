---
id: ADR-013
title: Slash commands unificados e namespace de skills
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [commands, skills, phase-2]
related:
  - path: ../STRATEGY.md
    section: "9.1"
  - path: ../STRATEGY.md
    section: "12.1"
  - path: ../prd/PRD-004-slash-commands.md
    role: implements
  - path: ../prd/PRD-009-skills.md
    role: see-also
---

# ADR-013: `/new` unificado e namespace de skills

## Contexto

STRATEGY listava `/new` e `/reset` como equivalentes sem definir diferença. `/<skill-name>` pode colidir com slash commands built-in.

## Decisão

### `/new` vs `/reset`

- **Comando canônico:** `/new`
- **`/reset`** é alias documentado em `/help` → mesma implementação
- Hermes-style “reset sem novo row” **não** implementado no MVP

### Resolução de input

Ordem no `CommandRouter`:

1. Comandos built-in (denylist reservada: `help`, `quit`, `new`, `reset`, `resume`, `stop`, `model`, `retry`, `usage`, `compress`, `skills`, `memory`, `personality`, `title`)
2. Skills (`/<skill-name>` se existir em `.cursor/skills/`)
3. Mensagem livre → agente

## Opções consideradas

### Unificar /new (escolhida)

| Prós | Contras |
|------|---------|
| Menos confusão | Diferente de possível semântica Hermes |

### Diferenciar /reset (rejeitada)

| Prós | Contras |
|------|---------|
| Paridade Hermes | Mais docs; mesmo row vs novo row confunde |

### Skills: prefixo /skill:name (rejeitada)

| Prós | Contras |
|------|---------|
| Sem colisão | UX pior que Hermes/Cursor |

## Consequências

### Positivas

- Router determinístico e testável.
- Skills ergonômicas com proteção de namespace.

### Negativas

- Skill não pode se chamar `help` etc.

## Referências

- [STRATEGY.md §9.1](../STRATEGY.md#91-slash-commands)
- [prd/PRD-009-skills.md](../prd/PRD-009-skills.md)
