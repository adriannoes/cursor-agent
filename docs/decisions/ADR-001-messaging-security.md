---
id: ADR-001
title: Segurança do perfil messaging
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [security, messaging, hooks, sandbox, phase-2b]
related:
  - path: ../gateway-security.md
    role: implements
  - path: ../STRATEGY.md
    section: "10"
  - path: ../prd/PRD-005-messaging-profile.md
    role: implements
  - path: ADR-014-tool-profiles-mvp.md
    role: see-also
---

# ADR-001: Segurança do perfil `messaging`

## Contexto

O Cursor SDK **não desliga** tools nativas (`read`, `write`, `edit`, `shell`, …). Em modo headless, o agente local roda com auto-approve e, por padrão, **sem sandbox**. O perfil `messaging` (Fase 2b) é gate obrigatório antes do gateway Telegram.

Referência: [Cursor SDK — hooks e sandbox](https://cursor.com/docs/sdk/python).

## Decisão

Perfil `messaging` = **read-only sobre o workspace** (não chat puro):

1. **Hooks em camadas** — cursor-agent copia `~/.cursor-agent/hooks/messaging/` para o `cwd` do gateway na subida:
   - `preToolUse` matcher `Write|StrReplace|Delete|Task` → `permission: deny`
   - `beforeShellExecution` → denylist destrutiva + allowlist read-only (`git status`, `ls`, `cat`, …)
   - `beforeMCPExecution` → deny (redundante com MCP vazio)
   - `beforeReadFile` → deny paths sensíveis (`~/.ssh`, `.env`, `*.pem`)
2. **Sandbox SDK** — `sandbox_options.enabled: true` no perfil messaging (rede off por padrão).
3. **MCP vazio** — `mcp_servers: {}` inline no perfil messaging.
4. **Threat model documentado** em [gateway-security.md](../gateway-security.md).

## Opções consideradas

### Opção A — Hooks em camadas + sandbox + read-only (escolhida)

| Prós | Contras |
|------|---------|
| Alinha com modelo oficial do SDK (hooks = policy boundary) | Hooks são file-based; troca de perfil exige hooks no disco |
| `preToolUse` cobre edit/write | Bugs intermitentes em Windows; restart após editar `hooks.json` |
| Bot útil para Q&A sobre código via `read`/`grep` | Manutenção de scripts de hook |

### Opção B — Apenas sandbox SDK

| Prós | Contras |
|------|---------|
| Uma flag, menos scripts | **Não bloqueia edit/write** — só shell e rede |
| Rede negada por padrão | Requer bubblewrap/seatbelt; falha em alguns Linux |

### Opção C — Workspace vazio (`cwd` sandbox dir)

| Prós | Contras |
|------|---------|
| Danos limitados se hooks falharem | Perde contexto do repositório |
| Simples de auditar | Bot vira chat genérico |

### Opção D — Chat puro (deny all tools)

| Prós | Contras |
|------|---------|
| Máxima segurança | Inútil para perguntas sobre código |
| Sem hooks complexos | Desperdiça capacidades do SDK |

## Consequências

### Positivas

- Gateway Telegram com postura defensiva documentada e testável.
- Leitura de código permitida; escrita e shell destrutivo bloqueados.

### Negativas

- Hooks não são programáticos por run — perfil messaging precisa workspace de hooks dedicado.
- Sandbox não substitui hooks para file edit.

## Referências

- [gateway-security.md](../gateway-security.md)
- [STRATEGY.md §10](../STRATEGY.md#10-fase-2b-perfil-messaging-gate-do-gateway)
- [Cursor Hooks](https://cursor.com/docs/hooks)
