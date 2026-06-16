---
id: ADR-009
title: Títulos de sessão — truncar primeira mensagem
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [sessions, ux, phase-1]
related:
  - path: ../STRATEGY.md
    section: "8"
  - path: ../prd/PRD-002-session-store.md
    role: implements
---

# ADR-009: Títulos de sessão — truncar primeira mensagem

## Contexto

Schema SQLite tem `title TEXT` sem mecanismo de preenchimento.

## Decisão

**MVP (Fase 1, [PRD-002](../prd/PRD-002-session-store.md) FR-5):** ao criar sessão ou no primeiro turn do usuário, `title = first_user_message[:60]` (strip, ellipsis se truncado).

**Evolução (Fase 5 / backlog):** prompt interno após 1º turn para título semântico (custo extra de tokens).

Comando manual `/title <texto>` é um slash command e fica diferido para a Fase 4 ou backlog, conforme não-objetivos de [PRD-004](../prd/PRD-004-slash-commands.md).

## Opções consideradas

### Opção A — Truncar 1ª mensagem (escolhida para MVP)

| Prós | Contras |
|------|---------|
| Zero custo de API | Títulos pobres em `sessions list` |

### Opção B — Prompt interno após 1º turn

| Prós | Contras |
|------|---------|
| Títulos úteis | +1 turn de tokens |

### Opção C — Manual `/title` apenas

| Prós | Contras |
|------|---------|
| Controle total | Pouco usado; listas vazias |

## Consequências

### Positivas

- `cursor-agent sessions list` útil desde Fase 1.

### Negativas

- Títulos longos ou genéricos até evolução.

## Referências

- [prd/PRD-002-session-store.md](../prd/PRD-002-session-store.md)
