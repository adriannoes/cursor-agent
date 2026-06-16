---
id: PRD-001
title: AsyncSdkFacade
status: draft
phase: 1
depends_on: [PRD-000]
adrs:
  - ADR-002
  - ADR-018
  - ADR-022
  - ADR-024
related:
  - path: ../contracts/async-sdk-facade.md
    role: spec
  - path: ../decisions/ADR-002-async-sdk-facade.md
---

# PRD-001 — AsyncSdkFacade

## 1. Introdução / Visão geral

O **cursor-agent** delega loop agentic, tools e inferência ao Cursor SDK. Todo acesso direto a `cursor_sdk` deve passar por uma única facade testável, usada por CLI, gateway e cron sem duplicar lógica sync/async.

**Problema:** importar `cursor_sdk` espalhado pelo código torna testes frágeis (exigem `CURSOR_API_KEY`), dificulta evolução quando o SDK muda e impede mocks determinísticos para pool e comandos.

**Objetivo:** implementar `AsyncSdkFacade` real + `FakeSdkFacade` conforme contrato em [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md), com logs JSON v1 nos eventos de `send`.

Depende de [PRD-000](PRD-000-sdk-spike.md) (spike SDK validado). Contexto: [STRATEGY.md §2.2 e §3.2](../STRATEGY.md#22-facade-async-first).

## 2. Objetivos

1. Estender o scaffold mínimo do PRD-000 com layout de módulos da facade (`sdk_facade.py`, `tests/unit/`) sem regredir o gate ADR-026.
2. Definir `SdkFacade` como `typing.Protocol` com tipos (`RunResult`, `StreamCallbacks`, `AgentBusyError`) alinhados ao contrato.
3. Implementar `AsyncSdkFacade` sobre `AsyncClient.launch_bridge` com lifecycle de um client por processo.
4. Implementar `FakeSdkFacade` in-memory para testes unitários sem bridge real.
5. Cobrir create, resume, send, cancel e close com testes unitários.
6. Emitir logs NDJSON schema v1 no início e fim de cada `send` ([ADR-018](../decisions/ADR-018-observability-logs.md)).

## 3. User Stories

| ID | História |
|----|----------|
| US-1 | Como **desenvolvedor de CLI**, quero uma API async única para criar e enviar mensagens a agentes sem importar `cursor_sdk` fora de um módulo. |
| US-2 | Como **desenvolvedor de testes**, quero `FakeSdkFacade` para testar pool, locks e comandos sem API key. |
| US-3 | Como **operador**, quero logs estruturados por run para debugar falhas e latência. |
| US-4 | Como **desenvolvedor de gateway**, quero retry apenas em erros `is_retryable` do SDK, com backoff respeitando `retry_after`. |

## 4. Requisitos funcionais

**FR-1.** O módulo `src/cursor_agent/sdk_facade.py` deve ser o **único** em `src/` que importa `cursor_sdk`. `FakeSdkFacade` vive no mesmo módulo na Fase 1 (split só se ultrapassar ~500 linhas).

**FR-2.** `SdkFacade` Protocol deve expor: `create_agent`, `resume_agent`, `send`, `cancel`, `close` com assinaturas do [contrato](../contracts/async-sdk-facade.md).

**FR-3.** `AsyncSdkFacade` deve usar context manager async (`async with`) criando bridge em `__aenter__` e chamando `close()` em `__aexit__`.

**FR-4.** `create_agent` deve aceitar `workspace`, `model` (default `composer-2.5`), `tool_profile` (default `coding`), `runtime_mode` (default `local`) e retornar `agent_id`.

**FR-5.** `resume_agent` deve re-injetar `mcp_servers` do perfil atual no resume — config inline MCP não persiste no SDK.

**FR-6.** `send` deve aceitar `StreamCallbacks` opcionais (`on_assistant_text`, `on_tool_start`, `on_tool_end`) e retornar `RunResult` com `run_id`, `status`, `text`, `usage`.

**FR-7.** Em falhas de rede/auth antes do run iniciar, propagar `CursorAgentError`; retry só se `is_retryable`, honrando `retry_after`, máximo 3 tentativas com backoff exponencial.

**FR-8.** `FakeSdkFacade` deve manter mapa `agent_id → messages[]`, retornar texto fixo ou scripted em `send`, e expor gancho de run em andamento (ex.: `asyncio.Event` liberado ao fim de `send`) para testes do `SessionAgentPool` assertarem `AgentBusyError` via `try_acquire` — a fake **não** levanta `AgentBusyError` ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md), [contrato §8](../contracts/async-sdk-facade.md#8-fakesdkfacade-testes)).

**FR-9.** Logs em `send` start/end devem seguir schema v1 de [ADR-018](../decisions/ADR-018-observability-logs.md) (campos `v`, `ts`, `level`, `event`, `session_id`, `session_key`, `agent_id`, `run_id`, `duration_ms`, `status`).

**FR-10.** Testes unitários em `tests/unit/test_facade.py` devem cobrir happy path e cenários de erro usando apenas `FakeSdkFacade`.

## 5. Não-objetivos (fora de escopo)

- `SessionStore`, `SessionAgentPool` — [PRD-002](PRD-002-session-store.md).
- CLI Typer / REPL — [PRD-003](PRD-003-cli-repl.md).
- Gateway Telegram e perfil `messaging`.
- Shutdown graceful SIGTERM — preparado em contrato ([ADR-021](../decisions/ADR-021-graceful-shutdown.md)); implementação completa pode vir com CLI.
- OpenTelemetry / tracing além de logs NDJSON v1.
- Wrapper sync paralelo — CLI usa `asyncio.run()` sobre a mesma facade ([ADR-002](../decisions/ADR-002-async-sdk-facade.md)).

## 6. Considerações de design

Não aplicável (sem UI). Streaming de texto do assistente é repassado via callbacks para a camada CLI (Rich) na Fase 1.

## 7. Considerações técnicas

| Tópico | Referência |
|--------|------------|
| Decisão facade + fake | [ADR-002](../decisions/ADR-002-async-sdk-facade.md) |
| Contrato de API (fonte de verdade) | [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md) |
| Logs JSON v1 | [ADR-018](../decisions/ADR-018-observability-logs.md) |
| Pirâmide de testes | [ADR-005](../decisions/ADR-005-testing-strategy.md) |
| Exit codes (camada CLI consome) | Contrato §3 — exit 0 sucesso/cancelado, 1 `CursorAgentError`, 2 `RunResult.status == ERROR` |

**Lifecycle:** um `AsyncClient` por processo; dispose via `close()` no shutdown do processo.

**MCP no resume:** obrigatório re-injetar servers do perfil — documentado no contrato §2.

**Layout de módulos e handoff PRD-000:**

O PRD-000 entrega dependência pinada, exemplos de integração e scaffold mínimo do pacote. O PRD-001 **estende** esse scaffold — não recria `pyproject.toml`, lockfile nem spike.

| Artefato PRD-000 | Uso no PRD-001 |
|------------------|----------------|
| `src/cursor_agent/__init__.py` (`__version__`) | Preservar; re-export opcional de tipos públicos da facade |
| `tests/test_package_metadata.py` | Deve continuar verde após T0 |
| `examples/async_repl.py`, `examples/tools_list.py` | Referência do spike; **não** importados por `src/` |
| `tests/integration/test_sdk_smoke.py` | Smoke SDK separado; facade não substitui este gate |

**Layout alvo (Fase 1 — subset de [STRATEGY §5.2](../STRATEGY.md#52-estrutura-alvo-fase-4)):**

```text
src/cursor_agent/
├── __init__.py          # PRD-000 — __version__; re-exports opcionais
└── sdk_facade.py        # Protocol, tipos, AsyncSdkFacade, FakeSdkFacade — único import cursor_sdk

tests/
├── test_package_metadata.py   # PRD-000 — gate de pacote
└── unit/
    ├── __init__.py
    ├── test_facade.py         # FR-10 — happy path, erros, logs (FakeSdkFacade)
    └── test_facade_imports.py # FR-1 — isolamento de import cursor_sdk
```

**Aprendizados do PRD-000 (spike SDK):**

- `cursor-sdk` pinado em `0.1.7`; APIs async reais usam `async with await AsyncClient.launch_bridge(...)` e `async with await client.agents.create(...)`.
- Smoke live validou `result.status == "finished"` para sucesso; o contrato da facade deve mapear esse status sem assumir `"success"`.
- `run.messages()` é a superfície estável para observar `SDKToolUseMessage`; `args`/`result` permanecem payloads instáveis e devem ficar tipados como dados opacos na facade.
- Em runs locais do spike, `SDKSystemMessage.tools` não foi emitido; o snapshot `docs/sdk-tools-snapshot.txt` registra tools observadas via `SDKToolUseMessage` (`grep`, `read`), não inventário declarado completo.
- Cold start medido no exemplo async: ~4.33s no primeiro turn com `composer-2.5`; smoke live de integração executou dois testes em ~20.61s.
- O spike ainda não validou os nomes reais dos campos de identidade e uso (`agent_id`, `run_id`, `usage`) no SDK Python; PRD-001 deve começar com testes/adapter finos que capturem esses atributos antes de consolidar `RunResult`.

## 8. Métricas de sucesso

| Métrica | Critério de aceite |
|---------|-------------------|
| Contrato | Implementação passa revisão contra [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md) |
| Testes unitários | `pytest tests/unit/test_facade.py` verde sem `CURSOR_API_KEY` |
| Isolamento SDK | `rg "cursor_sdk" src/` retorna apenas o módulo da facade |
| Observabilidade | Eventos `send` start/end em NDJSON com schema v1 |
| Fake utilizável | Pool e CLI (PRDs seguintes) podem injetar `FakeSdkFacade` em testes |
| Gate CI local | Gate ADR-026 verde sem `CURSOR_API_KEY` após T0 (cobertura ≥85% não regride) |

## 9. Perguntas em aberto

- A facade deve expor inventário de tools apenas como capability observada (`SDKToolUseMessage`) até o SDK voltar a emitir `SDKSystemMessage.tools`, ou deve omitir esse método na Fase 1?
- `run.messages()` e `run.text()` podem compartilhar consumo de stream em alguns cenários; `send` deve escolher uma única estratégia de observação para evitar dupla leitura.
- Confirmar em PRD-001 se MCP inline re-injetado no resume aparece nos eventos observáveis ou apenas altera a capacidade do run.
- Confirmar, com bridge mockado ou teste de contrato fino, onde o SDK expõe `agent_id`, `run_id`, status terminal e `usage`; não assumir nomes de atributos além do que o spike validou (`result.status == "finished"`).

## 10. Tarefas de implementação

### Definition of Done

- [ ] Layout `src/cursor_agent/sdk_facade.py` + pacote `tests/unit/` criado (T0)
- [ ] Handoff PRD-000 preservado (`__version__`, `test_package_metadata.py`, gate CI local sem key)
- [ ] `src/` não importa `examples/` (spike isolado da API de produção)
- [ ] Contrato implementado conforme [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md)
- [ ] `FakeSdkFacade` + testes unitários
- [ ] Logs JSON v1 em send start/end

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T0 | Scaffold pacote + testes unitários | 2h | PRD-000 |
| T1 | Protocol + tipos | 3h | T0 |
| T2 | AsyncSdkFacade real | 8h | T1 |
| T3 | FakeSdkFacade | 4h | T1 |
| T4 | test_facade_unit | 4h | T3 |

### T0 — scaffold de módulos

- [ ] T0.1 `tests/unit/__init__.py` — pacote pytest para testes da facade
- [ ] T0.2 `src/cursor_agent/sdk_facade.py` — stub inicial (tipos + `SdkFacade` Protocol **sem** import `cursor_sdk` até T2)
- [ ] T0.3 `src/cursor_agent/__init__.py` — preservar `__version__`; re-export opcional de tipos públicos (`RunResult`, `SdkFacade`, …)
- [ ] T0.4 `tests/unit/test_facade_imports.py` — RED→GREEN: apenas `sdk_facade` importa `cursor_sdk` quando `AsyncSdkFacade` existir
- [ ] T0.5 Gate ADR-026 verde após scaffold (`test_package_metadata.py` incluído; cobertura ≥85%)

### Arquivos alvo

| Arquivo | Responsabilidade |
|---------|------------------|
| `src/cursor_agent/__init__.py` | Metadata do pacote (PRD-000); re-exports opcionais da facade |
| `src/cursor_agent/sdk_facade.py` | Protocol, tipos, `AsyncSdkFacade`, `FakeSdkFacade` — único import `cursor_sdk` |
| `tests/unit/__init__.py` | Pacote de testes unitários |
| `tests/unit/test_facade.py` | Happy path, erros, retry, logs — `FakeSdkFacade` e mocks de bridge |
| `tests/unit/test_facade_imports.py` | Isolamento FR-1 via introspecção de imports |
| `tests/test_package_metadata.py` | Regressão do scaffold PRD-000 |

Detalhamento operacional (What / Why / Verify por sub-tarefa) fica em `engineering/tasks/tasks-PRD-001-facade.md` quando gerado.

### T2 — implementação

- [ ] T2.1 `launch_bridge` context manager
- [ ] T2.2 create / resume / send / cancel
- [ ] T2.3 MCP re-inject no resume
- [ ] T2.4 retry `is_retryable`
- [ ] T2.5 StreamCallbacks

### Demo

`pytest tests/unit/test_facade.py` — suite unitária da facade sem API key.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| bootstrap (T0) | `tests/test_package_metadata.py` continua verde + `tests/unit/test_facade_imports.py` (RED→GREEN conforme T0/T1/T2) | gate ADR-026 sem `CURSOR_API_KEY` |
| FR-2, FR-8 | `tests/unit/test_facade.py` — Protocol + `FakeSdkFacade` create/send | `pytest tests/unit/test_facade.py -k "fake" -v` |
| FR-3–FR-7 | `tests/unit/test_facade.py` — retry `is_retryable`, MCP re-inject (mock bridge) | `pytest tests/unit/test_facade.py -k "retry or resume" -v` |
| FR-9 | `tests/unit/test_facade.py` — NDJSON send start/end schema v1 | `pytest tests/unit/test_facade.py -k "log" -v` |
| FR-1 | `tests/unit/test_facade_imports.py` — único módulo importa `cursor_sdk` | `pytest tests/unit/test_facade_imports.py -v` |
| FR-6 | `tests/unit/test_facade.py` — adapter mapeia `run_id`, `status`, `text`, `usage` a partir de objetos SDK/fakes com shape real observado | `pytest tests/unit/test_facade.py -k "run_result_mapping" -v` |

Ordem sugerida: **T0 scaffold** → T1 tipos/Protocol → T3 Fake + happy path → erros/retry → logs → T2 `AsyncSdkFacade` com bridge mockado.

### Aprendizados recebidos do PRD-000

- [x] Versão pinada real: `cursor-sdk==0.1.7`.
- [x] Bridge async local validada com `AsyncClient.launch_bridge`, `LocalAgentOptions(cwd=...)` e modelo `composer-2.5`.
- [x] Multi-turn preserva contexto no mesmo agente; `examples/async_repl.py` valida recall do token `PLUMBA-7742`.
- [x] Tool calls nativas observadas no workspace: `read` e `grep`; `SDKSystemMessage.tools` não apareceu nos runs locais do spike.
- [x] Status terminal de sucesso observado: `finished`; testes da facade não devem esperar `success`.
- [x] Latência: cold start ~4.33s; smoke live de integração ~20.61s para dois testes.
- [x] Gap deliberado para PRD-001: confirmar shape real de `agent_id`, `run_id` e `usage` antes de finalizar o adapter de `RunResult`.

### Retroalimentação

**Após concluir PRD-001:** revisar e atualizar [PRD-002](PRD-002-session-store.md) (§7, §9, §11) antes de SessionStore/pool.

**Aprendizados a registrar:**

- [ ] Forma real de `RunResult`, `StreamCallbacks` e erros do SDK vs. contrato
- [ ] Latência de create/resume/send com bridge real (se smoke cruzado)
- [ ] Comportamento de MCP re-inject no resume (confirmado ou ajustar contrato)
- [ ] Campos de log que o SDK expõe vs. schema v1
- [ ] Ajustes em estimativas de pool/lock (PRD-002) com base no fake
