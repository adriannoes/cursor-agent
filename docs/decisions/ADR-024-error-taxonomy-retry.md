---
id: ADR-024
title: Taxonomia de erros e retry
status: accepted
date: 2026-06-15
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [errors, retry, facade, phase-1]
related:
  - path: ../STRATEGY.md
    section: "3.2"
    role: see-also
  - path: ../contracts/async-sdk-facade.md
    role: spec
  - path: ADR-002-async-sdk-facade.md
    role: see-also
  - path: ADR-008-agent-busy-gateway.md
    role: see-also
  - path: ../DECISIONS.md
    role: index
  - path: ../prd/PRD-001-facade.md
    role: implements
---

# ADR-024: Taxonomia de erros e retry

## Contexto

A facade precisa mapear falhas do SDK e da rede em exceções tipadas com semântica de retry previsível para CLI, gateway e cron. `AgentBusyError` já está definido em [ADR-008](ADR-008-agent-busy-gateway.md) como responsabilidade exclusiva do `SessionAgentPool`, não da facade.

## Decisão

### 1. Hierarquia `CursorAgentError`

Classe base em `cursor_agent/errors.py` (ou módulo equivalente na Fase 1):

| Subclasse | Quando | `is_retryable` |
|-----------|--------|----------------|
| `AuthError` | API key inválida ou expirada | `False` |
| `ConfigError` | Parâmetros inválidos antes do run | `False` |
| `NetworkError` | Timeout, conexão reset, 5xx transitório | `True` |
| `TimeoutError` | Run ou bridge excedeu limite configurado | `True` |
| `InvalidAgentError` | `agent_id` inexistente ou resume impossível | `False` |

Atributos comuns:

- `is_retryable: bool`
- `retry_after: float | None` — segundos sugeridos pelo upstream (header `Retry-After` ou equivalente SDK)

### 2. Política de retry

- Retry **somente** se `CursorAgentError.is_retryable` é `True`.
- Honrar `retry_after` quando presente; caso contrário backoff exponencial com jitter: `min(2**attempt, 30)` segundos.
- **Máximo 3 tentativas** por operação (`create_agent`, `resume_agent`, `send` pré-run).
- Falhas **após** o run iniciar → `RunResult.status == ERROR`; **sem** retry automático do turn inteiro (camada CLI pode oferecer retry manual).

### 3. Onde vivem as exceções

| Exceção | Módulo | Quem levanta |
|---------|--------|--------------|
| `CursorAgentError` (+ subclasses) | `cursor_agent/errors.py` | `AsyncSdkFacade` ao mapear erros SDK/rede |
| `AgentBusyError` | `cursor_agent/errors.py` (tipo compartilhado) | **`SessionAgentPool` apenas** ([ADR-008](ADR-008-agent-busy-gateway.md)) |
| `RunResult` com `CANCELLED` | contrato facade | `send` após `cancel()` bem-sucedido |

A facade **nunca** levanta `AgentBusyError`. Testes do pool usam `FakeSdkFacade` com `send` longo (gancho `asyncio.Event`) para simular run em andamento — ver [contrato §8](../contracts/async-sdk-facade.md#8-fakesdkfacade-testes).

## Opções consideradas

### Opção A — Hierarquia tipada + retry na facade (escolhida)

| Prós | Contras |
|------|---------|
| Exit codes CLI previsíveis (1 vs 2) | Mais tipos para manter |
| Gateway pode logar categoria sem parse de string | |

### Opção B — Exceção genérica + código string

| Prós | Contras |
|------|---------|
| Menos classes | Agentes e humanos inferem retry por convenção frágil |

## Consequências

### Positivas

- Contrato [async-sdk-facade.md](../contracts/async-sdk-facade.md) e [PRD-001 FR-7](../prd/PRD-001-facade.md) alinhados.
- Retry isolado na facade; busy state isolado no pool.

### Negativas

- Mapeamento SDK → subclasses precisa atualizar quando o SDK evoluir.

## Referências

- [contracts/async-sdk-facade.md §3](../contracts/async-sdk-facade.md#3-erros-e-exit-codes)
- [ADR-008 — AgentBusyError](ADR-008-agent-busy-gateway.md)
- [ADR-002 — AsyncSdkFacade](ADR-002-async-sdk-facade.md)
