---
id: ADR-010
title: Memória v1 — injeção e flag memory_injected
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [memory, phase-4]
related:
  - path: ../STRATEGY.md
    section: "2.6"
  - path: ../prd/PRD-008-memory-v1.md
    role: implements
  - path: ADR-016-honcho-memory-path.md
    role: see-also
---

# ADR-010: Memória v1 — injeção e flag `memory_injected`

## Contexto

Memória v1: `MEMORY.md` + `USER.md`, cap 8 KB no primeiro turn. Ordem de truncamento e comportamento em `/resume` não estavam definidos.

## Decisão

1. **Ordem de prioridade:** `USER.md` até 4 KB, depois `MEMORY.md` com o restante do budget (8 KB total).
2. **Truncar do fim** do arquivo se exceder quota da seção.
3. **Injetar apenas** no primeiro turn após `/new` ou `/resume` quando `metadata.memory_injected != true`.
4. Após injeção, setar `metadata.memory_injected = true` no SQLite.
5. `/new` reseta flag; `/compress` **não** re-injeta (contexto já carregado no novo agent via resumo).

## Opções consideradas

### Opção A — USER prioridade + flag injected (escolhida)

| Prós | Contras |
|------|---------|
| Determinístico; economiza tokens em resume | Memória não atualiza mid-session automaticamente |

### Opção B — Ordem fixa 4+4 KB sem prioridade

| Prós | Contras |
|------|---------|
| Simples | Pode cortar USER em favor de MEMORY |

### Opção C — Injetar em todo resume

| Prós | Contras |
|------|---------|
| Sempre fresco | Duplica contexto; custo alto |

## Consequências

### Positivas

- Comportamento testável e documentado.
- USER (preferências) preservado sobre MEMORY (fatos).

### Negativas

- Atualizações a `MEMORY.md` mid-session não aparecem até `/new`.

## Referências

- [STRATEGY.md §2.6](../STRATEGY.md#26-memória-v1-fase-4)
- [prd/PRD-008-memory-v1.md](../prd/PRD-008-memory-v1.md)
