---
id: ADR-003
title: Proibir resume cross-runtime
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [sessions, runtime, sdk, phase-1]
related:
  - path: ../STRATEGY.md
    section: "2.1"
  - path: ../STRATEGY.md
    section: "4"
  - path: ../prd/PRD-002-session-store.md
    role: implements
  - path: ADR-004-session-key-workspace.md
    role: see-also
---

# ADR-003: Proibir resume cross-runtime

## Contexto

O SDK detecta runtime pelo prefixo do `agent_id` (`bc-` = cloud, resto = local). Persistência local é **workspace-scoped**. O schema SQLite já tem coluna `runtime`, mas as regras não estavam definidas.

## Decisão

`/resume` só funciona se `session.runtime == config.runtime.mode` atual.

- Mismatch → erro claro + sugerir `/new`.
- Cron cloud grava `runtime: cloud` e **nunca** compartilha `session_key` com chat.
- `agent_id` é imutável por sessão; mudança de runtime exige `/new`.

## Opções consideradas

### Opção A — Proibir cross-runtime (escolhida)

| Prós | Contras |
|------|---------|
| Previsível; evita erros obscuros do SDK | Não “continua” job cloud no CLI local |
| Usa coluna `runtime` existente | |

### Opção B — Permitir com warning

| Prós | Contras |
|------|---------|
| Flexível | UX confusa; erros difíceis de debugar |

### Opção C — Dois comandos (`/resume` e `/resume-cloud`)

| Prós | Contras |
|------|---------|
| Explícito | Mais comandos e documentação |

## Consequências

### Positivas

- Comportamento determinístico em CLI, gateway e cron.
- Alinhado com SDK (runtime auto-detectado no resume).

### Negativas

- Usuário não retoma sessão cloud no laptop sem criar nova sessão local.

## Referências

- [STRATEGY.md §4](../STRATEGY.md#4-topologia-de-deploy)
- [Cursor SDK — Resuming agents](https://cursor.com/docs/sdk/python)
