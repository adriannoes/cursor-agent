---
id: backlog-phase5
title: Fase 5 — Backlog de paridade Hermes
status: living
date: 2026-06-12
related:
  - path: STRATEGY.md
    section: "13"
  - path: DECISIONS.md
  - path: prd/README.md
adrs:
  - ADR-014
  - ADR-015
  - ADR-016
  - ADR-020
---

# Fase 5 — Backlog de paridade Hermes

> Catálogo e roadmap **pós Fase 4**. Não bloqueia o MVP.  
> Decisões: [DECISIONS.md](DECISIONS.md) · Promoção → PRD: [ADR-020](decisions/ADR-020-backlog-promotion.md)

Ver também: [STRATEGY.md](STRATEGY.md) · [prd/README.md](prd/README.md)

---

## Objetivo

Priorizar o que do Hermes ainda vale implementar sobre o Cursor SDK:

1. Tools sem equivalente direto (MCP vs custom)
2. Gateway multi-plataforma
3. Backends de terminal e features avançadas

---

## O que não reimplementar (SDK nativo)

| Capacidade | Tool SDK (representativa) |
|------------|---------------------------|
| Shell | `shell` |
| Ler / escrever / editar | `read`, `write`, `edit` |
| Busca | `grep`, `glob`, `ls`, `semSearch` |
| MCP externo | `mcp` |
| Subagent | `task` + `.cursor/agents/*.md` |

Inventário factual da conta: script `examples/tools_list.py` do spike (**Fase 0**, [PRD-000](prd/PRD-000-sdk-spike.md)). O comando de CLI `cursor-agent tools list` só passa a existir a partir do PRD-003.

---

## Legenda de estratégia

| Código | Significado |
|--------|-------------|
| `SDK` | Já coberto pelo Cursor SDK |
| `MCP` | MCP server existente |
| `CONFIG` | Arquivo / config, sem tool |
| `CUSTOM` | Tool ou serviço próprio |
| `SKIP` | Fora de escopo |
| `LATER` | Backlog |

---

## Critérios de promoção → PRD

Item vira PRD quando ([ADR-020](decisions/ADR-020-backlog-promotion.md)):

1. DoD da fase anterior ✅
2. Dependências técnicas resolvidas
3. PRD draft com owner + estimativa
4. ADR se decisão nova
5. Máx. 2 épicos ativos por dev

---

## Catálogo de tools Hermes

### Web e pesquisa

| Tool | Estratégia | Esforço | Depende de | Promover quando | PRD alvo |
|------|------------|---------|------------|-----------------|----------|
| `web_search` | `MCP` | Baixo | Fase 4 | Perfil `full` definido | PRD-012 (futuro) |
| `web_extract` | `MCP` / `SDK` | Baixo | — | Demanda real | — |
| `x_search` | `MCP` / `CUSTOM` | Médio | — | API xAI disponível | — |

### Terminal e arquivos

| Tool | Estratégia | Notas |
|------|------------|-------|
| `terminal` | `SDK` | |
| `process` | `CUSTOM` | BG jobs — alto esforço; justificar vs SDK `shell` |
| `read_file`, `write_file`, `patch`, `search_files` | `SDK` | |

**Backends de terminal:**

| Backend | Estratégia |
|---------|------------|
| `local` | `SDK` |
| `docker` | `LATER` — MCP ou wrapper |
| `ssh` | `LATER` — cloud agent |
| `modal`, `daytona` | `LATER` — cloud Cursor |
| `singularity` | `SKIP` |

### Browser

Todas via **MCP** (Playwright, Browser DevTools). Não reimplementar.

### Mídia

| Tool | Estratégia |
|------|------------|
| `vision_analyze` | `SDK` (imagens em `UserMessage`) |
| `image_generate`, `text_to_speech` | `MCP` |
| Voice memos (gateway) | `CUSTOM` — Fase 5+ |

### Orquestração

| Tool | Estratégia | Esforço | Depende de | Promover quando | PRD alvo |
|------|------------|---------|------------|-----------------|----------|
| `todo` | `CONFIG` | Baixo | — | — | — |
| `clarify` | `CUSTOM` — callback CLI/gateway | Médio | Fase 4 | Demanda UX de aprovação humana | PRD-0xx (futuro) |
| `execute_code` | `SDK` (shell) | — | — | — | — |
| `delegate_task` | `SDK` | — | — | — | — |
| `session_search` | `CUSTOM` — SQLite FTS | Alto | SessionStore | Fase 4 ✅ + demanda busca | PRD-0xx (futuro) |
| `memory` | `CONFIG` | — | Fase 4 | já no roadmap MVP | [PRD-008](prd/PRD-008-memory-v1.md) |
| `cronjob` | `CUSTOM` | — | Fase 4 | já no roadmap MVP | [PRD-010](prd/PRD-010-cron.md) |
| `send_message` | `CUSTOM` — tool interna do gateway | — | PRD-006 | já no roadmap MVP | — |

### Integrações

| Grupo | Estratégia |
|-------|------------|
| `ha_*` | `MCP` |
| MCP dinâmico | `SDK` |
| `spotify` | `MCP` / `SKIP` |
| `discord` / `discord_admin` | Gateway + `MCP` |
| `messaging` | `CUSTOM` |

---

## Perfis de tools (pós-MVP)

O SDK **não filtra** tools nativas; perfis controlam **MCP** e **hooks**.

**MVP (Fases 0–4):** apenas `coding` e `messaging` — [ADR-014](decisions/ADR-014-tool-profiles-mvp.md).

```yaml
tool_profile: coding   # MVP: coding | messaging

# Pós-MVP (Q1+):
profiles:
  minimal:
    mcp_servers: []
  coding:
    mcp_servers: ["github"]
  full:
    mcp_servers: ["github", "brave-search", "playwright"]
  messaging:
    mcp_servers: []
```

| Preset de toolset | cursor-agent |
|-------------------|---------------|
| `cli` | `coding` + hooks moderados |
| `telegram` | `messaging` + [gateway-security.md](gateway-security.md) |
| `safe` | hooks deny + allowlist shell |
| `mcp-<name>` | entrada em `mcp_servers` |

---

## Gateway — plataformas (backlog)

> **Gate obrigatório:** Fase 2b (PRD-005) deve estar concluída antes de qualquer plataforma pública.

| Prioridade | Plataforma | Depende de | Promover quando | PRD alvo |
|------------|------------|------------|-----------------|----------|
| P0 | Telegram (Fase 3) | [PRD-005](prd/PRD-005-messaging-profile.md), [PRD-006](prd/PRD-006-gateway-core.md) | já no roadmap MVP | [PRD-007](prd/PRD-007-telegram-adapter.md) |
| P1 | Discord, Slack | PlatformAdapter | Telegram E2E 2 semanas | PRD-011 (futuro) |
| P2 | WhatsApp, Signal | — | P1 estável | — |
| P3 | Matrix, Mattermost, Email | — | Demanda | — |
| P4 | WeCom, Feishu, DingTalk, LINE | — | Demanda | — |

---

## Matriz de paridade (features)

| Feature Hermes | Esforço | Abordagem | ADR | Promover quando | PRD alvo |
|----------------|---------|-----------|-----|-----------------|----------|
| Multi-provider LLM | — | **Não** — Composer 2.5 | — | — | — |
| Context compression avançada | Médio | `/compress` + novo agent | [ADR-011](decisions/ADR-011-compress-flow.md) | — | [PRD-004](prd/PRD-004-slash-commands.md) |
| FTS5 session search | Alto | SessionStore | — | Fase 4 ✅ + demanda busca | PRD-0xx (futuro) |
| Learning loop / skills auto | Muito alto | Fora de escopo | — | — | — |
| Honcho | Alto | MCP | [ADR-016](decisions/ADR-016-honcho-memory-path.md) | ADR-016 + demanda semântica | PRD-0xx (futuro) |
| TUI `textual` | Alto | **Stretch goal** Q4 | [ADR-015](decisions/ADR-015-tui-stretch-goal.md) | Fase 4 ✅ + capacidade Q4 | PRD-0xx (futuro) |
| ACP (IDE) | Médio | Avaliar SDK | — | — | — |
| Batch trajectories | Médio | Script + SDK | — | — | — |
| Profiles (`-p`) | Baixo | `CURSOR_AGENT_PROFILE` | [ADR-004](decisions/ADR-004-session-key-workspace.md) | — | — |
| Filesystem rollback | Alto | git snapshots | — | — | — |
| Voice mode | Alto | TTS/STT | — | — | — |
| Plugins pip | Alto | Preferir MCP | — | — | — |
| AgentBusy queue | Médio | Fila FIFO (backlog) | [ADR-008](decisions/ADR-008-agent-busy-gateway.md) | Demanda UX gateway | PRD-0xx (futuro) |

---

## Roadmap trimestral sugerido

| Trimestre | Foco | Depende de |
|-----------|------|------------|
| **Q1** | MCP (search, GitHub, Playwright); perfil `full`; `clarify` | Fase 4 ✅ |
| **Q2** | Discord + Slack | PRD-007 estável |
| **Q3** | `process` tool; session FTS; docker experimental | Q2 ou demanda |
| **Q4** | TUI (stretch); voice; Honcho MCP | [ADR-015](decisions/ADR-015-tui-stretch-goal.md), [ADR-016](decisions/ADR-016-honcho-memory-path.md) |

---

## Checklist para nova tool custom

1. [ ] Existe equivalente SDK?
2. [ ] Existe MCP maduro?
3. [ ] Precisa UX humana (clarify/approve)?
4. [ ] Custo de manutenção justifica vs cloud agent?
5. [ ] Último recurso: bridge TypeScript `customTools`
6. [ ] Atende [ADR-020](decisions/ADR-020-backlog-promotion.md)?

---

*Atualizar quando itens forem promovidos a sprint/PRD.*
