---
id: ADR-004
title: session_key composto com workspace_hash
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [sessions, workspace, phase-1]
related:
  - path: ../STRATEGY.md
    section: "2.1"
  - path: ../prd/PRD-002-session-store.md
    role: implements
  - path: ADR-003-cross-runtime-resume.md
    role: see-also
---

# ADR-004: `session_key` composto com `workspace_hash`

## Contexto

`session_key = telegram:{chat_id}` ignorava workspace. Mudar `cwd` no config poderia retomar conversa de outro projeto. O SDK persiste estado local por workspace.

## Decisão

Formato composto:

```text
cli:{profile}:{workspace_hash}
telegram:{chat_id}:{workspace_hash}
```

- `workspace_hash = sha256(abs(cwd))[:8]`
- `profile` default `default` (CLI); futuro `CURSOR_AGENT_PROFILE` (Fase 5).
- `/resume` sem id → última sessão do `session_key` **atual** (inclui hash).

Atualizar exemplos em STRATEGY.md (substitui `cli:default` simples quando workspace implícito).

## Opções consideradas

### Opção A — session_key composto (escolhida)

| Prós | Contras |
|------|---------|
| Mudar cwd não contamina sessão antiga | `/resume` sem id surpreende se cwd mudou |
| Alinha com SDK workspace-scoped | Keys mais longas |

### Opção B — session_key simples + validação no resolve

| Prós | Contras |
|------|---------|
| Keys legíveis (`telegram:12345`) | Check extra em toda resolução |

### Opção C — Workspace só em metadata

| Prós | Contras |
|------|---------|
| Menor mudança no plano | Fácil confundir sessões entre projetos |

## Consequências

### Positivas

- Isolamento por projeto/workspace em CLI e gateway.
- `sessions list` pode filtrar por workspace sem ambiguidade.

### Negativas

- Usuário precisa entender que mudar `cwd` = novo namespace de sessões.

## Referências

- [STRATEGY.md §2.1](../STRATEGY.md#21-modelo-de-sessão-dupla-persistência)
- [prd/PRD-002-session-store.md](../prd/PRD-002-session-store.md)
