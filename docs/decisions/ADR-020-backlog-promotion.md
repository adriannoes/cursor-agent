---
id: ADR-020
title: Critérios de promoção backlog Fase 5 para PRD
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [process, backlog, phase-5]
related:
  - path: ../BACKLOG-PHASE5.md
    role: implements
  - path: ../prd/
    role: see-also
  - path: ADR-014-tool-profiles-mvp.md
    role: see-also
---

# ADR-020: Critérios promoção backlog → PRD

## Contexto

BACKLOG-PHASE5 é catálogo, não sprint. Faltava critério objetivo para promover itens.

## Decisão

Item do backlog vira PRD em `docs/prd/` quando **todos** forem verdade:

1. **DoD da fase anterior** ✅ (ex.: Telegram E2E antes de Discord).
2. **Dependências técnicas** resolvidas (ex.: `PlatformAdapter` existe).
3. **PRD draft** com owner, estimativa S/M/L, tasks e DoD específico.
4. **ADR** se decisão nova (ou referência a ADR existente).
5. **Capacidade:** máximo **2 épicos ativos** por dev.

**Colunas no BACKLOG** (adicionadas): `Depende de`, `Promover quando`, `PRD alvo`, `Esforço`.

**Exemplos:**

| Item | Promover quando | PRD |
|------|-----------------|-----|
| Discord | Telegram estável 2 semanas | PRD-011 (futuro) |
| `full` profile | MCP github+search escolhidos | PRD-012 (futuro) |
| Honcho | ADR-016 + demanda semântica | PRD-0xx |

## Opções consideradas

### Critérios explícitos (escolhida)

| Prós | Contras |
|------|---------|
| Evita scope creep | Burocracia leve |

### Trimestre fixo sem gate (rejeitada)

| Prós | Contras |
|------|---------|
| Simples | Q1 com 4 épicos grandes |

## Consequências

### Positivas

- BACKLOG → execução rastreável.
- Fase 5 não bloqueia MVP.

### Negativas

- Itens Q1 podem deslizar.

## Referências

- [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md)
- [DECISIONS.md](../DECISIONS.md)
