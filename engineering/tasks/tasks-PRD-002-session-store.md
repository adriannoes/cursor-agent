# Tarefas — PRD-002 SessionStore + SessionAgentPool (Fase 1)

> **PRD:** [PRD-002-session-store.md](../../docs/prd/PRD-002-session-store.md)  
> **ADRs:** [ADR-003](../../docs/decisions/ADR-003-cross-runtime-resume.md) (cross-runtime resume), [ADR-004](../../docs/decisions/ADR-004-session-key-workspace.md) (session key por workspace), [ADR-007](../../docs/decisions/ADR-007-config-loader.md) (config loader), [ADR-008](../../docs/decisions/ADR-008-agent-busy-gateway.md) (busy/locks), [ADR-009](../../docs/decisions/ADR-009-session-titles.md) (títulos), [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) (TDD + retro), [ADR-024](../../docs/decisions/ADR-024-error-taxonomy-retry.md) (erros + retry)  
> **Escopo deste documento:** Fase 1 — persistência local de sessões, resolução por `session_key`, pool com lock por sessão e config tipada. Sem CLI Typer/REPL, gateway Telegram, memória ou MCP real.  
> **Status:** Fase 2 completa — sub-tasks detalhadas prontas para implementação.

## Relevant Files

- `pyproject.toml` — dependências runtime novas para PRD-002 (`aiosqlite`, `pydantic-settings`, `PyYAML`) e preservação do gate ADR-026.
- `uv.lock` — lockfile atualizado após adicionar dependências.
- `src/cursor_agent/sessions/__init__.py` — pacote público de sessões.
- `src/cursor_agent/sessions/models.py` — modelos tipados para linhas de sessão, criação e atualização de metadata.
- `src/cursor_agent/sessions/store.py` — `SessionStore` com schema SQLite, CRUD async e resolução por `session_key`.
- `src/cursor_agent/config/__init__.py` — pacote público de configuração.
- `src/cursor_agent/config/loader.py` — loader Pydantic com precedência CLI > env `CURSOR_AGENT__*` > YAML > defaults.
- `src/cursor_agent/pool.py` — `SessionAgentPool`, lazy resume via `SdkFacade`, lock por `session_key`, runtime guard e `LogContext`.
- `src/cursor_agent/sdk_facade.py` — contrato `SdkFacade`, `FakeSdkFacade`, `RunResult`, `RunStatus`, `StreamCallbacks`; dependência direta do pool.
- `src/cursor_agent/errors.py` — `AgentBusyError`, `ConfigError` e demais erros compartilhados.
- `src/cursor_agent/facade_logging.py` — `LogContext` que o pool deve preencher em todo `facade.send`.
- `tests/unit/test_session_store.py` — testes unitários TDD para schema, session key, resolve/list/touch/title/metadata.
- `tests/unit/test_config_loader.py` — testes unitários TDD para precedência de config, YAML e expansão `${VAR}`.
- `tests/unit/test_pool.py` — testes unitários TDD para lazy resume, runtime guard, lock CLI/gateway, `LogContext`, title/touch/metadata.
- `docs/prd/PRD-003-cli-repl.md` — alvo da retroalimentação ao fechar PRD-002.

### Notes

- **Carryover PRD-001:** usar `FakeSdkFacade.send_in_progress` (`asyncio.Event`) para testar busy de forma determinística; a facade não deve levantar `AgentBusyError`.
- **Carryover PRD-001:** o pool deve montar `LogContext(session_id, session_key, agent_id)` em todo `facade.send`; `LogContext` deixa de ser opcional na camada pool.
- **Carryover PRD-001:** `RunResult.status == RunStatus.ERROR` retorna normalmente; o pool não converte status em exceção. `AgentBusyError` e `ConfigError` pertencem ao pool/camada de sessão.
- **Carryover PRD-001:** o pool não importa `cursor_sdk`; integra somente via `SdkFacade` / `FakeSdkFacade`.
- **TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)):** na Fase 2, cada requisito funcional deve ter sub-task de teste pytest antes da sub-task de produção.
- **Gate de PR ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):**

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

- **Verificação principal do PRD:** `uv run pytest tests/unit/test_session_store.py tests/unit/test_config_loader.py tests/unit/test_pool.py -v`.

## Tasks

- [x] **1.0 Preparar dependências e contratos-base da Fase 1** — PRD T1/T3 prerequisites

  **Trigger / entry point:** PRD-001 entregue com `AsyncSdkFacade`, `FakeSdkFacade`, erros e logging disponíveis.  
  **Enables:** `SessionStore`, config loader e pool podem ser implementados sem recriar scaffold ou importar `cursor_sdk` fora da facade.  
  **Depends on:** [PRD-001](../../docs/prd/PRD-001-facade.md) concluído; scaffold PRD-000 preservado.

  **Acceptance criteria:**
  - Dependências runtime necessárias para store/config estão declaradas no projeto e lockfile atualizado.
  - Pacotes `sessions` e `config` existem sem quebrar imports públicos já entregues.
  - Gate básico de import e metadata do pacote permanece verde.

  - [x] 1.1 Adicionar dependências runtime do PRD-002
    - **File**: `pyproject.toml`, `uv.lock` (modify existing)
    - **What**: Adicionar `aiosqlite`, `pydantic-settings` e `pyyaml` como dependências de runtime usando `uv`, sem alterar pins já existentes de `cursor-sdk`.
    - **Why**: `SessionStore` depende de SQLite async; config loader depende de Pydantic Settings v2 e YAML conforme ADR-007.
    - **Pattern**: Seguir `pyproject.toml` existente e preservar grupos `dev`.
    - **Verify**: `uv run python -c "import aiosqlite, pydantic_settings, yaml"` passa após atualizar dependências.

  - [x] 1.2 Criar pacotes vazios `sessions` e `config`
    - **File**: `src/cursor_agent/sessions/__init__.py`, `src/cursor_agent/config/__init__.py` (create new)
    - **What**: Criar pacotes com docstrings curtas e `__all__` inicial vazio, sem imports de produção ainda.
    - **Why**: Permite TDD incremental dos módulos sem misturar scaffold com implementação.
    - **Pattern**: Seguir `src/cursor_agent/__init__.py`; comentários/docstrings de código em inglês.
    - **Verify**: `uv run python -c "import cursor_agent.sessions, cursor_agent.config"` passa.

  - [x] 1.3 Preservar isolamento do SDK e metadata do pacote
    - **File**: `tests/unit/test_facade_imports.py`, `tests/test_package_metadata.py` (modify existing only if needed)
    - **What**: Rodar os testes existentes que garantem que apenas `sdk_facade.py` importa `cursor_sdk` e que `__version__` segue exportado.
    - **Why**: PRD-002 não deve regredir o contrato PRD-001 nem o scaffold PRD-000.
    - **Pattern**: Carryover de `tasks-PRD-001-facade.md` T1/T6.
    - **Verify**: `uv run pytest tests/unit/test_facade_imports.py tests/test_package_metadata.py -v` passa.

- [x] **2.0 Implementar `SessionStore` SQLite async** — PRD T1 (T1.1–T1.4), FR-1–FR-5

  **Trigger / entry point:** Código de sessão precisa criar, resolver, listar e atualizar metadados antes do pool/CLI.  
  **Enables:** Lazy resume por `agent_id`, listagem futura de sessões no PRD-003 e isolamento por workspace.  
  **Depends on:** Tarefa 1.0; schema definido em [STRATEGY.md §8](../../docs/STRATEGY.md#8-fase-1-cli-sessões).

  **Acceptance criteria:**
  - Schema SQLite corresponde ao PRD-002 FR-1, incluindo índice `idx_sessions_key`.
  - `session_key` segue `cli:{profile}:{workspace_hash}` com `sha256(abs(cwd))[:8]`.
  - `create`, `resolve`, `touch`, `list` e atualização JSON de `metadata` funcionam sem API key.
  - `resolve(session_key)` retorna a sessão mais recente; `title` deriva da primeira mensagem com truncamento de 60 caracteres.

  - [x] 2.1 Escrever testes TDD para `session_key` e título
    - **File**: `tests/unit/test_session_store.py` (create new)
    - **What**: Testar helper de `session_key` com `cli:{profile}:{sha256(abs(cwd))[:8]}` e helper de título com `strip`, truncamento a 60 caracteres e ellipsis.
    - **Why**: FR-2 e FR-5 são regras puras; testar antes de SQLite reduz risco e facilita diagnóstico.
    - **Pattern**: [ADR-004](../../docs/decisions/ADR-004-session-key-workspace.md) e [ADR-009](../../docs/decisions/ADR-009-session-titles.md).
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "session_key or title" -v` falha antes da implementação e passa após 2.2.

  - [x] 2.2 Implementar helpers puros de sessão
    - **File**: `src/cursor_agent/sessions/models.py` (create new)
    - **What**: Implementar funções tipadas como `build_cli_session_key(cwd: Path | str, profile: str = "default") -> str` e `title_from_first_user_message(message: str) -> str`, com mensagens de erro claras para inputs inválidos.
    - **Why**: O store e o pool precisam da mesma regra de key/título sem duplicação.
    - **Pattern**: Funções pequenas e grep-friendly; sem import de `aiosqlite` neste módulo.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "session_key or title" -v` passa.
    - **Integration**: `build_cli_session_key` será consumido por PRD-003 para `/new`, `/resume` e `sessions list`.

  - [x] 2.3 Escrever testes TDD de schema SQLite e índice
    - **File**: `tests/unit/test_session_store.py` (modify existing)
    - **What**: Testar que `SessionStore.initialize()` cria a tabela `sessions` com colunas do FR-1 e índice `idx_sessions_key`.
    - **Why**: Persistência local é a fonte de verdade de metadados; schema errado quebra resume/list após restart.
    - **Pattern**: Usar `tmp_path` para DB isolado e `aiosqlite` em testes async sem API key.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "schema" -v` falha antes da implementação e passa após 2.4.

  - [x] 2.4 Implementar inicialização do `SessionStore`
    - **File**: `src/cursor_agent/sessions/store.py` (create new)
    - **What**: Criar `SessionStore` com path de DB injetado, método `initialize()` idempotente, SQL parametrizado e schema conforme PRD-002 FR-1.
    - **Why**: Todas as operações de sessão dependem de schema pronto e seguro.
    - **Pattern**: `aiosqlite` com context manager; consultas SQL nunca por concatenação de input.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "schema" -v` passa.

  - [x] 2.5 Escrever testes TDD para `create`, `resolve`, `list` e `touch`
    - **File**: `tests/unit/test_session_store.py` (modify existing)
    - **What**: Testar criação com UUID, `agent_id`, `workspace`, `runtime`, `tool_profile`; `resolve(session_key)` retornando mais recente por `updated_at DESC`; `resolve(session_key, session_id)` retornando sessão específica; `list(session_key)` ordenado; `touch()` atualizando timestamp.
    - **Why**: FR-3 e FR-4 são o contrato mínimo que o pool consome para lazy resume e atualização pós-send.
    - **Pattern**: Usar relógio injetável ou timestamps controláveis para evitar sleeps.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "create or resolve or list or touch" -v` falha antes da implementação e passa após 2.6.

  - [x] 2.6 Implementar operações CRUD do `SessionStore`
    - **File**: `src/cursor_agent/sessions/store.py`, `src/cursor_agent/sessions/models.py` (modify existing)
    - **What**: Implementar modelos/dataclasses tipados para linhas de sessão e métodos `create`, `resolve`, `list`, `touch`.
    - **Why**: O pool precisa de `id`, `session_key`, `agent_id`, `workspace`, `runtime`, `tool_profile`, `title` e `metadata` resolvidos de forma consistente.
    - **Pattern**: Retornar objetos tipados em vez de tuplas cruas; timestamps em UTC ISO-8601.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "create or resolve or list or touch" -v` passa.
    - **Integration**: `SessionAgentPool` usará `resolve` antes de `resume_agent` e `touch` após `facade.send`.

  - [x] 2.7 Escrever testes TDD para atualização JSON de `metadata`
    - **File**: `tests/unit/test_session_store.py` (modify existing)
    - **What**: Testar merge/replace de `metadata` com campos como `memory_injected`, `status`, `last_run_id` e `last_status`, preservando JSON válido.
    - **Why**: PRD-002 FR-3 e PRD-003 `/status` dependem de metadata sem corromper histórico do SDK.
    - **Pattern**: Usar `json` da stdlib; não usar `pickle`.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "metadata" -v` falha antes da implementação e passa após 2.8.

  - [x] 2.8 Implementar atualização de `metadata`
    - **File**: `src/cursor_agent/sessions/store.py`, `src/cursor_agent/sessions/models.py` (modify existing)
    - **What**: Implementar método explícito para atualizar metadata JSON de uma sessão, validando que o payload é serializável e mantendo erros com valor recebido.
    - **Why**: Pool precisa persistir `last_run_id` e `last_status` após cada send, inclusive quando `RunStatus.ERROR` retorna normalmente.
    - **Pattern**: Manter metadata como `dict[str, object]`; serialização via `json.dumps`.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py -k "metadata" -v` passa.

- [x] **3.0 Implementar config loader Pydantic** — PRD T3, FR-9–FR-10

  **Trigger / entry point:** Store/pool/CLI precisam de config validada antes de iniciar sessão ou retomar runtime.  
  **Enables:** Runtime guard do pool, defaults do CLI no PRD-003 e configuração consistente para tool profile/model/cwd.  
  **Depends on:** Tarefa 1.0; [ADR-007](../../docs/decisions/ADR-007-config-loader.md).

  **Acceptance criteria:**
  - Precedência efetiva: CLI flags > env `CURSOR_AGENT__*` > `~/.cursor-agent/config.yaml` > defaults.
  - `${VAR}` em YAML é expandido com `os.path.expandvars`.
  - Config mínima inclui `model`, `tool_profile`, `runtime.mode`, `runtime.local.cwd`, `runtime.local.setting_sources`.
  - Erros de validação incluem valor recebido e formato esperado.

  - [x] 3.1 Escrever testes TDD para defaults e campos mínimos
    - **File**: `tests/unit/test_config_loader.py` (create new)
    - **What**: Testar config default com `model="composer-2.5"`, `tool_profile="coding"`, `runtime.mode="local"`, `runtime.local.cwd` e `runtime.local.setting_sources`.
    - **Why**: Pool e PRD-003 precisam de config válida sem arquivo YAML obrigatório.
    - **Pattern**: [ADR-007](../../docs/decisions/ADR-007-config-loader.md) e PRD-002 FR-10.
    - **Verify**: `uv run pytest tests/unit/test_config_loader.py -k "defaults" -v` falha antes da implementação e passa após 3.2.

  - [x] 3.2 Implementar modelos Pydantic de config
    - **File**: `src/cursor_agent/config/loader.py` (create new)
    - **What**: Criar `CursorAgentConfig`, `RuntimeConfig`, `LocalRuntimeConfig` e tipos auxiliares com `ConfigDict`, defaults e validação de valores permitidos.
    - **Why**: Config validada na subida evita falhas no meio de um turn.
    - **Pattern**: Pydantic v2; funções públicas tipadas e com docstrings.
    - **Verify**: `uv run pytest tests/unit/test_config_loader.py -k "defaults" -v` passa; `uv run mypy --strict src` passa.

  - [x] 3.3 Escrever testes TDD para YAML e expansão `${VAR}`
    - **File**: `tests/unit/test_config_loader.py` (modify existing)
    - **What**: Testar leitura de `config.yaml` em path temporário, expansão de `${VAR}` via `os.path.expandvars` e erro claro quando YAML tem shape inválido.
    - **Why**: ADR-007 exige YAML como fonte persistida e expansão explícita de variáveis.
    - **Pattern**: Usar `tmp_path` e `monkeypatch` para env; sem tocar `~/.cursor-agent` real.
    - **Verify**: `uv run pytest tests/unit/test_config_loader.py -k "yaml or expandvars" -v` falha antes da implementação e passa após 3.4.

  - [x] 3.4 Implementar leitura YAML segura
    - **File**: `src/cursor_agent/config/loader.py` (modify existing)
    - **What**: Implementar carregamento com `yaml.safe_load`, tratar arquivo ausente como `{}`, expandir variáveis e validar shape antes de construir o modelo final.
    - **Why**: Config local precisa ser robusta, sem executar conteúdo arbitrário.
    - **Pattern**: Segurança Python: `safe_load`, validação Pydantic e mensagens com valor recebido.
    - **Verify**: `uv run pytest tests/unit/test_config_loader.py -k "yaml or expandvars" -v` passa.

  - [x] 3.5 Escrever testes TDD para precedência CLI > env > YAML > defaults
    - **File**: `tests/unit/test_config_loader.py` (modify existing)
    - **What**: Testar overrides com env `CURSOR_AGENT__*` e dict de CLI flags, incluindo valores aninhados de runtime local.
    - **Why**: PRD-002 FR-9 e PRD-003 dependem de comportamento previsível entre flags, env e arquivo.
    - **Pattern**: Nested env com `__` conforme ADR-007.
    - **Verify**: `uv run pytest tests/unit/test_config_loader.py -k "precedence" -v` falha antes da implementação e passa após 3.6.

  - [x] 3.6 Implementar função pública de carregamento
    - **File**: `src/cursor_agent/config/loader.py`, `src/cursor_agent/config/__init__.py` (modify existing)
    - **What**: Implementar `load_config(config_path: Path | None = None, cli_overrides: Mapping[str, object] | None = None) -> CursorAgentConfig` com precedência ADR-007 e exports públicos.
    - **Why**: Pool e CLI precisam consumir a mesma config sem duplicar merge manual.
    - **Pattern**: Merge explícito e pequeno; não importar `sessions` nem `pool`.
    - **Verify**: `uv run pytest tests/unit/test_config_loader.py -v` passa.
    - **Integration**: `SessionAgentPool` usará `CursorAgentConfig.runtime.mode`, `model`, `tool_profile` e `runtime.local.cwd`.

- [x] **4.0 Implementar `SessionAgentPool` integrado à facade** — PRD T2 (T2.1–T2.3), FR-6–FR-8

  **Trigger / entry point:** Chamadores enviam mensagens por `session_key` e precisam retomar/criar agentes sem acessar SQLite ou SDK diretamente.  
  **Enables:** PRD-003 REPL (`/resume`, `/new`, envio de mensagens) e PRD-006 gateway com busy não bloqueante.  
  **Depends on:** Tarefas 2.0 e 3.0; `SdkFacade`, `FakeSdkFacade`, `LogContext`, `AgentBusyError` e `ConfigError` de PRD-001.

  **Acceptance criteria:**
  - `get(session_key)` faz lazy resume via `agent_id` persistido usando `SdkFacade.resume_agent`.
  - Resume com `session.runtime != config.runtime.mode` falha com `ConfigError` acionável sugerindo `/new`.
  - `send(session_key, message)` serializa por `asyncio.Lock` em modo CLI e levanta `AgentBusyError` em modo gateway/try-acquire.
  - Todo `facade.send` recebe `LogContext(session_id, session_key, agent_id)` preenchido a partir da sessão resolvida.
  - Após `send`, store atualiza `updated_at`, `title` quando vazio e metadata útil (`last_run_id`, `last_status`) sem tratar `RunStatus.ERROR` como exceção.

  - [x] 4.1 Escrever testes TDD para construção e lazy resume do pool
    - **File**: `tests/unit/test_pool.py` (create new)
    - **What**: Testar `SessionAgentPool` com `SessionStore`, `CursorAgentConfig` e `FakeSdkFacade` injetados; `get(session_key)` deve resolver sessão e chamar `resume_agent(agent_id, workspace=..., tool_profile=row.tool_profile)`.
    - **Why**: FR-7 é o caminho base de retomada por SQLite + SDK.
    - **Pattern**: Injeção por construtor; nenhum teste do pool exige `CURSOR_API_KEY`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "lazy_resume" -v` falha antes da implementação e passa após 4.2.

  - [x] 4.2 Implementar esqueleto e `get()` do `SessionAgentPool`
    - **File**: `src/cursor_agent/pool.py` (create new)
    - **What**: Criar classe `SessionAgentPool` com dependências injetadas (`SessionStore`, `SdkFacade`, `CursorAgentConfig`) e método `get(session_key, session_id: str | None = None)`.
    - **Why**: Centraliza acesso ao SDK e impede que CLI/gateway manipulem SQLite ou facade diretamente.
    - **Pattern**: Usar `SdkFacade` Protocol; não importar `cursor_sdk`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "lazy_resume" -v` passa.

  - [x] 4.3 Escrever testes TDD para runtime guard
    - **File**: `tests/unit/test_pool.py` (modify existing)
    - **What**: Testar que sessão com `runtime` diferente de `config.runtime.mode` levanta `ConfigError` antes de adquirir lock ou chamar `resume_agent`, com mensagem sugerindo `/new`.
    - **Why**: FR-6 e ADR-003 pertencem ao pool, porque o store não conhece a config atual.
    - **Pattern**: Usar fake/spies simples para confirmar que a facade não foi chamada.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "runtime" -v` falha antes da implementação e passa após 4.4.

  - [x] 4.4 Implementar runtime guard no pool
    - **File**: `src/cursor_agent/pool.py` (modify existing)
    - **What**: Validar `session.runtime == config.runtime.mode` em `get()`/`send()` antes de lock e resume; levantar `ConfigError` com runtime recebido, esperado e sugestão `/new`.
    - **Why**: Cross-runtime resume pode corromper expectativas de execução local/cloud.
    - **Pattern**: [ADR-003](../../docs/decisions/ADR-003-cross-runtime-resume.md); `ConfigError` de `src/cursor_agent/errors.py`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "runtime" -v` passa.

  - [x] 4.5 Escrever testes TDD para locks CLI e gateway
    - **File**: `tests/unit/test_pool.py` (modify existing)
    - **What**: Testar modo CLI bloqueante com dois `send` concorrentes aguardando `FakeSdkFacade(send_release=...)`; testar modo gateway/`blocking=False` levantando `AgentBusyError` enquanto `send_in_progress` está setado.
    - **Why**: FR-8 e ADR-008 são a proteção contra corrupção de estado por mensagens concorrentes.
    - **Pattern**: Não usar sleeps; sincronizar com `send_in_progress.wait()` e `send_release.set()`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "lock or busy" -v` falha antes da implementação e passa após 4.6.

  - [x] 4.6 Implementar lock por `session_key`
    - **File**: `src/cursor_agent/pool.py` (modify existing)
    - **What**: Manter mapa `session_key -> asyncio.Lock`; `send(..., blocking=True)` aguarda lock, `send(..., blocking=False)` tenta adquirir e levanta `AgentBusyError` se ocupado; liberar sempre em `finally`.
    - **Why**: CLI deve serializar, gateway deve rejeitar rápido com mensagem amigável.
    - **Pattern**: ADR-008; a facade nunca levanta `AgentBusyError`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "lock or busy" -v` passa.

  - [x] 4.7 Escrever testes TDD para `send` wrapper e `LogContext`
    - **File**: `tests/unit/test_pool.py` (modify existing)
    - **What**: Testar que `send` resolve a sessão, monta `LogContext(session_id, session_key, agent_id)`, repassa callbacks, chama `facade.send`, atualiza `touch`, preenche título se vazio e persiste `last_run_id`/`last_status`.
    - **Why**: PRD-002 §9 fecha que o pool não pode omitir contexto de log; PRD-003 consome título/listagem/status.
    - **Pattern**: `LogContext` de `src/cursor_agent/facade_logging.py`; `RunStatus.FINISHED`, não `"success"`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "send_wrapper or log_context or title or metadata" -v` falha antes da implementação e passa após 4.8.

  - [x] 4.8 Implementar `send` wrapper completo
    - **File**: `src/cursor_agent/pool.py` (modify existing)
    - **What**: Implementar `send(session_key, message, *, session_id=None, callbacks=None, blocking=True) -> RunResult` com resolve, runtime guard, lock, `LogContext`, chamada à facade, atualização de store e liberação em `finally`.
    - **Why**: Este é o contrato que CLI/gateway usarão para conversar sem conhecer detalhes da persistência dupla.
    - **Pattern**: PRD-002 T2.3; `RunResult.status == RunStatus.ERROR` retorna normalmente e ainda libera lock.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "send_wrapper or log_context or title or metadata" -v` passa.
    - **Integration**: PRD-003 REPL chamará este método para mensagens livres e `/resume`.

  - [x] 4.9 Escrever testes TDD para propagação de erros e liberação de lock
    - **File**: `tests/unit/test_pool.py` (modify existing)
    - **What**: Testar que `CursorAgentError` da facade propaga, `RunResult(status=RunStatus.ERROR)` retorna sem exceção e o lock fica liberado nos dois casos.
    - **Why**: PRD-002 §7 separa erro pré-run de run com status terminal de erro; CLI decide exit code no PRD-003.
    - **Pattern**: Usar fake customizado ou monkeypatch de `FakeSdkFacade.send`.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -k "error or finally" -v` falha antes da implementação e passa após 4.10.

  - [x] 4.10 Completar paths de erro do pool
    - **File**: `src/cursor_agent/pool.py` (modify existing)
    - **What**: Ajustar `try/finally` e atualização de metadata para cobrir exceções pré-run, status `ERROR` e cancelamento sem deadlock.
    - **Why**: Um lock preso bloquearia a sessão inteira após falhas.
    - **Pattern**: Taxonomia em PRD-002 §7; `RunStatus.ERROR` não vira exceção.
    - **Verify**: `uv run pytest tests/unit/test_pool.py -v` passa.

- [x] **5.0 Validar Definition of Done e retroalimentar PRD-003** — PRD T4 + §11

  **Trigger / entry point:** Store, config loader e pool concluídos com testes unitários.  
  **Enables:** Início do PRD-003 CLI REPL com decisões e contratos reais de sessão.  
  **Depends on:** Tarefas 1.0–4.0 concluídas.

  **Acceptance criteria:**
  - `uv run pytest tests/unit/test_session_store.py tests/unit/test_config_loader.py tests/unit/test_pool.py -v` passa.
  - Gate ADR-026 passa sem `CURSOR_API_KEY`.
  - Definition of Done do PRD-002 está atendida.
  - [PRD-003](../../docs/prd/PRD-003-cli-repl.md) §7, §9 e §11 são atualizados com aprendizados reais do PRD-002 antes de iniciar o REPL.
  - `/code-review` é executado e retorna veredito aprovado ou aprovado com ressalvas antes de encerrar o PRD.

  - [x] 5.1 Executar suite unitária principal do PRD-002
    - **File**: — (verificação)
    - **What**: Rodar os testes unitários criados para store, config loader e pool.
    - **Why**: Métrica de sucesso do PRD-002 exige cobertura sem API key.
    - **Pattern**: PRD-002 §8 e §11.
    - **Verify**: `uv run pytest tests/unit/test_session_store.py tests/unit/test_config_loader.py tests/unit/test_pool.py -v` passa.

  - [x] 5.2 Executar gate ADR-026 completo
    - **File**: — (verificação)
    - **What**: Rodar o gate canônico local sem `CURSOR_API_KEY`.
    - **Why**: Antes de fechar o PRD, o branch precisa estar merge-ready para PRs sem secrets.
    - **Pattern**: [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: `ruff check src tests && ruff format --check src tests && mypy --strict src && pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"` termina com exit code 0.

  - [x] 5.3 Revisar sequence safety antes de marcar PRD-002 como concluído
    - **File**: `engineering/tasks/tasks-PRD-002-session-store.md` (modify existing)
    - **What**: Confirmar que todas as sub-tasks foram executadas em ordem TDD: 1.0 → 2.0 e 3.0 → 4.0 → 5.0, com runtime guard no pool e não no store.
    - **Why**: Evita dependências invertidas e garante desenvolvimento seguro conforme pedido no LGTM.
    - **Pattern**: Checklist “Sequência segura de desenvolvimento” no fim deste documento.
    - **Verify**: Todos os checkboxes concluídos respeitam dependências e nenhum teste funcional foi escrito depois da produção correspondente.

  - [x] 5.4 Retroalimentar PRD-003 com aprendizados reais
    - **File**: `docs/prd/PRD-003-cli-repl.md` (modify existing)
    - **What**: Atualizar §7, §9 e §11 com decisões reais do store/pool/config: assinatura de `SessionAgentPool.send`, shape de listagem, erros que CLI deve mapear e metadata disponível.
    - **Why**: ADR-022 exige retro antes de iniciar o próximo PRD.
    - **Pattern**: Retro PRD-001 → PRD-002 já registrada em PRD-002 §7/§11.
    - **Verify**: PRD-003 contém bullets de aprendizados preenchidos ou `N/A` justificado nas seções §7, §9 e §11.

  - [x] 5.5 Executar `/code-review` do PRD-002
    - **File**: — (processo)
    - **What**: Rodar o protocolo de revisão após DoD e retro.
    - **Why**: AGENTS.md exige review aprovado ou aprovado com ressalvas antes de considerar o PRD encerrado.
    - **Pattern**: [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md) e [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc).
    - **Verify**: Veredito final é “Aprovado” ou “Aprovado com ressalvas”, com ressalvas registradas se existirem.

---

## Mapeamento PRD §10 → tarefas

| PRD §10 | Parent task neste documento |
|---------|-----------------------------|
| T1 — SessionStore aiosqlite | 2.0 |
| T2 — SessionAgentPool | 4.0 |
| T3 — config loader pydantic | 3.0 |
| T4 — testes unit | 2.0, 3.0, 4.0, 5.0 |

## Sequência segura de desenvolvimento

1. Executar **1.0** primeiro para dependências e pacotes vazios.
2. Executar **2.0** e **3.0** depois de 1.0; podem avançar em paralelo porque store e config não devem importar um ao outro.
3. Executar **4.0** somente após 2.0 e 3.0 verdes, porque o pool depende tanto de sessão resolvida quanto de `config.runtime.mode`.
4. Manter o runtime guard em `SessionAgentPool`, não no `SessionStore`.
5. Em cada bloco funcional, escrever teste RED antes da produção GREEN; 5.0 valida DoD, não concentra testes tardios.
6. Não importar `cursor_sdk` fora de `src/cursor_agent/sdk_facade.py`.
7. Não converter `RunResult.status == RunStatus.ERROR` em exceção no pool; exit code é responsabilidade do PRD-003.
8. Testar concorrência com `FakeSdkFacade.send_in_progress` e `send_release`, sem sleeps.
