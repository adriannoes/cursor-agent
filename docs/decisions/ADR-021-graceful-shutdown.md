---
id: ADR-021
title: Shutdown gracioso do gateway
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [gateway, ops, phase-3]
related:
  - path: ../STRATEGY.md
    section: "11"
  - path: ../prd/PRD-006-gateway-core.md
    role: implements
  - path: ADR-002-async-sdk-facade.md
    role: see-also
---

# ADR-021: Shutdown gracioso do gateway

## Contexto

Gateway long-running precisa tratar SIGINT/SIGTERM sem orphan processes ([SDK dispose](https://cursor.com/docs/sdk/python)).

## Decisão

Sequência no `gateway/runner.py`:

```text
SIGINT/SIGTERM recebido
  → parar polling Telegram (aiogram)
  → cancel runs ativos via facade (timeout 30s)
  → dispose AsyncClient / facade
  → flush logs
  → exit 0
```

- Runs que não cancelam em 30s: log warning + force dispose.
- Não aceitar novas mensagens após sinal (middleware flag `shutting_down`).

## Opções consideradas

### Cancel + dispose com timeout (escolhida)

| Prós | Contras |
|------|---------|
| Sem orphan bridge processes | Run pode ser cortado |

### Aguardar runs indefinidamente (rejeitada)

| Prós | Contras |
|------|---------|
| Não perde trabalho | Deploy travado |

### Exit imediato (rejeitada)

| Prós | Contras |
|------|---------|
| Rápido | Leak de recursos SDK |

## Consequências

### Positivas

- VPS restart seguro (systemd, Docker).
- Alinhado ADR-002 lifecycle.

### Negativas

- Resposta longa pode ser interrompida no deploy.

## Referências

- [prd/PRD-006-gateway-core.md](../prd/PRD-006-gateway-core.md)
- [ADR-002](ADR-002-async-sdk-facade.md)
