---
id: ADR-008
title: AgentBusyError no gateway — rejeitar com mensagem
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [gateway, concurrency, phase-3]
related:
  - path: ../STRATEGY.md
    section: "2.3"
  - path: ../prd/PRD-002-session-store.md
    role: implements
  - path: ../prd/PRD-006-gateway-core.md
    role: implements
---

# ADR-008: `AgentBusyError` no gateway — rejeitar com mensagem

## Contexto

`SessionAgentPool` usa lock por `session_key`. Se usuário envia mensagem durante run ativo, o comportamento no gateway não estava definido.

## Decisão

**MVP (Fase 3):** rejeitar inbound com mensagem amigável:

> Estou processando sua mensagem anterior. Aguarde ou envie /stop.

- Não enfileirar automaticamente.
- `/stop` cancela run ativo (`run.cancel()`).
- Fila FIFO por `session_key` fica no [BACKLOG-PHASE5](../BACKLOG-PHASE5.md) se houver demanda.

### Modo de lock por entry point

O `SessionAgentPool` usa `asyncio.Lock` por `session_key`, mas o **modo de aquisição** difere entre CLI e gateway:

| Entry point | Modo | Comportamento |
|-------------|------|---------------|
| **CLI** | `await lock.acquire()` (bloqueante) | Aguarda fim do run ou `/stop`; não levanta `AgentBusyError` |
| **Gateway** | `lock.acquire(blocking=False)` / `try_acquire` | Se lock ocupado → `AgentBusyError` → adapter envia mensagem amigável |

A facade **não** levanta `AgentBusyError`; responsabilidade exclusiva do pool ([STRATEGY §2.3](../STRATEGY.md#23-concorrência-sessionagentpool)).

## Opções consideradas

### Opção A — Rejeitar com mensagem (escolhida)

| Prós | Contras |
|------|---------|
| Simples; sem fila oculta | Usuário precisa reenviar |
| Evita reordenação de respostas | |

### Opção B — Fila FIFO (1 msg)

| Prós | Contras |
|------|---------|
| UX melhor | Complexidade; timeout; memória |
| | Risco de fila infinita |

### Opção C — Coalescing (descarta intermediárias)

| Prós | Contras |
|------|---------|
| Bom para spam | Perde mensagens |

## Consequências

### Positivas

- Comportamento previsível e fácil de testar com `FakeSdkFacade`.

### Negativas

- UX inferior a fila para usuários rápidos no chat.

## Referências

- [STRATEGY.md §2.3](../STRATEGY.md#23-concorrência-sessionagentpool)
- [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md) — fila como evolução
