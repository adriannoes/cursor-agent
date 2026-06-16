---
id: ADR-016
title: Caminho de memória v1 para Honcho MCP
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [memory, honcho, phase-5]
related:
  - path: ADR-010-memory-v1.md
    role: extends
  - path: ../BACKLOG-PHASE5.md
    section: "Orquestração"
---

# ADR-016: Caminho memória v1 → Honcho MCP

## Contexto

Fase 4 entrega `MEMORY.md` + `USER.md`. BACKLOG prevê Honcho MCP (Q4). Migração não estava definida.

## Decisão

1. **v1 (Fase 4):** arquivos locais — [ADR-010](ADR-010-memory-v1.md).
2. **v2 (Fase 5 Q4+):** Honcho via MCP — **não** remove v1 automaticamente.
3. **Coexistência:** config `memory.backend: files | honcho | both` (default `files`).
4. **Promover Honcho** só após session FTS estável (Q3) ou necessidade de memória semântica comprovada.
5. Export v1 → Honcho: script one-shot `cursor-agent memory migrate` (backlog).

## Opções consideradas

### Migração incremental v1 → v2 (escolhida)

| Prós | Contras |
|------|---------|
| Sem big-bang | Dois sistemas temporários |

### Pular Honcho (rejeitada para longo prazo)

| Prós | Contras |
|------|---------|
| Menos complexidade | Sem memória semântica |

### Honcho substitui v1 na Fase 4 (rejeitada)

| Prós | Contras |
|------|---------|
| Um sistema | Atrasa MVP; dependência MCP |

## Consequências

### Positivas

- MVP simples; evolução planejada.
- Usuários podem ficar em files-only.

### Negativas

- Manutenção de dois backends se `both`.

## Referências

- [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md)
- [ADR-010](ADR-010-memory-v1.md)
