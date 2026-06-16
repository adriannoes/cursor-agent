---
id: ADR-015
title: TUI textual como stretch goal
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [ux, tui, phase-5]
related:
  - path: ../STRATEGY.md
    section: "1.3"
  - path: ../BACKLOG-PHASE5.md
    section: "Matriz de paridade"
---

# ADR-015: TUI `textual` como stretch goal

## Contexto

STRATEGY §1.3 listava TUI como não-objetivo; BACKLOG Q4 incluía TUI. Contradição documental.

## Decisão

- **MVP (Fases 0–4):** CLI Rich REPL apenas — TUI **fora de escopo**.
- **Fase 5 Q4:** TUI `textual` como **stretch goal** — promover só se MVP estável e demanda explícita.
- Atualizar STRATEGY §1.3: “TUI completa (stretch goal Fase 5, não bloqueia MVP)”.

## Opções consideradas

### Stretch goal (escolhida)

| Prós | Contras |
|------|---------|
| Alinha expectativas | Q4 pode não entregar TUI |

### Remover TUI do backlog (rejeitada)

| Prós | Contras |
|------|---------|
| Escopo menor | Perde referência Hermes |

### TUI no MVP (rejeitada)

| Prós | Contras |
|------|---------|
| UX rica | +1 sprint; duplica CLI |

## Consequências

### Positivas

- Docs consistentes; foco no gateway e CLI.

### Negativas

- Sem paridade TUI Hermes no horizonte MVP.

## Referências

- [BACKLOG-PHASE5.md — Q4](../BACKLOG-PHASE5.md#roadmap-trimestral-sugerido)
