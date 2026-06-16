# Documentação — cursor-agent

Hub de documentação do repositório. Para agentes de IA, o ponto de entrada principal é **[AGENTS.md](../AGENTS.md)** na raiz do repo.

Agente *clean-room* inspirado no **comportamento** do [Hermes Agent](https://github.com/NousResearch/hermes-agent) e em padrões de gateway do [OpenClaw](https://github.com/openclaw/openclaw). Pode estudar docs **e** codebases de referência para entender soluções — **zero código copiado**; reimplementação com [Cursor Python SDK](https://cursor.com/docs/sdk/python) + **Composer 2.5**. Projetos relacionados do mesmo autor (ex.: shellclaw) são **separados** — ver [STRATEGY.md §1.4](STRATEGY.md#14-relação-com-outros-projetos).

---

## Para agentes de IA

| Documento | Descrição |
|-----------|-----------|
| **[AGENTS.md](../AGENTS.md)** | Índice mestre — leia primeiro em toda nova sessão |
| [prd/README.md](prd/README.md) | PRDs, ordem de execução e fluxo TDD |
| [engineering/tasks/README.md](../engineering/tasks/README.md) | Índice mestre de planos de tarefas (separado dos PRDs) |

---

## Estratégia e decisões

| Documento | Descrição |
|-----------|-----------|
| [STRATEGY.md](STRATEGY.md) | Visão, arquitetura, roadmap Fases 0–4 |
| [DECISIONS.md](DECISIONS.md) | Índice de Architecture Decision Records |
| [decisions/](decisions/) | ADRs individuais (ADR-001 … ADR-023) |
| [BACKLOG-PHASE5.md](BACKLOG-PHASE5.md) | Backlog pós-MVP |

---

## Requisitos e implementação

| Documento | Descrição |
|-----------|-----------|
| [prd/](prd/) | Product Requirements Documents (PRD-000 … PRD-010) |
| [contracts/](contracts/) | Contratos técnicos entre componentes |
| [gateway-security.md](gateway-security.md) | Threat model do gateway de mensagens |
| [prompts/](prompts/) | Prompts reutilizáveis |

---

## Ferramentas Cursor

| Caminho | Descrição |
|---------|-----------|
| [.cursor/commands/](../.cursor/commands/) | Comandos: PRD, generate-tasks, development, code-review |
| [.cursor/rules/](../.cursor/rules/) | Regras persistentes para agentes |
