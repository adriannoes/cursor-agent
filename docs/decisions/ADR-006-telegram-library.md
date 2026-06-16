---
id: ADR-006
title: Biblioteca Telegram aiogram 3.x
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [gateway, telegram, phase-3]
related:
  - path: ../STRATEGY.md
    section: "5.1"
  - path: ../prd/PRD-007-telegram-adapter.md
    role: implements
  - path: ADR-012-telegram-chunking.md
    role: see-also
---

# ADR-006: Biblioteca Telegram — aiogram 3.x

## Contexto

Fase 3 precisa de adapter Telegram async. STRATEGY listava `aiogram` ou `python-telegram-bot` sem decisão. O stack é async-first (`AsyncSdkFacade`, APScheduler na Fase 4).

## Decisão

Usar **aiogram 3.x** (pin em `pyproject.toml`). Abstrair atrás de `PlatformAdapter` para Discord/Slack no backlog.

## Opções consideradas

### Opção A — aiogram 3.x (escolhida)

| Prós | Contras |
|------|---------|
| Async nativo — mesmo loop que facade + APScheduler | Curva de routers/middleware |
| Ativo em 2026 (Bot API 10.0+) | Menos stars que PTB |
| Padrão para bots + scheduler no mesmo processo | |

### Opção B — python-telegram-bot 21.x

| Prós | Contras |
|------|---------|
| Ecossistema maior, mais exemplos | Mais boilerplate com asyncio puro |
| Bom para bots pequenos | Integração APScheduler exige mais cuidado |

## Consequências

### Positivas

- Gateway, cron e SDK no mesmo event loop sem thread pools.
- `AsyncIOScheduler` (Fase 4) encaixa naturalmente.

### Negativas

- Time precisa aprender routers/filters do aiogram 3.

## Referências

- [aiogram docs](https://docs.aiogram.dev/)
- [prd/PRD-007-telegram-adapter.md](../prd/PRD-007-telegram-adapter.md)
