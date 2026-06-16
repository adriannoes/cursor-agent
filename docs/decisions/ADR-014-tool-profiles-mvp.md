---
id: ADR-014
title: Perfis coding e messaging no MVP
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [security, profiles, phase-2b]
related:
  - path: ../STRATEGY.md
    section: "10"
  - path: ../BACKLOG-PHASE5.md
    section: "Perfis de tools"
  - path: ADR-001-messaging-security.md
    role: see-also
  - path: ../prd/PRD-005-messaging-profile.md
    role: implements
---

# ADR-014: Perfis `coding` e `messaging` no MVP

## Contexto

BACKLOG-PHASE5 lista `minimal`, `coding`, `full`, `messaging`. MVP (Fases 0–4) precisa de escopo claro.

## Decisão

**MVP implementa apenas:**

| Perfil | MCP | Hooks | Uso |
|--------|-----|-------|-----|
| `coding` | configurável (default `[]` ou `github` futuro) | moderados (template dev) | CLI |
| `messaging` | `{}` | deny ([ADR-001](ADR-001-messaging-security.md)) | Gateway |

`minimal` e `full` → **Fase 5 Q1** quando MCP search/GitHub/Playwright forem promovidos ([ADR-020](ADR-020-backlog-promotion.md)).

Gateway **recusa subir** se `tool_profile != messaging`.

## Opções consideradas

### Só coding + messaging no MVP (escolhida)

| Prós | Contras |
|------|---------|
| Foco; não atrasa gateway | BACKLOG lista 4 perfis — doc atualizada |

### 4 perfis na Fase 2b (rejeitada)

| Prós | Contras |
|------|---------|
| Paridade cedo | Atrasa gate de segurança |

## Consequências

### Positivas

- Fase 2b entregável em 2–3 dias.
- `full` ganha definição quando MCPs forem escolhidos.

### Negativas

- Usuários avançados sem perfil `full` até Q1 pós-MVP.

## Referências

- [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md)
- [STRATEGY.md §10](../STRATEGY.md#10-fase-2b-perfil-messaging-gate-do-gateway)
