# Tarefas — PRD-003 CLI REPL (Fase 1)

> **PRD:** [PRD-003-cli-repl.md](../../docs/prd/PRD-003-cli-repl.md)
> **ADRs:** [ADR-003](../../docs/decisions/ADR-003-cross-runtime-resume.md) (cross-runtime resume), [ADR-004](../../docs/decisions/ADR-004-session-key-workspace.md) (session key por workspace), [ADR-019](../../docs/decisions/ADR-019-packaging-license.md) (packaging MIT + entry point), [ADR-021](../../docs/decisions/ADR-021-graceful-shutdown.md) (SIGINT/SIGTERM dispose), [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) (TDD + retro), [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md) (gate CI)
> **Contrato:** [async-sdk-facade.md §3](../../docs/contracts/async-sdk-facade.md#3-erros-e-exit-codes) (exit codes)
> **Escopo deste documento:** Fase 1 — CLI Typer instalável, REPL async com streaming, slash commands mínimos (`/new`, `/resume`, `/quit`), subcomando `sessions list`, exit codes 0/1/2 e resume pós-restart. **Fora de escopo:** slash commands completos (`/help`, `/stop`, `/model`, `/compress`), gateway Telegram, TUI Rich avançada, API Python pública estável, publicação automática PyPI.
> **Status:** Fase 2 completa — sub-tasks detalhadas prontas para implementação.

## Relevant Files

- `pyproject.toml` — adicionar `typer` (e `rich` opcional) como runtime, `[project.scripts]` `cursor-agent`, metadata MIT e `license`/`readme` (FR-1, FR-12, ADR-019).
- `uv.lock` — lockfile atualizado após novas dependências.
- `LICENSE` — arquivo MIT (lacuna PRD-002 → ADR-019, FR-12).
- `src/cursor_agent/cli/__init__.py` — pacote público do CLI.
- `src/cursor_agent/cli/app.py` — app Typer + `main()` (alvo do entry point); comando default abre o REPL; subcomando `sessions`.
- `src/cursor_agent/cli/startup.py` — bootstrap de produção (`load_config` → `session_key` → `store.initialize` → `AsyncSdkFacade` → `SessionAgentPool`).
- `src/cursor_agent/cli/repl_session.py` — loop async do REPL e estado `active_session_id`.
- `src/cursor_agent/cli/slash_commands.py` — handlers `/new`, `/resume`, `/quit`.
- `src/cursor_agent/cli/stream_renderer.py` — `StreamCallbacks` que imprimem deltas de texto/tool no terminal.
- `src/cursor_agent/cli/exit_codes.py` — mapeamento `RunStatus`/erros → exit code 0/1/2.
- `tests/unit/test_cli_entry.py` — `cursor-agent --help` via Typer `CliRunner` (FR-1, FR-2).
- `tests/unit/test_cli_repl.py` — `/new`, `/quit`, `active_session_id` no `send`, streaming com `FakeSdkFacade` (FR-2, FR-4, FR-6).
- `tests/unit/test_cli_sessions.py` — `sessions list` filtrado por `session_key` (FR-9).
- `tests/unit/test_cli_exit_codes.py` — exit codes 0/1/2 conforme contrato (FR-10).
- `tests/unit/test_cli_resume.py` — restart simulado mantém `agent_id` (FR-7, US-4).
- `docs/prd/PRD-004-slash-commands.md` — alvo da retroalimentação ao fechar PRD-003 (§11).

### Notes

#### Carryover das tasks anteriores (o que reusar — não recriar)

Contratos **já implementados e testados** em PRD-001/PRD-002 que o CLI apenas consome (ver [tasks-PRD-001](tasks-PRD-001-facade.md), [tasks-PRD-002](tasks-PRD-002-session-store.md)):

- **Config:** `load_config(config_path=None, cli_overrides=None) -> CursorAgentConfig` em `src/cursor_agent/config/loader.py`; precedência CLI > env `CURSOR_AGENT__*` > YAML > defaults; falhas públicas como `ConfigError`. Campos: `model`, `tool_profile`, `runtime.mode`, `runtime.local.cwd`, `runtime.local.setting_sources`. Default path `~/.cursor-agent/config.yaml` (`DEFAULT_CONFIG_PATH`).
- **session_key:** `build_cli_session_key(cwd, profile="default") -> str` em `src/cursor_agent/sessions/models.py` (`cli:{profile}:{sha256(abs(cwd))[:8]}`). Usar `config.runtime.local.cwd` como base; `profile="default"` até Fase 5.
- **Store:** `SessionStore(db_path)` com `initialize()`, `create(SessionCreateParams)`, `resolve(session_key, session_id=None)`, `list(session_key)`, `touch(id)`, `update_title(id, title)`, `update_metadata(id, metadata, merge=True)`. `SessionRecord`: `id`, `session_key`, `agent_id`, `title`, `workspace`, `runtime`, `tool_profile`, `created_at`, `updated_at`, `metadata`.
- **Pool:** `SessionAgentPool(store, facade, config)` com `get(session_key, session_id=None) -> SessionRecord` (lazy resume + runtime guard) e `send(session_key, message, *, session_id=None, callbacks=None, blocking=True) -> RunResult`. **Não existe `pool.new`** — `/new` é orquestração do CLI (`facade.create_agent` + `store.create`).
- **Facade:** `AsyncSdkFacade(api_key=..., bridge_options=..., logger=...)` como `async with`; `create_agent(*, workspace, model, tool_profile, runtime_mode)`; `RunResult(run_id, status, text, usage)`; `RunStatus.{FINISHED,ERROR,CANCELLED}`; `StreamCallbacks(on_assistant_text, on_tool_start, on_tool_end)`. `FakeSdkFacade` para testes sem `CURSOR_API_KEY`.
- **Erros/exit codes:** `CursorAgentError`/`ConfigError` → exit **1**; `RunStatus.ERROR` → exit **2**; `FINISHED`/`CANCELLED` → exit **0** ([contrato §3](../../docs/contracts/async-sdk-facade.md#3-erros-e-exit-codes)). Pool **não** converte `RunStatus.ERROR` em exceção.

#### Lacunas das tasks anteriores que esta iniciativa precisa fechar

Itens previstos por ADR-019/PRD mas **ainda ausentes** no repo (confirmado: `pyproject.toml` sem `[project.scripts]`, sem `license`, sem `typer`; sem arquivo `LICENSE`):

- **Entry point ausente:** `pyproject.toml` não declara `[project.scripts] cursor-agent` (FR-1) — bloqueia `pip install -e .` expor o comando.
- **Licença ausente:** sem `LICENSE` MIT nem campo `license`/`authors`/`readme` no `pyproject.toml` (FR-12, ADR-019).
- **Dependência de CLI ausente:** `typer` (e `rich` opcional) não estão em `dependencies`.

#### Regras de implementação (carryover de estilo)

- **`active_session_id` obrigatório:** todo `pool.send` do REPL passa `session_id=active_session_id`; omitir resolve a sessão mais recente por `updated_at`, que pode não ser a ativa (PRD §7).
- **Status terminal:** comparar com `RunStatus.FINISHED` / `RunStatus.ERROR`, **nunca** `"success"`.
- **Erro no loop interativo:** imprimir mensagem amigável e **continuar** o loop; exit 1/2 só em startup ou no encerramento pós-turno (PRD §9, FR-10).
- **Isolamento SDK:** nenhum módulo `cli/` importa `cursor_sdk`; integra somente via `SdkFacade`/`AsyncSdkFacade` (carryover PRD-001 FR-1).
- **Testes sem secret:** injetar `FakeSdkFacade`, `SessionStore(tmp_path / "sessions.db")` e `load_config(config_path=missing_path)`; nunca tocar `~/.cursor-agent` real (carryover PRD-002).
- **TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)):** cada FR tem sub-task de teste pytest **antes** da sub-task de produção (red → green).
- **Gate de PR ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):**

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

- **Verificação principal do PRD:** `uv run pytest tests/unit/test_cli_entry.py tests/unit/test_cli_repl.py tests/unit/test_cli_sessions.py tests/unit/test_cli_exit_codes.py tests/unit/test_cli_resume.py -v`.

## Tasks

- [x] **1.0 Packaging, licença e scaffold do pacote CLI** — PRD T1 prereq, FR-1, FR-12

  **Trigger / entry point:** PRD-002 entregue (`SessionStore`, `SessionAgentPool`, `load_config`, `FakeSdkFacade`); início do PRD-003.
  **Enables:** `pip install -e .` expõe `cursor-agent`; pacote `cli/` disponível para REPL e subcomando; conformidade de licença para distribuição PyPI futura.
  **Depends on:** [PRD-002](../../docs/prd/PRD-002-session-store.md) concluído; scaffold PRD-000/001 preservado.

  **Acceptance criteria:**
  - `typer` (e `rich`, se adotado) declarados em `dependencies`; `uv.lock` atualizado.
  - `pyproject.toml` declara `[project.scripts] cursor-agent` apontando para o módulo do app Typer.
  - `LICENSE` MIT na raiz e campos `license`/`readme` no `pyproject.toml` (ADR-019).
  - Pacote `src/cursor_agent/cli/` importável sem quebrar gate ADR-026 nem imports públicos existentes.
  - `rg "cursor_sdk" src/cursor_agent/cli` retorna zero hits.

  - [x] 1.1 Escrever teste TDD de metadata de packaging
    - **File**: `tests/test_pyproject_config.py` (modify existing)
    - **What**: Adicionar testes que asseguram `project.scripts["cursor-agent"] == "cursor_agent.cli.app:main"`, `project.license` declara MIT, `project.readme` aponta para `README.md` e `typer` consta em `project.dependencies`.
    - **Why**: FR-1 e FR-12 são pré-requisito de instalação; falham hoje porque o `pyproject.toml` não tem `[project.scripts]` nem `license`.
    - **Pattern**: Reusar `_load_pyproject()` já existente no arquivo; usar `tomllib`.
    - **Verify**: `uv run pytest tests/test_pyproject_config.py -k "scripts or license or typer or readme" -v` falha antes de 1.2/1.3 e passa depois.

  - [x] 1.2 Adicionar dependências de CLI (`typer` + `rich` opcional)
    - **File**: `pyproject.toml`, `uv.lock` (modify existing)
    - **What**: Adicionar `typer>=0.12` (e `rich>=13`, se adotado para formatação) a `dependencies` via `uv add`, preservando o pin `cursor-sdk==0.1.7` e o grupo `dev`.
    - **Why**: FR-2 exige Typer; PRD §6 cita Rich opcional para streaming legível.
    - **Pattern**: Seguir bloco `dependencies` atual; não alterar pins existentes.
    - **Verify**: `uv run python -c "import typer"` passa (e `import rich` se adicionado).

  - [x] 1.3 Declarar entry point, licença MIT e metadata de distribuição
    - **File**: `pyproject.toml` (modify existing), `LICENSE` (create new)
    - **What**: Adicionar `[project.scripts] cursor-agent = "cursor_agent.cli.app:main"`; campos `license = "MIT"`, `readme = "README.md"` e `authors`; criar `LICENSE` MIT na raiz.
    - **Why**: FR-1, FR-12 e [ADR-019](../../docs/decisions/ADR-019-packaging-license.md); fecha a lacuna confirmada (sem `LICENSE`, sem `[project.scripts]`).
    - **Pattern**: [ADR-019](../../docs/decisions/ADR-019-packaging-license.md) (MIT, semver 0.x, entry point `cursor-agent`).
    - **Verify**: `uv run pytest tests/test_pyproject_config.py -v` passa; `rg "MIT License" LICENSE` retorna hit.
    - **Integration**: O entry point `cursor_agent.cli.app:main` é o alvo criado em 1.4 e implementado em 2.2.

  - [x] 1.4 Criar scaffold do pacote `cli/` com app stub
    - **File**: `src/cursor_agent/cli/__init__.py`, `src/cursor_agent/cli/app.py` (create new)
    - **What**: Criar pacote `cli` com docstring curta; em `app.py`, definir `app = typer.Typer()` e `def main() -> None: app()` (alvo do entry point), sem lógica de REPL ainda.
    - **Why**: Permite TDD incremental do REPL e garante que o entry point resolve antes de detalhar comportamento.
    - **Pattern**: Seguir `src/cursor_agent/sessions/__init__.py`; comentários/código em inglês; **sem** `import cursor_sdk`.
    - **Verify**: `uv run python -c "from cursor_agent.cli.app import main, app"` não falha; `rg "cursor_sdk" src/cursor_agent/cli` retorna zero hits.

- [x] **2.0 Bootstrap de startup + app Typer + REPL async** — PRD T1, FR-2, FR-3

  **Trigger / entry point:** Usuário executa `cursor-agent` sem subcomando (entry point da Tarefa 1.0).
  **Enables:** Loop de conversa, slash commands (Tarefa 3.0) e subcomando `sessions` (Tarefa 4.0) sobre pool/facade já conectados.
  **Depends on:** Tarefa 1.0; contratos carryover de `load_config`, `SessionStore`, `SessionAgentPool`, `AsyncSdkFacade`.

  **Acceptance criteria:**
  - Comando default inicia REPL interativo com **um** event loop asyncio por processo.
  - Bootstrap segue a ordem PRD §7: `load_config` → `workspace` resolvido → `build_cli_session_key` → `store.initialize()` → `async with AsyncSdkFacade(...)` → `SessionAgentPool(...)`.
  - Estado `active_session_id: str | None` inicializado; ao abrir, auto-resume da mais recente (`pool.get(session_key)`) quando há linha, senão orienta `/new` (decisão MVP registrada em teste).
  - `AsyncSdkFacade` recebe `api_key` de `CURSOR_API_KEY` sem logá-la; SIGINT/SIGTERM dispõem a facade (ADR-021).
  - Falha de config no startup encerra com exit **1**.

  > **Ordem segura (double-check):** `startup.py` e `repl_session.py` (com `run_repl`) **antes** da fiação do app Typer — o callback do app importa `run_repl`, então o módulo precisa existir primeiro (evita forward reference no import).

  - [x] 2.1 Escrever teste TDD do bootstrap de startup
    - **File**: `tests/unit/test_cli_repl.py` (create new)
    - **What**: Testar wiring: `session_key` derivado de `config.runtime.local.cwd`; `store.initialize()` chamado; pool construído com `FakeSdkFacade` injetado e `SessionStore(tmp_path / "sessions.db")`; `store_path` default sobreponível.
    - **Why**: FR-3; bootstrap precisa ser injetável para testes sem `CURSOR_API_KEY` nem `~/.cursor-agent`.
    - **Pattern**: Carryover PRD-002 — `load_config(config_path=missing_path)`, `FakeSdkFacade`, `tmp_path`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "bootstrap or startup" -v` falha antes de 2.2 e passa depois.

  - [x] 2.2 Implementar `startup.py` (bootstrap injetável)
    - **File**: `src/cursor_agent/cli/startup.py` (create new)
    - **What**: Helpers tipados: `resolve_workspace(config) -> str`, `session_key_for(config) -> str` (usa `build_cli_session_key(config.runtime.local.cwd)`), `create_store(config, *, store_path=None) -> SessionStore` (reusável por `sessions list` sem facade) e um async context manager `repl_runtime(config, *, store_path=None, facade_factory=AsyncSdkFacade) -> tuple[SessionAgentPool, str, SessionStore]` que abre `async with` da facade e monta o pool na ordem PRD §7.
    - **Why**: FR-3; centraliza o wiring para REPL (2.x) e subcomandos (4.x).
    - **Pattern**: PRD §7 "Bootstrap de startup"; `AsyncSdkFacade(api_key=os.environ.get("CURSOR_API_KEY"))`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "bootstrap or startup" -v` passa.
    - **Integration**: `repl_runtime` é consumido por `run_repl` (2.4); `create_store` + `session_key_for` por `sessions list` (4.2).

  - [x] 2.3 Escrever teste TDD do loop REPL e `active_session_id` inicial
    - **File**: `tests/unit/test_cli_repl.py` (modify existing)
    - **What**: Testar `run_repl(pool, session_key, store, *, reader, writer)` com reader injetável que emite `/quit`: ao abrir com sessão existente faz auto-resume (`pool.get(session_key)`) e define `active_session_id`; sem sessão, escreve orientação para `/new`; encerra com exit 0 e dispõe a facade no fim.
    - **Why**: FR-2 + decisão MVP de sessão ativa (PRD §9); ADR-021 (dispose ao sair).
    - **Pattern**: Reader/writer injetáveis (sem `input()` real); teste **async** (asyncio_mode=auto).
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "loop or active_session or quit" -v` falha antes de 2.4 e passa depois.

  - [x] 2.4 Implementar `repl_session.py` (loop + estado + dispose)
    - **File**: `src/cursor_agent/cli/repl_session.py` (create new)
    - **What**: `run_repl(...)` com `active_session_id: str | None`, auto-resume inicial da mais recente quando há linha, leitura de linhas via reader injetável, despacho `/`-prefixado vs texto livre (handlers em 3.x) e dispose garantido em `finally`; tratar SIGINT/`KeyboardInterrupt` encerrando o loop e dispondo a facade.
    - **Why**: FR-2; estado de sessão ativo vive no CLI, não no pool (PRD §7).
    - **Pattern**: [ADR-021](../../docs/decisions/ADR-021-graceful-shutdown.md) (cancel/dispose ordenado); `async with AsyncSdkFacade` já fecha no `__aexit__`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "loop or active_session or quit" -v` passa.

  - [x] 2.5 Escrever teste TDD do entry point (`--help` + comando default)
    - **File**: `tests/unit/test_cli_entry.py` (create new)
    - **What**: Com Typer `CliRunner`: `--help` sai com code 0 e lista o subcomando `sessions`; invocar sem subcomando chama o REPL (monkeypatch de `run_repl` para um stub que registra a chamada, evitando loop bloqueante).
    - **Why**: FR-1/FR-2; valida que o app default abre o REPL sem travar a suíte.
    - **Pattern**: `typer.testing.CliRunner`; teste **sync** (sem loop ativo) para o `asyncio.run` interno funcionar.
    - **Verify**: `uv run pytest tests/unit/test_cli_entry.py -v` falha antes de 2.6 e passa depois.

  - [x] 2.6 Implementar app Typer com comando default e grupo `sessions`
    - **File**: `src/cursor_agent/cli/app.py` (modify existing)
    - **What**: `app = typer.Typer(invoke_without_command=True)`; callback default que importa e roda `asyncio.run(run_repl(...))` (de `repl_session`, já existente em 2.4) quando nenhum subcomando é dado; registrar sub-Typer `sessions` (comando `list` ligado em 4.0); `main()` chama `app()`.
    - **Why**: FR-2; um event loop por processo via `asyncio.run` único.
    - **Pattern**: Typer callback `@app.callback(invoke_without_command=True)` + `ctx.invoked_subcommand`; import de `run_repl` no topo do módulo (sem inline import).
    - **Verify**: `uv run pytest tests/unit/test_cli_entry.py -v` passa.

- [x] **3.0 Slash commands e turno livre com streaming** — PRD T2, FR-4–FR-8

  **Trigger / entry point:** Entrada do usuário no REPL — texto livre ou linha iniciada por `/`.
  **Enables:** Conversa ponta a ponta (US-2), criação/retomada de sessão (US-3, US-4) e títulos/metadata preenchidos pelo pool no primeiro `send`.
  **Depends on:** Tarefa 2.0 (REPL + pool + `active_session_id`).

  **Acceptance criteria:**
  - Texto livre chama `pool.send(session_key, message, session_id=active_session_id, callbacks=..., blocking=True)`; bloquear turno quando `active_session_id is None` e sugerir `/new`/`/resume`.
  - `/new` orquestra `facade.create_agent(...)` + `store.create(SessionCreateParams(...))` e define `active_session_id = row.id` (sem usar `pool.new`).
  - `/resume [uuid]` chama `pool.get(session_key, session_id=uuid?)` e atualiza `active_session_id`; runtime mismatch (`ConfigError`) imprime erro sugerindo `/new` e **continua** o loop.
  - `/quit` encerra o REPL com exit **0** e dispõe a facade (`close()` via `async with`).
  - Streaming: `StreamCallbacks(on_assistant_text=...)` imprime deltas (não texto acumulado) durante o `send`.

  - [x] 3.1 Escrever teste TDD do turno livre com `session_id=active_session_id`
    - **File**: `tests/unit/test_cli_repl.py` (modify existing)
    - **What**: Com sessão ativa, texto livre chama `pool.send(session_key, msg, session_id=active_session_id, callbacks=..., blocking=True)` (capturar kwargs com spy); com `active_session_id is None`, **não** chama `send` e escreve orientação `/new`/`/resume`.
    - **Why**: FR-4 + PRD §7 (omitir `session_id` resolveria a sessão errada).
    - **Pattern**: Spy sobre `SessionAgentPool.send`; asserir `session_id` passado.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "free_text or send_session_id" -v` falha antes de 3.2 e passa depois.

  - [x] 3.2 Implementar handler de texto livre no REPL
    - **File**: `src/cursor_agent/cli/repl_session.py` (modify existing)
    - **What**: Roteamento: linha sem `/` → guard de `active_session_id` → `pool.send(..., session_id=active_session_id, callbacks=callbacks, blocking=True)` (parâmetro `callbacks` aceito; pode ser `None` aqui — o renderer real é ligado em 3.8); guardar `last_status` do `RunResult` para exit code (4.x).
    - **Why**: FR-4; turno livre é o caminho principal de conversa (US-2).
    - **Pattern**: PRD §7 "Envio de mensagem livre + streaming"; comparar status com `RunStatus`, nunca `"success"`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "free_text or send_session_id" -v` passa.

  - [x] 3.3 Escrever teste TDD do `/new` (orquestração CLI)
    - **File**: `tests/unit/test_cli_repl.py` (modify existing)
    - **What**: `/new` chama `facade.create_agent(...)`, `store.create(SessionCreateParams(...))` com `title=None`, e define `active_session_id = row.id`; o primeiro `send` seguinte preenche o título via pool.
    - **Why**: FR-6; `pool.new` não existe — orquestração é do CLI.
    - **Pattern**: PRD §7 "Fluxo `/new`"; `SessionCreateParams` de `cursor_agent.sessions.models`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "new_command" -v` falha antes de 3.4 e passa depois.

  - [x] 3.4 Implementar `/new` em `slash_commands.py`
    - **File**: `src/cursor_agent/cli/slash_commands.py` (create new)
    - **What**: `handle_new(ctx) -> str` que orquestra `create_agent` + `store.create` e retorna o novo `active_session_id`; `workspace = str(Path(config.runtime.local.cwd).resolve())`.
    - **Why**: FR-6; mantém a persistência dupla (SDK + store) coerente.
    - **Pattern**: PRD §7 fluxo `/new`; `facade.create_agent(workspace=..., model=config.model, tool_profile=config.tool_profile, runtime_mode=config.runtime.mode)`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "new_command" -v` passa.
    - **Integration**: O `active_session_id` retornado alimenta o turno livre (3.2) e o `/resume` (3.6).

  - [x] 3.5 Escrever teste TDD do `/resume` e do runtime mismatch
    - **File**: `tests/unit/test_cli_repl.py` (modify existing)
    - **What**: `/resume` sem arg chama `pool.get(session_key)` (mais recente); `/resume <uuid>` chama `pool.get(session_key, session_id=uuid)`; `active_session_id` atualizado; quando `pool.get` levanta `ConfigError` (runtime mismatch), o REPL imprime erro sugerindo `/new` e **continua** o loop (sem exit 1).
    - **Why**: FR-7 + FR-8; resume usa `pool.get`, não `store.resolve` direto.
    - **Pattern**: PRD §7 "Fluxo `/resume`" + §9 (erro no loop interativo continua).
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "resume_command or runtime_mismatch" -v` falha antes de 3.6 e passa depois.

  - [x] 3.6 Implementar `/resume` e `/quit` em `slash_commands.py`
    - **File**: `src/cursor_agent/cli/slash_commands.py` (modify existing)
    - **What**: `handle_resume(ctx, arg) -> str` via `pool.get(session_key, session_id=arg or None)` retornando `row.id`; `handle_quit(ctx)` sinaliza fim do loop; `ConfigError` capturado e renderizado como mensagem amigável (não propaga no loop).
    - **Why**: FR-7, FR-5; resume lazy + runtime guard vivem no pool.
    - **Pattern**: PRD §7/§9; `ConfigError` de `cursor_agent.errors`.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "resume_command or runtime_mismatch or quit_command" -v` passa.

  - [x] 3.7 Escrever teste TDD do streaming de deltas
    - **File**: `tests/unit/test_cli_repl.py` (modify existing)
    - **What**: Com `FakeSdkFacade(scripted_replies=...)`, asserir que o writer recebe os deltas na ordem emitida por `on_assistant_text` (chunks, não texto acumulado) durante o turno livre.
    - **Why**: FR-6; UX de streaming legível (PRD §6).
    - **Pattern**: [contrato §5](../../docs/contracts/async-sdk-facade.md#5-streaming-streamcallbacks) — `on_assistant_text` recebe delta.
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "streaming or deltas" -v` falha antes de 3.8 e passa depois.

  - [x] 3.8 Implementar `stream_renderer.py` e ligar callbacks ao `send`
    - **File**: `src/cursor_agent/cli/stream_renderer.py` (create new); `src/cursor_agent/cli/repl_session.py` (modify existing)
    - **What**: `build_stream_callbacks(writer) -> StreamCallbacks` que escreve deltas de `on_assistant_text` (e opcionalmente eventos de tool) no writer; passar ao `pool.send(..., callbacks=...)`.
    - **Why**: FR-6; isola a renderização do loop para testabilidade.
    - **Pattern**: `StreamCallbacks` de `cursor_agent.sdk_facade`; Rich opcional sem quebrar testes (writer injetável).
    - **Verify**: `uv run pytest tests/unit/test_cli_repl.py -k "streaming or deltas" -v` passa.

- [x] **4.0 Subcomando `sessions list` e exit codes** — PRD T3, FR-9, FR-10

  **Trigger / entry point:** Usuário executa `cursor-agent sessions list` (one-shot) ou encerra um turno do REPL.
  **Enables:** Usuário escolhe qual sessão retomar (US-5); scripts distinguem falha pré-run de falha de run (US-6).
  **Depends on:** Tarefa 2.0 (bootstrap/`session_key`); Tarefa 3.0 (turno livre cujo status mapeia exit code).

  **Acceptance criteria:**
  - `sessions list` lista sessões do `session_key` atual com `id`, `title` e `updated_at` (via `store.list`), sem exigir `CURSOR_API_KEY`.
  - Exit codes conforme [contrato §3](../../docs/contracts/async-sdk-facade.md#3-erros-e-exit-codes): `FINISHED`/`CANCELLED` → 0; `CursorAgentError`/`ConfigError` pré-run → 1; `RunStatus.ERROR` → 2.
  - Mapeamento de exit code centralizado em `cli/exit_codes.py` e aplicado a subcomandos one-shot e ao encerramento pós-turno.
  - Subcomando one-shot com config quebrada sai com exit **1** (não levanta traceback cru).

  - [x] 4.1 Escrever teste TDD do `sessions list`
    - **File**: `tests/unit/test_cli_sessions.py` (create new)
    - **What**: Com `SessionStore(tmp_path)` semeado e `CliRunner`, `cursor-agent sessions list` imprime `id`, `title` e `updated_at` apenas das sessões do `session_key` atual; lista vazia mostra mensagem amigável; não exige `CURSOR_API_KEY`.
    - **Why**: FR-9; usuário escolhe qual sessão retomar (US-5).
    - **Pattern**: `store.list(session_key)`; injetar `store_path`/`config_path` para isolar o teste.
    - **Verify**: `uv run pytest tests/unit/test_cli_sessions.py -v` falha antes de 4.2 e passa depois.

  - [x] 4.2 Implementar comando `sessions list`
    - **File**: `src/cursor_agent/cli/app.py` (modify existing)
    - **What**: Comando `sessions list` one-shot que carrega config, deriva `session_key`, abre store (sem precisar da facade para listar) e renderiza `store.list(session_key)`; não instanciar `AsyncSdkFacade` quando só lista.
    - **Why**: FR-9; listar não deve exigir bridge SDK nem secret.
    - **Pattern**: PRD §7 (retro PRD-002 — `sessions list` exibe `SessionRecord.id/title/updated_at`).
    - **Verify**: `uv run pytest tests/unit/test_cli_sessions.py -v` passa.

  - [x] 4.3 Escrever teste TDD do mapeamento de exit codes
    - **File**: `tests/unit/test_cli_exit_codes.py` (create new)
    - **What**: `exit_code_for_status(RunStatus.FINISHED|CANCELLED) == 0`, `RunStatus.ERROR == 2`; `exit_code_for_error(ConfigError|CursorAgentError) == 1`; subcomando one-shot com `config_path` inválido (ou env quebrado) sai com code 1 via `CliRunner`.
    - **Why**: FR-10 + [contrato §3](../../docs/contracts/async-sdk-facade.md#3-erros-e-exit-codes); scripts distinguem falha pré-run de run error (US-6).
    - **Pattern**: Carryover PRD-002 — `CursorAgentError`/`ConfigError` → 1; `RunStatus.ERROR` → 2; `FINISHED`/`CANCELLED` → 0.
    - **Verify**: `uv run pytest tests/unit/test_cli_exit_codes.py -v` falha antes de 4.4 e passa depois.

  - [x] 4.4 Implementar `exit_codes.py` e aplicar nos pontos de saída
    - **File**: `src/cursor_agent/cli/exit_codes.py` (create new); `src/cursor_agent/cli/app.py` (modify existing)
    - **What**: `exit_code_for_status(status: RunStatus) -> int` e `exit_code_for_error(exc: BaseException) -> int`; aplicar via `typer.Exit(code=...)` em subcomandos one-shot (erro de startup → 1) e no encerramento pós-turno do REPL (último `RunStatus` antes de `/quit`).
    - **Why**: FR-10; centralizar evita divergência de códigos entre caminhos.
    - **Pattern**: [contrato §3](../../docs/contracts/async-sdk-facade.md#3-erros-e-exit-codes); PRD §9 (exit 1/2 em startup ou pós-turno; loop interativo continua).
    - **Verify**: `uv run pytest tests/unit/test_cli_exit_codes.py -v` passa.
    - **Integration**: `exit_code_for_status` consome o `last_status` registrado no turno livre (3.2).

- [x] **5.0 Validar DoD, resume pós-restart, suíte CLI e retro PRD-004** — PRD T4 + §11

  **Trigger / entry point:** Tarefas 1.0–4.0 concluídas com testes verdes.
  **Enables:** Encerramento do PRD-003 e início do PRD-004 (slash commands) com contratos reais do REPL.
  **Depends on:** Tarefas 1.0–4.0.

  **Acceptance criteria:**
  - Suíte CLI completa passa: `uv run pytest tests/unit/test_cli_entry.py tests/unit/test_cli_repl.py tests/unit/test_cli_sessions.py tests/unit/test_cli_exit_codes.py tests/unit/test_cli_resume.py -v`.
  - Teste de resume pós-restart prova que reabrir o processo + `/resume` reusa o mesmo `agent_id` persistido (US-4, métrica de Persistência).
  - Gate ADR-026 passa sem `CURSOR_API_KEY`; Definition of Done do PRD-003 (§10) atendida.
  - [PRD-004](../../docs/prd/PRD-004-slash-commands.md) §7, §9 e §11 atualizados com aprendizados reais do REPL (CommandRouter, Rich, exit codes observados, packaging).
  - `/code-review` retorna veredito **Aprovado** ou **Aprovado com ressalvas**.

  - [x] 5.1 Escrever teste TDD de resume pós-restart
    - **File**: `tests/unit/test_cli_resume.py` (create new)
    - **What**: Simular restart com **dois pools** sobre o **mesmo** `SessionStore(tmp_path)` e o **mesmo** `FakeSdkFacade` (representa persistência server-side): pool A cria sessão (`create_agent` + `store.create`) e envia; pool B (novo, cache em memória vazio) faz `pool.get(session_key)` e asserir que `facade.resume_agent` é chamado com o `agent_id` persistido e que o `send` seguinte funciona.
    - **Why**: US-4 + métrica de Persistência (PRD §8); prova que a conversa sobrevive ao restart via `agent_id` no SQLite.
    - **Pattern**: Pool re-resolve do store; `_resumed_agent_ids` zera entre pools (carryover PRD-002).
    - **Verify**: `uv run pytest tests/unit/test_cli_resume.py -v` falha antes da lógica de bootstrap/resume e passa quando 2.x/3.x estão verdes.

  - [x] 5.2 Executar a suíte CLI completa do PRD-003
    - **File**: — (verificação)
    - **What**: Rodar os cinco arquivos de teste do CLI juntos.
    - **Why**: Métrica de sucesso "Testes" do PRD §8 (suite CLI com fake passa sem integração).
    - **Pattern**: PRD §11 (tabela TDD por FR).
    - **Verify**: `uv run pytest tests/unit/test_cli_entry.py tests/unit/test_cli_repl.py tests/unit/test_cli_sessions.py tests/unit/test_cli_exit_codes.py tests/unit/test_cli_resume.py -v` passa.

  - [x] 5.3 Executar gate ADR-026 completo
    - **File**: — (verificação)
    - **What**: Rodar o gate canônico local sem `CURSOR_API_KEY`.
    - **Why**: Branch precisa estar merge-ready para PRs sem secrets.
    - **Pattern**: [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: `ruff check src tests && ruff format --check src tests && mypy --strict src && pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"` termina com exit code 0.

  - [x] 5.4 Retroalimentar PRD-004 com aprendizados reais
    - **File**: `docs/prd/PRD-004-slash-commands.md` (modify existing)
    - **What**: Atualizar §7, §9 e §11 com decisões reais do REPL: pontos de integração para CommandRouter e Rich, exit codes observados vs. contrato, UX async (cold start/latência) e implicações de packaging/entry point.
    - **Why**: Gate obrigatório [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) antes do próximo PRD; espelha os bullets "Aprendizados a registrar" do PRD-003 §11.
    - **Pattern**: Retro PRD-002 → PRD-003 já registrada no PRD-003 §11.
    - **Verify**: PRD-004 contém bullets de aprendizado preenchidos ou `N/A` justificado nas seções §7, §9 e §11.

  - [x] 5.5 Executar `/code-review` do PRD-003
    - **File**: — (processo)
    - **What**: Rodar o protocolo de revisão após DoD e retro.
    - **Why**: AGENTS.md exige veredito aprovado antes de encerrar o PRD.
    - **Pattern**: [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md) e [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc).
    - **Verify**: Veredito final é "Aprovado" ou "Aprovado com ressalvas", com ressalvas registradas se existirem.

  - [x] 5.6 Atualizar índice de tasks
    - **File**: `engineering/tasks/README.md` (modify existing)
    - **What**: Marcar o status do PRD-003 na tabela de índice conforme o estágio (Fase 2 completa → implementado).
    - **Why**: Manter o índice mestre coerente para agentes de longa duração.
    - **Pattern**: Linhas existentes de PRD-000/001/002 na tabela "Índice de planos".
    - **Verify**: Tabela do README reflete o status atual do PRD-003.

---

## Mapeamento PRD §10 → tarefas

| PRD §10 | Parent task neste documento |
|---------|-----------------------------|
| (prereq) Packaging/entry point/licença (FR-1, FR-12) | 1.0 |
| T1 — Typer + asyncio loop | 2.0 |
| T2 — Wire pool + facade (slash + send) | 3.0 |
| T3 — `sessions list` command + exit codes | 4.0 |
| T4 — testes CLI + resume pós-restart | 5.0 |

## Sequência segura de desenvolvimento

> Verificado em double-check de dependências, ordem TDD (RED antes de GREEN) e forward references entre módulos.

### Ordem entre parent tasks

1. Executar **1.0** primeiro: dependências (`typer`), packaging/licença e scaffold `cli/` antes de qualquer lógica. Dentro da 1.0: deps (1.2) **antes** do scaffold `app.py` (1.4), porque `app.py` importa `typer`.
2. Executar **2.0** após 1.0: bootstrap e loop dependem do pacote `cli/` e do entry point.
3. Executar **3.0** após 2.0: slash commands e `send` dependem de `active_session_id` e do pool conectado.
4. Executar **4.0** após 2.0; a parte de **exit code pós-turno** depende de 3.0 (que registra `last_status`). O `sessions list` (4.1/4.2) precisa **apenas** de 2.0 (`create_store` + `session_key_for`), sem facade — pode adiantar se útil.
5. Executar **5.0** por último: valida DoD, resume pós-restart e faz a retro do PRD-004 — não concentra testes tardios (cada FR é testado em RED→GREEN nas tarefas 1–4).

### Ordem dentro das parent tasks (forward references corrigidas)

6. **2.0:** implementar `startup.py` (2.2) e `repl_session.run_repl` (2.4) **antes** da fiação do app Typer (2.6), porque o callback do app importa `run_repl`. Inverter quebraria o import (e os testes de `--help`).
7. **3.0:** o handler de texto livre (3.2) aceita `callbacks` que pode ser `None`; o `stream_renderer` real é ligado em 3.8 — não há dependência circular entre FR-4 e FR-6.

### Invariantes de segurança (carryover)

8. Não importar `cursor_sdk` em `cli/`; integrar só via `SdkFacade`/`AsyncSdkFacade` e `SessionAgentPool`.
9. Todo `pool.send` do REPL passa `session_id=active_session_id`; nunca omitir (resolveria a sessão errada).
10. Erros no loop interativo viram mensagens amigáveis e **continuam** o loop; exit 1/2 reservados a startup e encerramento pós-turno.
11. Comparar status com `RunStatus.FINISHED`/`RunStatus.ERROR`, nunca `"success"`; pool não converte `RunStatus.ERROR` em exceção.
12. Em cada bloco funcional, escrever o teste RED antes da produção GREEN; 5.0 valida DoD e não escreve testes funcionais novos de FR.
