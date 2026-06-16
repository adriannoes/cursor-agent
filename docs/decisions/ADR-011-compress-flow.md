---
id: ADR-011
title: Fluxo /compress com saga e prompt versionado
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [commands, compression, phase-2]
related:
  - path: ../STRATEGY.md
    section: "9.1"
  - path: ../prompts/compress.txt
    role: implements
  - path: ../prd/PRD-004-slash-commands.md
    role: implements
---

# ADR-011: Fluxo `/compress` com saga e prompt versionado

## Contexto

`/compress` resume conversa, cria novo `agent_id`, mantém mesmo `session id`. Falha mid-flight e prompt de resumo não estavam especificados.

## Decisão

1. Prompt fixo em [prompts/compress.txt](../prompts/compress.txt) (versionado no repo).
2. **Saga leve:**
   - Setar `metadata.status = "compressing"`
   - Enviar prompt → `run.wait()` → obter resumo
   - Criar novo `agent_id`; atualizar row SQLite
   - Enviar resumo como primeira mensagem do novo agent
   - Limpar `metadata.status`
3. **Em falha:** manter `agent_id` antigo; limpar status; mensagem de erro ao usuário.
4. Não re-injetar memória v1 após compress (ver [ADR-010](ADR-010-memory-v1.md)).

## Opções consideradas

### Opção A — Saga leve + prompt versionado (escolhida)

| Prós | Contras |
|------|---------|
| Recuperável; prompt reproduzível | Estado `compressing` se crash sem cleanup |

### Opção B — Transação atômica com rollback completo

| Prós | Contras |
|------|---------|
| Mais seguro | Complexo; SDK não participa de TX SQL |

### Opção C — Prompt inline no código

| Prós | Contras |
|------|---------|
| Menos arquivos | Difícil iterar qualidade do resumo |

## Consequências

### Positivas

- Compressão auditável e testável com fake facade.
- Prompt melhorável sem mudar código.

### Negativas

- Crash durante `compressing` pode exigir limpeza manual (raro).

## Referências

- [STRATEGY.md §9.1](../STRATEGY.md#91-slash-commands)
- [prompts/compress.txt](../prompts/compress.txt)
