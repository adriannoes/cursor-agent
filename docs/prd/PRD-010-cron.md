---
id: PRD-010
title: Cron scheduler
status: draft
phase: 4
depends_on: [PRD-006, PRD-007]
adrs:
  - ADR-002
  - ADR-003
  - ADR-008
  - ADR-021
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "12.3"
  - path: ../decisions/ADR-006-telegram-library.md
    role: see-also
  - path: ../decisions/ADR-003-cross-runtime-resume.md
    role: spec
---

# PRD-010 — Cron

## 1. Introdução/Visão Geral

O cursor-agent precisa executar jobs agendados (relatórios, lembretes, batch) com agentes dedicados, opcionalmente entregando resultado via Telegram. O scheduler usa APScheduler e configuração declarativa em `~/.cursor-agent/cron/jobs.yaml`, alinhado à [Fase 4 — §12.3](../STRATEGY.md#123-cron).

**Problema:** tarefas recorrentes hoje exigem intervenção manual ou scripts externos desconectados do gateway.

**Objetivo:** jobs com `agent_id` dedicado por execução, sem compartilhar sessão de chat, com CLI de gestão e suporte a `runtime: cloud` para batch.

## 2. Objetivos

- Agendar jobs com APScheduler a partir de `jobs.yaml`.
- Garantir **um `agent_id` dedicado por job** — nunca compartilhar `session_key` com chat ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)).
- Expor `cursor-agent cron list|add|remove` para operação sem editar YAML manualmente.
- Suportar flag `runtime: cloud` em jobs de batch.
- Entregar resultado opcionalmente ao Telegram `chat_id` configurado ([PRD-007](PRD-007-telegram-adapter.md)).
- Evitar conflito de busy entre gateway e cron ([PRD-006](PRD-006-gateway-core.md), [ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).

## 3. Histórias de Usuário

- **Como** operador, **quero** `cursor-agent cron list` para ver jobs ativos, **para** auditar agendamentos sem abrir YAML.
- **Como** usuário avançado, **quero** adicionar um job com prompt e schedule, **para** automatizar tarefas recorrentes.
- **Como** usuário Telegram, **quero** receber a saída do job no meu `chat_id`, **para** não precisar do CLI.
- **Como** desenvolvedor, **quero** jobs cloud isolados com `runtime: cloud`, **para** batch sem misturar com sessões locais ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)).

## 4. Requisitos Funcionais

1. O sistema deve usar APScheduler como motor de agendamento.
2. Jobs devem ser definidos em `~/.cursor-agent/cron/jobs.yaml` com schema validado.
3. Cada execução de job deve criar ou usar **`agent_id` dedicado** — não compartilhar sessão com chat CLI ou gateway ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)).
4. Jobs com `runtime: cloud` devem gravar `runtime: cloud` na sessão e nunca compartilhar `session_key` com chat local.
5. O CLI deve implementar `cursor-agent cron list`, `cron add` e `cron remove`.
6. `cron add` deve persistir no `jobs.yaml` e recarregar o scheduler sem reiniciar o processo (quando aplicável).
7. Entrega opcional: quando `delivery.telegram.chat_id` estiver configurado, enviar resultado via adapter Telegram ([PRD-007](PRD-007-telegram-adapter.md), [ADR-006](../decisions/ADR-006-telegram-library.md)).
8. Execução do job deve passar pela mesma AsyncSdkFacade que CLI e gateway ([PRD-001](PRD-001-facade.md), [ADR-002](../decisions/ADR-002-async-sdk-facade.md)).
9. Conflito AgentBusy deve seguir política do gateway — mensagem clara, sem deadlock ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).
10. Shutdown gracioso deve cancelar jobs pendentes ou aguardar conclusão conforme [ADR-021](../decisions/ADR-021-graceful-shutdown.md).

### Critérios de aceite (DoD)

- [ ] APScheduler + `cron/jobs.yaml`
- [ ] `agent_id` dedicado por job (não compartilha chat)
- [ ] `cursor-agent cron list|add|remove`
- [ ] Flag `runtime: cloud` para batch

## 5. Fora de Escopo (Non-Goals)

- UI web para gestão de cron.
- Distribuição multi-nó (leader election) — single-process no MVP.
- Retry exponencial sofisticado ou dead-letter queue.
- Jobs que compartilham `session_key` com conversa ativa do usuário.
- Resume cross-runtime de sessões cron no CLI local ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)).

## 6. Considerações de Design

- `cron list` em tabela Rich: id, schedule, próximo disparo, runtime, destino Telegram (se houver).
- `cron add` interativo ou flags (`--schedule`, `--prompt`, `--chat-id`, `--runtime`).
- Mensagens de erro devem citar job id e campo inválido do YAML.

## 7. Considerações Técnicas

- **Dependências:** [PRD-006](PRD-006-gateway-core.md) (processo long-running, pool), [PRD-007](PRD-007-telegram-adapter.md) (delivery opcional).
- **Runtime:** [ADR-003](../decisions/ADR-003-cross-runtime-resume.md) — cron cloud isolado; `/resume` cross-runtime proibido.
- **Telegram:** [ADR-006](../decisions/ADR-006-telegram-library.md) — aiogram no mesmo event loop.
- **Facade compartilhada:** [ADR-002](../decisions/ADR-002-async-sdk-facade.md).
- **Estrutura alvo:** pacote `cron/` conforme [STRATEGY §5.2](../STRATEGY.md#52-estrutura-alvo-fase-4).
- **Aceite da fase:** cron dispara e entrega; gateway e cron sem busy conflict ([STRATEGY §12](../STRATEGY.md#12-fase-4-memória-skills-cron)).

## 8. Métricas de Sucesso

- Job de demo dispara no horário configurado e entrega mensagem no Telegram `chat_id`.
- Nenhum job compartilha `session_key` com sessão de chat ativa (verificável em testes).
- `cron list|add|remove` funcionam sem corrupção do `jobs.yaml`.
- Jobs `runtime: cloud` persistem runtime correto e não são resumíveis no CLI local.
- Gateway e cron coexistem sem deadlock em cenário de carga moderada.

## 9. Questões em Aberto

- Cron roda embutido no gateway ou processo separado `cursor-agent cron daemon`?
- Limite de frequência mínima entre disparos (mitigar custo — [STRATEGY §14](../STRATEGY.md#14-segurança-ops-riscos-dod))?
- Schema exato de `jobs.yaml` (campos obrigatórios: `id`, `schedule`, `prompt`, `runtime`?) — formalizar em contrato separado?
- Timezone default dos schedules (UTC vs local)?

## 10. Tarefas de implementação

### Definition of Done

- [ ] APScheduler + `cron/jobs.yaml` validado
- [ ] `agent_id` dedicado por job (não compartilha chat)
- [ ] `cursor-agent cron list|add|remove` operacional
- [ ] Flag `runtime: cloud` para batch
- [ ] Gateway e cron coexistem sem deadlock

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T1 | Scheduler core (APScheduler + lifecycle) | 6h | PRD-006 |
| T2 | Schema e loader `jobs.yaml` | 3h | T1 |
| T3 | CLI `cron list|add|remove` | 4h | T2 |
| T4 | Delivery Telegram opcional | 4h | PRD-007 |
| T5 | Testes (isolamento agent_id, runtime cloud, busy) | 4h | T1 |

### Demo

1. `cursor-agent cron list` — exibe jobs ativos do `jobs.yaml`.
2. Job de demo dispara no horário configurado → mensagem entregue no Telegram `chat_id`.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR scheduler | `tests/unit/test_cron_scheduler.py` — APScheduler lifecycle, add/remove | `pytest tests/unit/test_cron_scheduler.py -v` |
| FR jobs schema | `tests/unit/test_cron_jobs_loader.py` — validação `jobs.yaml` | `pytest tests/unit/test_cron_jobs_loader.py -v` |
| FR isolation | `tests/unit/test_cron_agents.py` — `agent_id` dedicado por job | `pytest tests/unit/test_cron_agents.py -v` |
| FR runtime | `tests/unit/test_cron_runtime.py` — flag `runtime: cloud` | `pytest tests/unit/test_cron_runtime.py -v` |
| FR coexist | `tests/unit/test_cron_gateway_coexist.py` — sem deadlock com pool | `pytest tests/unit/test_cron_gateway_coexist.py -v` |

Ordem sugerida: schema loader → scheduler core → isolamento agent → CLI → delivery Telegram opcional.

### Retroalimentação

**Após concluir PRD-010:** revisar e atualizar [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md) e candidatos a promoção ([ADR-020](../decisions/ADR-020-backlog-promotion.md)) — não há PRD-011 no MVP.

**Aprendizados a registrar:**

- [ ] Processo embutido vs. `cursor-agent cron daemon`
- [ ] Limites de frequência e custo observados
- [ ] Schema final de `jobs.yaml` e timezone
- [ ] Coexistência gateway + cron em carga moderada
- [ ] Itens do backlog a promover com evidência de implementação
