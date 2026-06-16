# Tarefas — PRD-001 AsyncSdkFacade (Fase 1)

> **PRD:** [PRD-001-facade.md](../../docs/prd/PRD-001-facade.md)  
> **ADRs:** [ADR-002](../../docs/decisions/ADR-002-async-sdk-facade.md) (Protocol + FakeSdkFacade), [ADR-018](../../docs/decisions/ADR-018-observability-logs.md) (NDJSON v1), [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) (TDD + retro), [ADR-024](../../docs/decisions/ADR-024-error-taxonomy-retry.md) (erros + retry), [ADR-025](../../docs/decisions/ADR-025-secrets-policy.md) (redaction em logs), [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) (pirâmide), [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md) (gate CI)  
> **Contrato:** [async-sdk-facade.md](../../docs/contracts/async-sdk-facade.md)  
> **Escopo deste documento:** Fase 1 — facade async + fake; sem SessionStore, CLI ou gateway.  
> **Status:** Fase 2 completa — sub-tarefas detalhadas prontas para implementação.

## Relevant Files

- `src/cursor_agent/__init__.py` — metadata PRD-000 (`__version__`); re-exports opcionais de tipos públicos da facade (T0).
- `src/cursor_agent/sdk_facade.py` — `SdkFacade` Protocol, `AsyncSdkFacade`, `FakeSdkFacade`; **único** módulo em `src/` que importa `cursor_sdk` (FR-1).
- `src/cursor_agent/errors.py` — hierarquia `CursorAgentError` + subclasses e `AgentBusyError` (tipo compartilhado; levantado só no pool — ADR-024).
- `src/cursor_agent/facade_logging.py` — emissor NDJSON schema v1 para `send` start/end com redaction ADR-025 (FR-9); criar só se `sdk_facade.py` ultrapassar ~300 linhas.
- `src/cursor_agent/tool_profile_resolver.py` — stub mínimo `tool_profile` → `mcp_servers` até PRD-002/005 (FR-5); pode ser função privada em `sdk_facade.py` se preferir menos arquivos.
- `tests/unit/__init__.py` — pacote de testes unitários (T0).
- `tests/unit/test_facade_imports.py` — isolamento FR-1: só `sdk_facade` importa `cursor_sdk` (T0/T6).
- `tests/unit/test_facade.py` — happy path, fake, retry, MCP, logs, adapter `RunResult` (FR-6–FR-10).
- `tests/unit/test_errors.py` — taxonomia ADR-024 e atributos `is_retryable` / `retry_after` (T2).
- `tests/unit/test_run_adapter.py` — mapeamento SDK → `RunResult` com fakes de shape (T3).
- `tests/test_package_metadata.py` — regressão scaffold PRD-000; deve permanecer verde (T0).
- `tests/integration/test_sdk_smoke.py` — smoke SDK PRD-000; **não** substituído pela facade; gate separado com API key.
- `examples/async_repl.py` — referência de padrão async do spike; **não** importado por `src/`.
- `docs/prd/PRD-002-session-store.md` — alvo da retroalimentação ao fechar PRD-001 (T6.6).

### Notes

- **Handoff PRD-000:** não recriar `pyproject.toml`, `uv.lock` nem exemplos; estender scaffold existente.
- **Decisões padrão (fecham §9 do PRD para execução):**
  - **Inventário de tools:** omitir método público na Fase 1 (sem `list_tools` na facade).
  - **Stream:** estratégia única — `async for message in run.messages()` + `await run.wait()`; **não** chamar `run.text()` depois de drenar `messages()`.
  - **Logs:** `LogContext` opcional em `send(..., log_context=...)`; `session_id` / `session_key` podem ser `None` até PRD-002.
  - **MCP:** resolver stub `coding` → `{}`, `messaging` → `{}` (ADR-014 baseline); perfil real em PRD-005.
- **TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)):** Ordem: T0 scaffold → T2 tipos/erros → T3 adapter shape → T4 Fake + happy path → T5 Async mockado → T6 logs/imports/retro. Fake **antes** de Async real.
- **Gate de PR ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):**

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

- Integração facade **opcional** (nightly): reutilizar padrão de `tests/integration/test_sdk_smoke.py`; suíte unitária PR não exige API key.
- Status terminal de sucesso SDK observado no spike: `"finished"` — mapear para `RunStatus.FINISHED`, não `"success"`.
- Pin SDK: `cursor-sdk==0.1.7` ([ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md)).

## Tasks

- [x] **1.0 Scaffold Fase 1 + gate ADR-026** — PRD T0 (T0.1–T0.5)

  **Trigger / entry point:** PRD-000 concluído; branch `feat/prd-001-facade` (ou equivalente).  
  **Enables:** Layout `tests/unit/`, stub `sdk_facade.py`, testes de import e gate CI sem regressão.  
  **Depends on:** [PRD-000](../../docs/prd/PRD-000-sdk-spike.md) entregue (pyproject, CI, scaffold `src/cursor_agent/__init__.py`).

  **Acceptance criteria:**
  - `tests/unit/` existe e é coletável pelo pytest.
  - `src/cursor_agent/sdk_facade.py` existe com stub de tipos/Protocol **sem** import `cursor_sdk`.
  - `tests/test_package_metadata.py` continua verde.
  - Gate ADR-026 passa sem `CURSOR_API_KEY` (cobertura ≥85%).

  - [x] 1.1 Criar pacote `tests/unit/`
    - **File**: `tests/unit/__init__.py` (create new)
    - **What**: Pacote vazio importável para testes unitários da facade.
    - **Why**: PRD T0.1; espelha layout previsto em [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md).
    - **Pattern**: `tests/integration/__init__.py` do PRD-000.
    - **Verify**: `uv run pytest tests/unit/ --collect-only` coleta sem erro estrutural.

  - [x] 1.2 Criar stub inicial `sdk_facade.py` (sem `cursor_sdk`)
    - **File**: `src/cursor_agent/sdk_facade.py` (create new)
    - **What**: Módulo com docstring, placeholders para tipos e `SdkFacade` Protocol; **sem** `import cursor_sdk` até Tarefa 5.x.
    - **Why**: PRD T0.2; permite TDD de tipos e imports antes do bridge real.
    - **Pattern**: Layout em [PRD-001 §7](../../docs/prd/PRD-001-facade.md#7-considerações-técnicas).
    - **Verify**: `uv run python -c "import cursor_agent.sdk_facade"` não falha; `rg "cursor_sdk" src/` retorna zero hits nesta sub-tarefa.

  - [x] 1.3 Preservar `__version__` e preparar re-exports opcionais
    - **File**: `src/cursor_agent/__init__.py` (modify existing)
    - **What**: Manter `__version__ = "0.0.0"`; adicionar `__all__` vazio ou comentário de re-exports futuros (`RunResult`, `SdkFacade`, …).
    - **Why**: PRD T0.3; handoff PRD-000 não pode regredir metadata do pacote.
    - **Pattern**: Scaffold existente em `src/cursor_agent/__init__.py`.
    - **Verify**: `uv run pytest tests/test_package_metadata.py -v` passa.

  - [x] 1.4 Esqueleto `test_facade_imports.py` (RED condicional)
    - **File**: `tests/unit/test_facade_imports.py` (create new)
    - **What**: Teste que varre módulos em `src/cursor_agent/` e asserta que **nenhum** importa `cursor_sdk` enquanto `AsyncSdkFacade` não existir; após T5, asserta que **somente** `sdk_facade.py` importa.
    - **Why**: PRD T0.4 / FR-1; gate de isolamento desde o início.
    - **Pattern**: `rg "cursor_sdk" src/` como verificação manual complementar.
    - **Verify**: `uv run pytest tests/unit/test_facade_imports.py -v` passa (zero imports SDK no stub).

  - [x] 1.5 Validar gate ADR-026 após scaffold
    - **File**: — (verificação)
    - **What**: Rodar gate canônico completo; confirmar cobertura ≥85% e `test_package_metadata` + `test_pyproject_config` verdes.
    - **Why**: PRD T0.5 / métrica “Gate CI local” §8.
    - **Pattern**: [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: `ruff check src tests && ruff format --check src tests && mypy --strict src && pytest --cov=cursor_agent --cov-fail-under=85 -m "not integration"` exit 0.

- [x] **2.0 Contrato público + taxonomia de erros** — PRD T1 (tipos + ADR-024)

  **Trigger / entry point:** Scaffold T0 concluído.  
  **Enables:** `FakeSdkFacade` e `AsyncSdkFacade` compartilham tipos e erros tipados.  
  **Depends on:** Tarefa 1.0.

  **Acceptance criteria:**
  - `RunStatus`, `RunResult`, `StreamCallbacks`, `LogContext`, `SdkFacade` Protocol definidos conforme contrato.
  - `errors.py` com `CursorAgentError` (+ subclasses) e `AgentBusyError`.
  - `mypy --strict src` verde nos novos tipos.

  - [x] 2.1 Teste TDD dos tipos públicos (`RunResult`, `RunStatus`, `StreamCallbacks`)
    - **File**: `tests/unit/test_facade.py` (create new)
    - **What**: Testes que instanciam dataclasses/enums e validam campos obrigatórios (`run_id`, `status`, `text`, `usage` opcional).
    - **Why**: FR-2 / FR-6; contrato em [async-sdk-facade.md §1](../../docs/contracts/async-sdk-facade.md#1-tipos).
    - **Pattern**: `RunStatus.FINISHED` alinhado ao spike (`"finished"`, não `"success"`).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "types" -v` falha antes da implementação, passa após 2.2.

  - [x] 2.2 Implementar tipos e `SdkFacade` Protocol em `sdk_facade.py`
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: `RunStatus` enum, `RunResult`, `StreamCallbacks`, `LogContext` (opcional: `session_id`, `session_key`, `agent_id`), `SdkFacade` Protocol com assinaturas do contrato.
    - **Why**: FR-2; base para fake e implementação real.
    - **Pattern**: [contracts/async-sdk-facade.md §1](../../docs/contracts/async-sdk-facade.md#1-tipos).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "types" -v` passa; `uv run mypy --strict src` passa.

  - [x] 2.3 Teste TDD da hierarquia `CursorAgentError`
    - **File**: `tests/unit/test_errors.py` (create new)
    - **What**: Assertar subclasses (`AuthError`, `ConfigError`, `NetworkError`, `TimeoutError`, `InvalidAgentError`), `is_retryable` e `retry_after` conforme ADR-024.
    - **Why**: FR-7; retry e exit codes CLI dependem de taxonomia estável.
    - **Pattern**: [ADR-024 §1](../../docs/decisions/ADR-024-error-taxonomy-retry.md#1-hierarquia-cursoragenterror).
    - **Verify**: `uv run pytest tests/unit/test_errors.py -v` falha antes de 2.4, passa depois.

  - [x] 2.4 Implementar `src/cursor_agent/errors.py`
    - **File**: `src/cursor_agent/errors.py` (create new)
    - **What**: `CursorAgentError` base com `is_retryable`, `retry_after`; subclasses ADR-024; `AgentBusyError` (documentar: levantado só pelo pool — ADR-008).
    - **Why**: ADR-024 §3; separar erros de domínio da facade.
    - **Pattern**: Tabela ADR-024; `AgentBusyError` no contrato §1.
    - **Verify**: `uv run pytest tests/unit/test_errors.py -v` passa.

  - [x] 2.5 Re-exportar tipos públicos em `__init__.py` (opcional)
    - **File**: `src/cursor_agent/__init__.py` (modify existing)
    - **What**: Exportar `RunResult`, `RunStatus`, `StreamCallbacks`, `SdkFacade` (typing-only) se desejável para consumidores futuros.
    - **Why**: PRD T0.3; DX para PRD-002/003 sem import profundo.
    - **Pattern**: `__all__` explícito.
    - **Verify**: `uv run python -c "from cursor_agent import RunResult; print(RunResult)"` funciona se re-export ativado.

- [x] **3.0 Adapter de shape do SDK + estratégia de stream** — PRD gap §9 / FR-6

  **Trigger / entry point:** Tipos T2 disponíveis.  
  **Enables:** `RunResult` estável antes de Fake/Async; decisão de stream documentada.  
  **Depends on:** Tarefa 2.0.

  **Acceptance criteria:**
  - Funções puras mapeiam objetos SDK-like → `RunResult` (status `finished` → `FINISHED`).
  - Estratégia única: drenar `run.messages()` uma vez; não combinar com `run.text()` no mesmo run.
  - Testes com fakes de shape (sem bridge real).

  - [x] 3.1 Teste TDD `run_result_mapping` com fakes de shape SDK
    - **File**: `tests/unit/test_run_adapter.py` (create new)
    - **What**: Fakes mínimos (`SimpleNamespace` ou dataclasses) simulando `run.wait()` → `status="finished"`, `run_id`, `usage`; testar mapeamento para `RunResult`.
    - **Why**: Gap PRD-000 §11; não assumir nomes de atributos sem teste.
    - **Pattern**: Spike validou `result.status == "finished"`; descobrir `run_id`/`usage` via fake documentado no teste.
    - **Verify**: `uv run pytest tests/unit/test_run_adapter.py -k "run_result_mapping" -v` RED→GREEN.

  - [x] 3.2 Implementar funções puras de mapeamento (`map_wait_result`, `extract_assistant_text`)
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Funções privadas `_map_run_result(wait_result) -> RunResult`, `_extract_text_from_messages(messages) -> str` com parsing defensivo; payloads de tool opacos (`Any`).
    - **Why**: FR-6; única fonte de verdade para adapter SDK → domínio.
    - **Pattern**: Spike `SDKToolUseMessage` — envelope estável, `args`/`result` instáveis.
    - **Verify**: `uv run pytest tests/unit/test_run_adapter.py -v` passa.

  - [x] 3.3 Documentar estratégia de stream no módulo
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Comentário/docstring de módulo: usar **somente** `run.messages()` + `run.wait()`; proibir `run.text()` após drenar messages.
    - **Why**: Fecha pergunta §9 do PRD; evita bug de double-consume visto no smoke PRD-000.
    - **Pattern**: Nota em `examples/async_repl.py` usa `run.text()` isolado — facade unifica caminho.
    - **Verify**: Revisão estática; teste 3.1 permanece verde.

  - [x] 3.4 (Opcional) Micro-teste de integração para capturar shape real
    - **File**: `tests/integration/test_facade_shape.py` (create new, opcional)
    - **What**: Teste `@pytest.mark.integration` que registra atributos reais de `run.wait()` e `agent.agent_id` em assert documentado; skip sem `CURSOR_API_KEY`.
    - **Why**: Calibrar adapter se fakes divergirem do SDK 0.1.7.
    - **Pattern**: [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) marker integration.
    - **Verify**: Sem key: SKIPPED; com key: passa e documenta shape em comentário do teste.

- [x] **4.0 `FakeSdkFacade` determinística** — PRD T3 + FR-8, FR-10

  **Trigger / entry point:** Tipos e adapter T3 prontos.  
  **Enables:** Testes unitários de happy path, pool (PRD-002) e CLI sem API key.  
  **Depends on:** Tarefas 2.0, 3.0.

  **Acceptance criteria:**
  - `FakeSdkFacade` implementa `SdkFacade` com mapa `agent_id → messages[]`.
  - `send` suporta respostas scripted e gancho `asyncio.Event` para simular run em andamento.
  - Fake **não** levanta `AgentBusyError`.
  - `pytest tests/unit/test_facade.py -k "fake" -v` verde.

  - [x] 4.1 Teste TDD create + send happy path (fake)
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: `FakeSdkFacade.create_agent` retorna `agent_id`; `send` append mensagem e retorna `RunResult` com texto scripted e `FINISHED`.
    - **Why**: FR-8, FR-10; primeiro fluxo verde sem bridge.
    - **Pattern**: Contrato §8 FakeSdkFacade.
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "fake" -v` RED→GREEN.

  - [x] 4.2 Implementar `FakeSdkFacade` — create, send, close
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Classe in-memory: `create_agent`, `resume_agent` (reusa id), `send`, `cancel` (no-op ou CANCELLED), `close`; mapa de mensagens por agente.
    - **Why**: FR-8; ~80% dos testes sem API key ([ADR-002](../../docs/decisions/ADR-002-async-sdk-facade.md)).
    - **Pattern**: [contracts/async-sdk-facade.md §8](../../docs/contracts/async-sdk-facade.md#8-fakesdkfacade-testes).
    - **Verify**: Testes 4.1 passam.

  - [x] 4.3 Teste TDD gancho de run em andamento (`asyncio.Event`)
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Fake expõe `send_in_progress: asyncio.Event` (ou equivalente); teste asserta evento setado durante `send` e liberado ao fim — para PRD-002 `try_acquire`.
    - **Why**: FR-8 / ADR-008; pool testa busy sem fake levantar `AgentBusyError`.
    - **Pattern**: Contrato §8 “gancho de run em andamento”.
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "fake_busy_hook" -v` passa.

  - [x] 4.4 Implementar gancho de busy no `FakeSdkFacade`
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: `asyncio.Event` por agente ou global; set no início de `send`, clear no `finally`.
    - **Why**: Habilita testes de `SessionAgentPool` no PRD-002.
    - **Pattern**: ADR-008 — fake não levanta `AgentBusyError`.
    - **Verify**: Teste 4.3 passa.

  - [x] 4.5 Teste TDD `StreamCallbacks` na fake
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Callbacks `on_assistant_text`, `on_tool_start`, `on_tool_end` invocados em ordem com deltas simulados.
    - **Why**: FR-6; validar contrato de streaming antes do Async real.
    - **Pattern**: [contracts/async-sdk-facade.md §5](../../docs/contracts/async-sdk-facade.md#5-streaming-streamcallbacks).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "fake_callbacks" -v` passa após 4.6.

  - [x] 4.6 Implementar dispatch de callbacks na fake
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Invocar callbacks async/sync conforme contrato; deltas de texto, não texto acumulado.
    - **Why**: FR-6; CLI Rich consumirá deltas no PRD-003.
    - **Pattern**: Contrato §5 — `on_assistant_text` recebe delta.
    - **Verify**: Teste 4.5 passa.

- [x] **5.0 `AsyncSdkFacade` com bridge mockado** — PRD T2 (FR-3–FR-7)

  **Trigger / entry point:** Fake e adapter estáveis (T3, T4).  
  **Enables:** Implementação real isolada; único import `cursor_sdk`.  
  **Depends on:** Tarefas 2.0, 3.0, 4.0 (fake como referência de comportamento).

  **Acceptance criteria:**
  - `AsyncSdkFacade` usa `async with` + `AsyncClient.launch_bridge` em `__aenter__`/`__aexit__`.
  - `create_agent`, `resume_agent`, `send`, `cancel`, `close` cobertos com `unittest.mock` / fakes de bridge.
  - Retry ADR-024 em erros pré-run `is_retryable`.
  - MCP re-inject via stub de `tool_profile`.
  - `rg "cursor_sdk" src/` → somente `sdk_facade.py`.

  - [x] 5.1 Teste TDD context manager (`__aenter__` / `__aexit__`)
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Mock `AsyncClient.launch_bridge`; asserta bridge criado no enter e `close`/`aclose` no exit.
    - **Why**: FR-3; lifecycle um client por processo.
    - **Pattern**: [contracts/async-sdk-facade.md §2.2](../../docs/contracts/async-sdk-facade.md#22-lifecycle).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "async_context" -v` RED→GREEN.

  - [x] 5.2 Implementar `AsyncSdkFacade.__aenter__` / `__aexit__` e construtor
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Construtor puro (`api_key`, `bridge_options`, `logger`); `__aenter__` chama `AsyncClient.launch_bridge`; `__aexit__` dispose. **Primeiro** `import cursor_sdk` neste módulo.
    - **Why**: FR-3; ADR-002 adapter real.
    - **Pattern**: Spike `async with await AsyncClient.launch_bridge(...)`.
    - **Verify**: Teste 5.1 passa; `uv run pytest tests/unit/test_facade_imports.py -v` — só `sdk_facade.py` importa SDK.

  - [x] 5.3 Teste TDD `create_agent` (local, composer-2.5)
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Mock client/agents.create; asserta `model="composer-2.5"`, `LocalAgentOptions(cwd=workspace)`, retorno `agent_id`.
    - **Why**: FR-4; defaults do spike.
    - **Pattern**: `examples/async_repl.py`, `tests/integration/test_sdk_smoke.py`.
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "create_agent" -v` passa após 5.4.

  - [x] 5.4 Implementar `create_agent`
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: `async with await client.agents.create(...)`; registrar `agent_id` internamente; defaults `model`, `tool_profile`, `runtime_mode`.
    - **Why**: FR-4.
    - **Pattern**: SDK docs + spike.
    - **Verify**: Teste 5.3 passa.

  - [x] 5.5 Teste TDD `resume_agent` com MCP re-inject (stub)
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Mock resume; asserta que `mcp_servers` do stub de perfil é passado no resume (inline não persiste no SDK).
    - **Why**: FR-5; contrato §6.
    - **Pattern**: [ADR-014](../../docs/decisions/ADR-014-tool-profiles-mvp.md) baseline — stub até PRD-005.
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "resume" -v` passa após 5.6.

  - [x] 5.6 Implementar `resume_agent` + stub `tool_profile` → `mcp_servers`
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing); opcional `src/cursor_agent/tool_profile_resolver.py`
    - **What**: `resume_agent` re-injeta MCP; função `_resolve_mcp_servers(tool_profile) -> dict` com defaults `coding`/`messaging` → `{}`.
    - **Why**: FR-5; desbloqueia resume sem config loader completo (PRD-002).
    - **Pattern**: Contrato §6 MCP re-inject.
    - **Verify**: Teste 5.5 passa.

  - [x] 5.7 Teste TDD `send` com stream mockado
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Mock `agent.send` + `run.messages()` async iterator + `run.wait()`; asserta `RunResult` via adapter T3 e callbacks opcionais.
    - **Why**: FR-6; integra adapter + StreamCallbacks.
    - **Pattern**: Estratégia única `messages()` + `wait()` (T3.3).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "async_send" -v` passa após 5.8.

  - [x] 5.8 Implementar `send`
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Orquestrar send, drenar messages, invocar callbacks, retornar `RunResult` mapeado; sem `run.text()` após messages.
    - **Why**: FR-6.
    - **Pattern**: Adapter T3 + contrato §5.
    - **Verify**: Teste 5.7 passa.

  - [x] 5.9 Teste TDD retry `is_retryable` (pré-run)
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Mock `CursorAgentError(is_retryable=True, retry_after=0.1)`; asserta 3 tentativas max e backoff; não retry após run iniciar.
    - **Why**: FR-7 / ADR-024.
    - **Pattern**: Patch `asyncio.sleep`; honrar `retry_after`.
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "retry" -v` passa após 5.10.

  - [x] 5.10 Implementar política de retry em operações pré-run
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Helper `_retry_sdk_call` com max 3, `retry_after`, backoff exponencial com jitter; mapear exceções SDK → `CursorAgentError`.
    - **Why**: FR-7.
    - **Pattern**: [ADR-024 §2](../../docs/decisions/ADR-024-error-taxonomy-retry.md#2-política-de-retry).
    - **Verify**: Teste 5.9 passa.

  - [x] 5.11 Teste TDD `cancel` e `close`
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: `cancel` durante send → `RunStatus.CANCELLED`; `close` idempotente.
    - **Why**: Contrato §4; objetivo §2.5.
    - **Pattern**: [contracts/async-sdk-facade.md §4](../../docs/contracts/async-sdk-facade.md#4-cancelamento).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "cancel or close" -v` passa após 5.12.

  - [x] 5.12 Implementar `cancel` e `close`
    - **File**: `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Propagar cancel ao SDK; `close` libera bridge e estado interno.
    - **Why**: Lifecycle completo da facade.
    - **Pattern**: Contrato §2.2 dispose.
    - **Verify**: Teste 5.11 passa.

- [x] **6.0 Observabilidade, isolamento e handoff** — PRD DoD + retro PRD-002

  **Trigger / entry point:** Tarefas 1.0–5.0 concluídas.  
  **Enables:** PRD-002 SessionStore/pool com `FakeSdkFacade` e contrato estável.  
  **Depends on:** Tarefas 1.0–5.0.

  **Acceptance criteria:**
  - NDJSON send start/end schema v1 com redaction ADR-025.
  - `test_facade_imports.py` verde; `rg "cursor_sdk" src/` → só `sdk_facade.py`.
  - Gate ADR-026 verde; cobertura ≥85%.
  - Demo: `pytest tests/unit/test_facade.py -v` sem API key.
  - PRD-002 §7/§9/§11 atualizados com aprendizados.

  - [x] 6.1 Teste TDD logs NDJSON send start/end
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Capturar logs via `caplog` ou logger injetado; assertar campos obrigatórios ADR-018 (`v`, `ts`, `level`, `event`, `agent_id`, `run_id`, `duration_ms`, `status`); `session_id`/`session_key` opcionais `null`.
    - **Why**: FR-9.
    - **Pattern**: [ADR-018 schema v1](../../docs/decisions/ADR-018-observability-logs.md).
    - **Verify**: `uv run pytest tests/unit/test_facade.py -k "log" -v` RED→GREEN.

  - [x] 6.2 Implementar emissor NDJSON com redaction
    - **File**: `src/cursor_agent/facade_logging.py` (create new) ou `sdk_facade.py` (modify)
    - **What**: Funções `emit_send_start` / `emit_send_end`; nunca logar `api_key`; `LogContext` opcional.
    - **Why**: FR-9 / ADR-025.
    - **Pattern**: ADR-018 + ADR-025 redaction.
    - **Verify**: Teste 6.1 passa.

  - [x] 6.3 Consolidar `test_facade_imports.py` pós-`AsyncSdkFacade`
    - **File**: `tests/unit/test_facade_imports.py` (modify existing)
    - **What**: Assertar que exatamente `sdk_facade.py` importa `cursor_sdk`; nenhum outro módulo em `src/`.
    - **Why**: FR-1 / métrica §8.
    - **Pattern**: `rg "cursor_sdk" src/` manual.
    - **Verify**: `uv run pytest tests/unit/test_facade_imports.py -v` passa.

  - [x] 6.4 Executar gate de qualidade local (sem integração)
    - **File**: — (verificação)
    - **What**: Gate ADR-026 completo + `pytest tests/unit/ -v`.
    - **Why**: DoD PRD-001; CI local §8.
    - **Pattern**: [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: Todos os comandos exit 0 sem `CURSOR_API_KEY`.

  - [x] 6.5 Executar `/code-review` antes do handoff
    - **File**: — (protocolo em [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md))
    - **What**: `/code-review` com [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc); veredito **Aprovado** ou **Aprovado com ressalvas**.
    - **Why**: Gate ADR-022/023 antes de encerrar PRD-001.
    - **Pattern**: [engineering/tasks/README.md](../README.md#fluxo-para-agentes-de-longa-duração).
    - **Verify**: Relatório arquivado ou citado no handoff.

  - [x] 6.6 Revisar PRD-002 com aprendizados da facade (retroalimentação)
    - **File**: [PRD-002-session-store.md](../../docs/prd/PRD-002-session-store.md) (modify existing)
    - **What**: Atualizar §7, §9 e §11 com: shape real de `RunResult`, hook `FakeSdkFacade` para pool, latência create/send se medida, decisão MCP stub, campos de log vs schema v1.
    - **Why**: Gate obrigatório [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) antes de PRD-002.
    - **Pattern**: Retro PRD-000→001 em [PRD-001 §11](../../docs/prd/PRD-001-facade.md#11-desenvolvimento--tdd-e-retroalimentação).
    - **Verify**: Bullets §11 preenchidos; estimativas T1/T2 ajustadas se necessário.

  - [x] 6.7 Confirmar ausência de artefatos fora de escopo
    - **File**: — (review)
    - **What**: Verificar que **não** existem `SessionStore`, `SessionAgentPool`, CLI Typer, gateway; `src/` não importa `examples/`.
    - **Why**: PRD-001 §5 não-objetivos.
    - **Pattern**: `rg "SessionStore|SessionAgentPool" src/` vazio; `rg "examples" src/` vazio.
    - **Verify**: Apenas `sdk_facade.py`, `errors.py`, logging stub em `src/cursor_agent/`.

---

## Mapeamento PRD §10 → tarefas

| PRD | Sub-tarefa neste documento |
|-----|---------------------------|
| T0.1 | 1.1 |
| T0.2 | 1.2 |
| T0.3 | 1.3, 2.5 |
| T0.4 | 1.4, 6.3 |
| T0.5 | 1.5, 6.4 |
| T1 (tipos) | 2.1–2.2 |
| T1 (erros) | 2.3–2.4 |
| T3 FakeSdkFacade | 4.1–4.6 |
| T2.1 context manager | 5.1–5.2 |
| T2.2 create/send/cancel | 5.3–5.4, 5.7–5.8, 5.11–5.12 |
| T2.3 MCP re-inject | 5.5–5.6 |
| T2.4 retry | 5.9–5.10 |
| T2.5 StreamCallbacks | 4.5–4.6, 5.7–5.8 |
| T4 test_facade_unit | 4.x, 5.x, 6.1 |
| FR-6 adapter | 3.1–3.3 |
| Logs FR-9 | 6.1–6.2 |
| DoD retro | 6.6 |
| `/code-review` | 6.5 |
