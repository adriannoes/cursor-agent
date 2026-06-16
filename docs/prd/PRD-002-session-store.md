---
id: PRD-002
title: SessionStore e SessionAgentPool
status: draft
phase: 1
depends_on: [PRD-001]
adrs:
  - ADR-003
  - ADR-004
  - ADR-007
  - ADR-008
  - ADR-009
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "8"
---

# PRD-002 — SessionStore + SessionAgentPool

## 1. Introdução / Visão geral

O cursor-agent usa **dupla persistência**: metadados de sessão no SQLite local e histórico de conversa no SDK via `agent_id`. Esta PRD cobre persistência, resolução de sessões e serialização de acesso concorrente por `session_key`.

**Problema:** sem store local, o usuário não pode listar sessões, retomar por UUID após restart ou isolar conversas por workspace. Sem pool com lock, mensagens concorrentes no mesmo chat corrompem estado do agente.

**Objetivo:** implementar `SessionStore` (aiosqlite), `SessionAgentPool` (lazy resume + `asyncio.Lock` por key) e loader de config Pydantic — base para o REPL em [PRD-003](PRD-003-cli-repl.md).

Modelo de sessão: [STRATEGY.md §2.1](../STRATEGY.md#21-modelo-de-sessão-dupla-persistência). Schema e aceite: [STRATEGY.md §8](../STRATEGY.md#8-fase-1-cli-sessões).

## 2. Objetivos

1. Persistir sessões em SQLite com schema definido em STRATEGY §8.
2. Resolver `session_key` composto com `workspace_hash` ([ADR-004](../decisions/ADR-004-session-key-workspace.md)).
3. Validar `runtime` no `/resume` — proibir cross-runtime ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)).
4. Preencher `title` a partir da primeira mensagem do usuário ([ADR-009](../decisions/ADR-009-session-titles.md)).
5. Serializar `send` por `session_key` via `SessionAgentPool` — CLI com lock bloqueante; gateway com `try_acquire` → `AgentBusyError` ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).
6. Carregar config tipada com precedência CLI > env > YAML ([ADR-007](../decisions/ADR-007-config-loader.md)).

## 3. User Stories

| ID | História |
|----|----------|
| US-1 | Como **usuário CLI**, quero que `/resume` após restart restaure a conversa via `agent_id` salvo no SQLite. |
| US-2 | Como **usuário**, quero listar sessões com título legível para escolher qual retomar. |
| US-3 | Como **usuário**, quero que mudar de diretório de trabalho não misture sessões de projetos diferentes. |
| US-4 | Como **desenvolvedor**, quero config validada na subida (model, runtime, cwd) em vez de falhar no meio de um turn. |
| US-5 | Como **sistema**, quero rejeitar ou serializar envios simultâneos na mesma `session_key` para evitar corrupção de estado. |

## 4. Requisitos funcionais

**FR-1.** `SessionStore` deve usar `aiosqlite` com schema:

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    title TEXT,
    workspace TEXT NOT NULL,
    runtime TEXT NOT NULL,
    tool_profile TEXT DEFAULT 'coding',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata JSON
);
CREATE INDEX idx_sessions_key ON sessions(session_key, updated_at DESC);
```

**FR-2.** `session_key` deve seguir formato `cli:{profile}:{workspace_hash}` onde `workspace_hash = sha256(abs(cwd))[:8]` e `profile` default `default` ([ADR-004](../decisions/ADR-004-session-key-workspace.md)).

**FR-3.** Operações do store: `create`, `resolve(session_key, session_id?)`, `touch`, `list(session_key)`, atualização de `metadata` JSON (ex.: `memory_injected`, `status`).

**FR-4.** `resolve` sem `session_id` deve retornar a sessão mais recente (`updated_at DESC`) do `session_key` atual.

**FR-5.** No primeiro turn do usuário (ou na criação), `title = first_user_message[:60]` com strip e ellipsis se truncado ([ADR-009](../decisions/ADR-009-session-titles.md)).

**FR-6.** `/resume` (camada pool/store) deve falhar com erro claro se `session.runtime != config.runtime.mode`, sugerindo `/new` ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)).

**FR-7.** `SessionAgentPool.get(session_key)` deve fazer lazy resume via `agent_id` persistido, usando `AsyncSdkFacade.resume_agent`.

**FR-8.** `SessionAgentPool.send(session_key, message)` deve adquirir `asyncio.Lock` por `session_key`:
- **CLI:** `await lock.acquire()` (bloqueante) — aguarda fim do run ou `/stop`; não levanta `AgentBusyError`.
- **Gateway:** `try_acquire` / `acquire(blocking=False)` — se lock indisponível, levantar `AgentBusyError` ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).

**FR-9.** `config/loader.py` deve usar pydantic-settings v2 com precedência: CLI flags > env `CURSOR_AGENT__*` > `~/.cursor-agent/config.yaml` > defaults; expansão `${VAR}` via `os.path.expandvars` ([ADR-007](../decisions/ADR-007-config-loader.md)).

**FR-10.** Config mínimo deve incluir: `model`, `tool_profile`, `runtime.mode`, `runtime.local.cwd`, `runtime.local.setting_sources`.

**FR-11.** Testes unitários em `tests/unit/test_session_store.py` e `tests/unit/test_pool.py` usando `FakeSdkFacade` — sem API key.

## 5. Não-objetivos (fora de escopo)

- CLI Typer, comandos `/new` `/resume` na UX — [PRD-003](PRD-003-cli-repl.md).
- Gateway Telegram e `session_key` formato `telegram:{chat_id}:{workspace_hash}` (schema suporta; implementação gateway é Fase 3).
- Memória `MEMORY.md` / `USER.md` — Fase 4 ([ADR-010](../decisions/ADR-010-memory-v1.md)).
- `/compress`, cron jobs, agent dedicado por job.
- Títulos semânticos via LLM — backlog Fase 5.
- Migrações complexas além do schema inicial (evoluir em PR futuro se necessário).

## 6. Considerações de design

- `sessions list` (CLI) exibirá `id`, `title`, `updated_at` — títulos truncados devem ser úteis o suficiente para distinguir sessões no mesmo workspace.
- `agent_id` é interno; UX principal usa UUID da sessão (`session id`).

## 7. Considerações técnicas

| Tópico | Referência |
|--------|------------|
| session_key + workspace_hash | [ADR-004](../decisions/ADR-004-session-key-workspace.md) |
| Resume cross-runtime proibido | [ADR-003](../decisions/ADR-003-cross-runtime-resume.md) |
| Config loader | [ADR-007](../decisions/ADR-007-config-loader.md) |
| Títulos de sessão | [ADR-009](../decisions/ADR-009-session-titles.md) |
| Agent busy / lock | [ADR-008](../decisions/ADR-008-agent-busy-gateway.md) |
| Facade (dependência) | [PRD-001](PRD-001-facade.md), [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md) |
| Schema e config exemplo | [STRATEGY.md §8](../STRATEGY.md#8-fase-1-cli-sessões) |

**Fonte da verdade:** histórico de conversa no SDK (`agent_id`); metadados no SQLite.

**Concorrência:** uma mensagem inbound por vez por `session_key`; cron nunca compartilha key com chat (regra documentada para fases futuras).

## 8. Métricas de sucesso

| Métrica | Critério de aceite |
|---------|-------------------|
| Persistência | Criar sessão, restart simulado, `resolve` retorna mesmo `agent_id` |
| Isolamento workspace | `session_key` diferente ao mudar `cwd` |
| Runtime guard | Resume com runtime mismatch falha com mensagem acionável |
| Títulos | `list` mostra título derivado da primeira mensagem |
| Concorrência | CLI: segundo `send` aguarda lock; gateway: `AgentBusyError` |
| Testes | `pytest tests/unit/test_session_store.py tests/unit/test_pool.py` verde |

## 9. Perguntas em aberto

Nenhuma — chave composta, runtime, config e títulos estão em ADRs listados no frontmatter.

## 10. Tarefas de implementação

### Definition of Done

- [ ] Schema SQLite conforme STRATEGY
- [ ] `session_key` composto ([ADR-004](../decisions/ADR-004-session-key-workspace.md))
- [ ] Resume valida runtime ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md))
- [ ] Lock por key; `AgentBusyError`

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T1 | SessionStore aiosqlite | 6h | PRD-001 |
| T2 | SessionAgentPool | 6h | T1 |
| T3 | config loader pydantic | 4h | — |
| T4 | testes unit | 6h | T2 |

### T1 — store

- [ ] T1.1 migrations / schema
- [ ] T1.2 resolve(session_key), touch, list
- [ ] T1.3 title from first message ([ADR-009](../decisions/ADR-009-session-titles.md))
- [ ] T1.4 metadata JSON (`memory_injected`, `status`)

### T2 — pool

- [ ] T2.1 lazy resume via agent_id
- [ ] T2.2 asyncio.Lock por session_key (CLI bloqueante; gateway try_acquire)
- [ ] T2.3 send wrapper

### Demo

`pytest tests/unit/test_session_store.py tests/unit/test_pool.py` — store e pool sem API key.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR store | `tests/unit/test_session_store.py` — `session_key` composto, touch, list, title | `pytest tests/unit/test_session_store.py -v` |
| FR runtime | `tests/unit/test_session_store.py` — resume bloqueia cross-runtime ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)) | `pytest tests/unit/test_session_store.py -k runtime -v` |
| FR pool | `tests/unit/test_pool.py` — lazy resume, lock, `AgentBusyError` | `pytest tests/unit/test_pool.py -v` |
| FR config | `tests/unit/test_config_loader.py` — precedência pydantic-settings | `pytest tests/unit/test_config_loader.py -v` |

Ordem sugerida: schema/store → config loader → pool com `FakeSdkFacade` injetado.

### Retroalimentação

**Após concluir PRD-002:** revisar e atualizar [PRD-003](PRD-003-cli-repl.md) (§7, §9, §11) antes do CLI REPL.

**Aprendizados a registrar:**

- [ ] Schema SQLite final e migrações necessárias
- [ ] Comportamento de lock (bloqueante CLI vs. try_acquire gateway)
- [ ] Tempos de I/O aiosqlite sob carga leve
- [ ] Defaults de config que o REPL deve expor
- [ ] Edge cases de `session_key` com múltiplos workspaces
