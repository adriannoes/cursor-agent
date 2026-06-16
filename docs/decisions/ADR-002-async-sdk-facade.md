---
id: ADR-002
title: AsyncSdkFacade com Protocol e FakeSdkFacade
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [architecture, facade, testing, phase-1]
related:
  - path: ../contracts/async-sdk-facade.md
    role: implements
  - path: ../STRATEGY.md
    section: "3.2"
  - path: ../prd/PRD-001-facade.md
    role: implements
  - path: ADR-005-testing-strategy.md
    role: see-also
---

# ADR-002: `AsyncSdkFacade` com `Protocol` e `FakeSdkFacade`

## Contexto

Todo acesso ao `cursor-sdk` deve passar por uma única facade (`sdk_facade.py`). CLI, gateway e cron compartilham a mesma API async. Testes precisam rodar sem `CURSOR_API_KEY` na maioria dos casos.

## Decisão

1. Definir `SdkFacade` como `typing.Protocol` com contrato em [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md).
2. Implementar `AsyncSdkFacade` como adapter real sobre `AsyncClient.launch_bridge`.
3. Implementar `FakeSdkFacade` para testes unitários (pool, commands, session store).
4. Um `AsyncClient` por processo; dispose no shutdown (ver [ADR-021](ADR-021-graceful-shutdown.md)).

## Opções consideradas

### Opção A — Protocol + implementação + fake (escolhida)

| Prós | Contras |
|------|---------|
| ~80% dos testes sem API key | Tipos duplicados se SDK mudar |
| Ports & adapters; padrão maduro | Mais arquivos iniciais |

### Opção B — Wrapper fino sem Protocol

| Prós | Contras |
|------|---------|
| Menos código | CI frágil; difícil testar pool/locks |
| Direto ao SDK | Dev lento sem integração constante |

### Opção C — Gravação VCR de streams SDK

| Prós | Contras |
|------|---------|
| Replay offline | Cassettes quebram com updates do SDK |
| Testa SDK real | Manutenção alta |

## Consequências

### Positivas

- Contrato estável isolado de breaking changes do SDK.
- Testes rápidos e determinísticos em PRs.

### Negativas

- Manter `FakeSdkFacade` alinhado ao contrato quando SDK evoluir.

## Referências

- [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md)
- [Cursor Python SDK](https://cursor.com/docs/sdk/python)
