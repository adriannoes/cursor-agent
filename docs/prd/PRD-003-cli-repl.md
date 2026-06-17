---
id: PRD-003
title: CLI REPL
status: draft
phase: 1
depends_on: [PRD-002]
adrs:
  - ADR-003
  - ADR-004
  - ADR-019
  - ADR-021
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "8"
---

# PRD-003 — CLI REPL

## 1. Introdução / Visão geral

Esta PRD entrega o produto mínimo utilizável do **cursor-agent**: um CLI instalável com REPL interativo, conversa livre com streaming, gestão básica de sessões e exit codes previsíveis para automação.

**Problema:** sem CLI, o usuário não tem interface para conversar com o agente, criar/retomar sessões ou validar o fluxo ponta a ponta (config → pool → facade → SDK).

**Objetivo:** entry point `cursor-agent` (Typer + asyncio), comandos `/new`, `/resume`, `/quit`, subcomando `sessions list`, e resume funcional após restart do processo.

Depende de [PRD-002](PRD-002-session-store.md) (store + pool). Empacotamento: [ADR-019](../decisions/ADR-019-packaging-license.md). Aceite Fase 1: [STRATEGY.md §8](../STRATEGY.md#8-fase-1-cli-sessões).

## 2. Objetivos

1. Publicar CLI via `pyproject.toml` entry point `cursor-agent` (instalação `pip` / `pipx`).
2. REPL async único com loop de conversa e streaming de resposta do assistente.
3. Slash commands mínimos: `/new`, `/resume [session-id]`, `/quit`.
4. Subcomando `cursor-agent sessions list` para listar sessões do `session_key` atual.
5. Exit codes: 0 sucesso/cancelado, 1 erro antes do run (`CursorAgentError`), 2 run com `status == error`.
6. Demonstrar resume após restart: conversa persiste via `agent_id` no SQLite + SDK.

## 3. User Stories

| ID | História |
|----|----------|
| US-1 | Como **desenvolvedor**, quero instalar com `pipx install cursor-agent` e iniciar o REPL imediatamente. |
| US-2 | Como **usuário**, quero conversar em linguagem natural e ver a resposta do agente em streaming. |
| US-3 | Como **usuário**, quero `/new` para iniciar conversa nova sem perder sessões anteriores na lista. |
| US-4 | Como **usuário**, quero `/resume` (sem id ou com UUID) para continuar de onde parei, inclusive após fechar o terminal. |
| US-5 | Como **usuário**, quero `sessions list` para ver títulos e escolher qual sessão retomar. |
| US-6 | Como **automatizador de scripts**, quero exit codes distintos para falha de config/rede vs falha do run. |

## 4. Requisitos funcionais

**FR-1.** O pacote deve declarar entry point console script `cursor-agent` apontando para o módulo CLI ([ADR-019](../decisions/ADR-019-packaging-license.md)).

**FR-2.** Comando default (sem subcomando) deve iniciar REPL interativo usando `asyncio` event loop único por processo.

**FR-3.** O REPL deve carregar config via loader de [PRD-002](PRD-002-session-store.md) e instanciar `AsyncSdkFacade` + `SessionAgentPool` no startup.

**FR-4.** Entrada de texto livre (não começando com `/`) deve ser enviada via `pool.send(session_key, message, session_id=active_session_id, callbacks=..., blocking=True)` — **sempre** com `session_id` da sessão ativa em memória (ver §7).

**FR-5.** `/quit` deve encerrar o REPL com exit code 0 e chamar `facade.close()` no shutdown (via `async with AsyncSdkFacade` ou equivalente).

**FR-6.** `/new` é **orquestração do CLI** (não existe `pool.new`): chamar `facade.create_agent(...)`, persistir com `store.create(SessionCreateParams(...))`, definir `active_session_id = row.id`. Título pode ficar `None` — o primeiro `send` preenche via pool.

**FR-7.** `/resume` deve chamar `pool.get(session_key, session_id?)` (lazy resume + runtime guard), **não** `store.resolve` direto. Sem argumento: `session_id=None` (última por `updated_at`); com UUID: `session_id=<uuid>`. Atualizar `active_session_id` com o `SessionRecord.id` retornado.

**FR-8.** Resume com runtime mismatch deve exibir erro claro e sugerir `/new` ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)) — `pool.get` / `pool.send` levantam `ConfigError`; no REPL interativo, imprimir e continuar o loop (§9).

**FR-9.** Subcomando `cursor-agent sessions list` deve listar sessões do `session_key` atual com `id`, `title`, `updated_at`.

**FR-10.** Exit codes conforme [contracts/async-sdk-facade.md §3](../contracts/async-sdk-facade.md#3-erros-e-exit-codes): 0 = `FINISHED` ou `CANCELLED`; 1 = `CursorAgentError` (auth, config, rede antes do run); 2 = `RunResult.status == ERROR`.

**FR-11.** Testes CLI em `tests/unit/` ou `tests/integration/` leves com `FakeSdkFacade` / Typer `CliRunner` — sem API key na suite padrão.

**FR-12.** Licença MIT e versionamento semver `0.x` no `pyproject.toml`, alinhados a [ADR-019](../decisions/ADR-019-packaging-license.md).

## 5. Não-objetivos (fora de escopo)

- Slash commands completos (`/help`, `/stop`, `/model`, `/compress`, …) — Fase 2 ([PRD-004](PRD-004-slash-commands.md) quando existir).
- Gateway Telegram — Fase 3.
- TUI estilo Hermes — stretch Fase 5 ([ADR-015](../decisions/ADR-015-tui-stretch-goal.md)); MVP usa terminal simples ou Rich básico.
- API Python pública estável (`__all__` em `cursor_agent`) — explicitamente fora de escopo ([STRATEGY §2.8](../STRATEGY.md#28-escopo-de-api-pública)).
- Publicação automática PyPI / GitHub Release — pode ser PR separado; estrutura de packaging deve estar pronta.
- Memória `MEMORY.md`, hooks avançados, perfis `messaging`.

## 6. Considerações de design

- REPL deve ser legível: prompt claro, indicação de sessão ativa (`title` truncado ou primeiros 8 chars do UUID).
- Streaming: montar `StreamCallbacks(on_assistant_text=...)` no CLI e repassar em `pool.send(..., callbacks=...)`; Rich opcional para formatação.
- Ao iniciar sem sessão ativa, orientar o usuário com `/new` ou `/resume` antes do primeiro turno livre.
- Mensagens de erro ao usuário em português ou inglês consistente com o restante do projeto (seguir convenção do código existente).

## 7. Considerações técnicas

| Tópico | Referência |
|--------|------------|
| Packaging MIT, PyPI, entry point | [ADR-019](../decisions/ADR-019-packaging-license.md) |
| Exit codes e erros SDK | [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md) |
| Modelo de sessão e aceite Fase 1 | [STRATEGY.md §8](../STRATEGY.md#8-fase-1-cli-sessões) |
| Pool e store | [PRD-002](PRD-002-session-store.md) |
| Facade | [PRD-001](PRD-001-facade.md) |
| Shutdown graceful | [ADR-021](../decisions/ADR-021-graceful-shutdown.md) — tratar SIGINT/SIGTERM encerrando facade |

**Stack:** Typer para CLI, `asyncio.run()` ou loop dedicado no REPL, integração com `SessionAgentPool`.

**session_key:** derivado do config (`cli:{profile}:{workspace_hash}`) — usuário não digita manualmente.

**Retro PRD-002 (store/pool/config entregues):**

- `build_cli_session_key(cwd, profile="default")` gera `cli:{profile}:{sha256(abs(cwd))[:8]}`; o CLI deve usar `config.runtime.local.cwd` como base do workspace atual. `profile` permanece `"default"` até Fase 5 (`CURSOR_AGENT_PROFILE`).
- `SessionStore` expõe `create`, `resolve`, `list`, `touch`, `update_title` e `update_metadata`; `sessions list` deve exibir `SessionRecord.id`, `title` e `updated_at` filtrados pelo `session_key` atual.
- `SessionAgentPool.send(session_key, message, *, session_id=None, callbacks=None, blocking=True)` é a API de envio para texto livre no REPL; CLI deve manter `blocking=True`.
- `SessionAgentPool.get(session_key, session_id=None)` faz lazy resume via `SdkFacade.resume_agent` e valida `runtime` antes de retomar.
- `load_config(config_path=None, cli_overrides=None)` usa `pydantic-settings` com precedência CLI > env `CURSOR_AGENT__*` > YAML > defaults; falhas públicas chegam como `ConfigError`.
- Após cada `send`, metadata inclui `last_run_id` e `last_status`; o CLI **não** precisa duplicar essa persistência — o pool já grava.

### Bootstrap de startup (produção)

Ordem recomendada no entry point do REPL ([STRATEGY §8](../STRATEGY.md#8-fase-1-cli-sessões)):

1. `config = load_config(config_path=..., cli_overrides=...)` — YAML default em `~/.cursor-agent/config.yaml`; flags Typer futuras via `cli_overrides`.
2. `workspace = str(Path(config.runtime.local.cwd).resolve())`.
3. `session_key = build_cli_session_key(config.runtime.local.cwd)` — `profile="default"`.
4. `store = SessionStore(Path.home() / ".cursor-agent" / "sessions.db")`; `await store.initialize()`.
5. `async with AsyncSdkFacade(api_key=...) as facade:` → `pool = SessionAgentPool(store=store, facade=facade, config=config)`.
6. Estado REPL: `active_session_id: str | None = None` (ou auto-`get` na última sessão existente — decisão de UX; ver §9).

Testes unitários continuam com `SessionStore(tmp_path / "sessions.db")` e `FakeSdkFacade` — nunca tocar `~/.cursor-agent` real.

### Estado REPL e `session_id` (crítico)

O pool **não** rastreia sessão ativa. Sem `session_id` em `send`, `store.resolve(session_key)` retorna a linha **mais recente por `updated_at`**, que pode não ser a escolhida em `/new` ou `/resume`.

| Variável CLI | Uso |
|--------------|-----|
| `session_key` | Derivado do config; constante por processo (salvo reload de config) |
| `active_session_id` | UUID da sessão ativa; **obrigatório** em todo `pool.send(..., session_id=active_session_id)` |
| `active_session_id = None` | Bloquear turno livre; sugerir `/new` ou `/resume` |

### Fluxo `/new` (orquestração CLI — fora do pool)

```text
workspace = str(Path(config.runtime.local.cwd).resolve())
agent_id = await facade.create_agent(
    workspace=workspace,
    model=config.model,
    tool_profile=config.tool_profile,
    runtime_mode=config.runtime.mode,
)
row = await store.create(SessionCreateParams(
    session_key=session_key,
    agent_id=agent_id,
    workspace=workspace,
    runtime=config.runtime.mode,
    tool_profile=config.tool_profile,
    title=None,
))
active_session_id = row.id
```

O primeiro `pool.send` dessa sessão preenche `title` (truncamento 57 chars + `...` quando necessário) e metadata `last_run_id` / `last_status`.

### Fluxo `/resume`

```text
row = await pool.get(session_key, session_id=optional_uuid)
active_session_id = row.id
```

Usar `pool.get`, não `store.resolve` — resume lazy e runtime guard vivem no pool.

### Envio de mensagem livre + streaming

```text
result = await pool.send(
    session_key,
    message,
    session_id=active_session_id,
    callbacks=StreamCallbacks(on_assistant_text=emit_chunk, ...),
    blocking=True,
)
# exit code do turno: map result.status (RunStatus.FINISHED → 0, ERROR → 2)
```

Comparar status com `RunStatus.FINISHED` / `RunStatus.ERROR` — **nunca** `"success"`.

## 8. Métricas de sucesso

| Métrica | Critério de aceite |
|---------|-------------------|
| Instalação | `pip install -e .` expõe comando `cursor-agent` no PATH |
| Conversa | Usuário envia mensagem e recebe resposta do agente |
| Sessões | `/new` e `/resume` funcionam; `sessions list` mostra entradas |
| Persistência | Fechar processo → reabrir → `/resume` continua conversa |
| Exit codes | Scripts distinguem falha pré-run (1) vs run error (2) |
| Testes | Suite CLI com fake passa em `pytest -m "not integration"` |

## 9. Perguntas em aberto

**Decisões fechadas recebidas do PRD-002:**

- Runtime mismatch já é `ConfigError` no pool e a mensagem sugere `/new`; o CLI deve apenas renderizar a falha e sair com code 1 quando ocorrer fora do REPL.
- `RunResult.status == RunStatus.ERROR` retorna normalmente do pool; o CLI deve mapear esse caso para exit code 2 sem transformar em exceção.
- `AgentBusyError` continua responsabilidade do pool/gateway; o REPL usa envio bloqueante e não deve exibir busy para mensagens digitadas em série.
- Títulos são derivados da primeira mensagem no pool/store; `/new` pode criar a sessão sem título e deixar o primeiro `send` preencher.
- **`/new` não existe no pool** — orquestração `create_agent` + `store.create` é exclusiva do CLI (§7).
- **`active_session_id` obrigatório no `send`** — omitir `session_id` resolve a sessão mais recente por `updated_at`, não a ativa do usuário.
- **`/resume` usa `pool.get`**, não `store.resolve` direto.

**Erros: REPL interativo vs exit code (fechado):**

| Contexto | `ConfigError` / `CursorAgentError` | `RunResult.status == ERROR` |
|----------|--------------------------------------|-----------------------------|
| **Dentro do REPL** (slash ou turno) | Imprimir mensagem amigável; **continuar** o loop (não exit 1) | Imprimir falha do run; **continuar** o loop (exit 2 só ao encerrar o processo, se aplicável) |
| **Startup** (config inválida antes do loop) | Exit **1** | N/A |
| **Subcomando one-shot** (ex.: `sessions list` com config quebrada) | Exit **1** | N/A |

No MVP, exit codes 1/2 aplicam-se principalmente ao **último turno antes de `/quit`** ou a falhas de **startup** — documentar no teste de exit codes.

**Sessão ativa ao abrir o REPL (fechado para MVP):**

- Se existir sessão para o `session_key` atual: auto-resume da **mais recente** (`pool.get(session_key)` sem id) **ou** exigir `/resume` explícito.
- **Recomendação MVP:** auto-resume da mais recente quando houver linha; caso contrário, prompt orientando `/new`. Registrar escolha nos testes de `test_cli_repl.py`.

Nenhuma pergunta bloqueante restante para gerar tasks do CLI; packaging e escopo de API continuam em [ADR-019](../decisions/ADR-019-packaging-license.md).

## 10. Tarefas de implementação

### Definition of Done

- [ ] `cursor-agent` entry point
- [ ] `/new`, `/resume`, `/quit`, `sessions list`
- [ ] Exit codes 0/1/2
- [ ] Resume após restart funciona

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T1 | Typer + asyncio loop | 4h | PRD-002 |
| T2 | Wire pool + facade | 4h | T1 |
| T3 | sessions list command | 2h | T1 |
| T4 | testes CLI | 4h | T2 |

### Demo

1. `cursor-agent` → conversa → `/quit` — fluxo interativo básico.
2. Restart do processo → `/resume` — restaura conversa via `agent_id` persistido.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR entry | `tests/unit/test_cli_entry.py` — `cursor-agent --help` via Typer runner | `pytest tests/unit/test_cli_entry.py -v` |
| FR REPL | `tests/unit/test_cli_repl.py` — `/new`, `/quit`, `active_session_id` no send, streaming com fake | `pytest tests/unit/test_cli_repl.py -v` |
| FR sessions | `tests/unit/test_cli_sessions.py` — `sessions list` | `pytest tests/unit/test_cli_sessions.py -v` |
| FR exit codes | `tests/unit/test_cli_exit_codes.py` — 0/1/2 conforme contrato | `pytest tests/unit/test_cli_exit_codes.py -v` |
| FR resume | `tests/unit/test_cli_resume.py` — restart simulado, mesmo `agent_id` | `pytest tests/unit/test_cli_resume.py -v` |

Ordem sugerida: entry point → bootstrap (config + store.initialize + pool) → estado `active_session_id` → `/new` (create_agent + store.create) → `/resume` (pool.get) → turno livre com `session_id` → streaming → exit codes → resume pós-restart.

### Retroalimentação

**Após concluir PRD-003:** revisar e atualizar [PRD-004](PRD-004-slash-commands.md) (§7, §9, §11) antes de slash commands.

**Aprendizados recebidos do PRD-002:**

- [x] Shape real de `SessionRecord` para CLI/listagem: `id`, `session_key`, `agent_id`, `title`, `workspace`, `runtime`, `tool_profile`, `created_at`, `updated_at`, `metadata`.
- [x] Assinatura do pool para REPL: `send(session_key, message, session_id=None, callbacks=None, blocking=True)` e `get(session_key, session_id=None)`.
- [x] Config mínima validada: `model`, `tool_profile`, `runtime.mode`, `runtime.local.cwd`, `runtime.local.setting_sources`; overrides vêm de CLI/env/YAML/defaults.
- [x] Exit code mapping preservado: `CursorAgentError`/`ConfigError` → 1; `RunStatus.ERROR` → 2; `FINISHED`/`CANCELLED` → 0.
- [x] Testes do CLI devem injetar `FakeSdkFacade`, `SessionStore(tmp_path / "sessions.db")` e `load_config(config_path=missing_path)` para rodar sem `CURSOR_API_KEY`.
- [x] `/new` é orquestração CLI (`facade.create_agent` + `store.create`); pool não expõe método `new`.
- [x] REPL deve manter `active_session_id` e passar `session_id=` em todo `pool.send` — omitir resolve a sessão errada quando há múltiplas linhas no mesmo `session_key`.
- [x] `/resume` deve usar `pool.get`, não `store.resolve` direto (lazy resume + runtime guard).
- [x] Paths de produção: `~/.cursor-agent/config.yaml` + `~/.cursor-agent/sessions.db`; chamar `await store.initialize()` no startup.
- [x] Erros no loop interativo: imprimir e continuar; exit 1/2 reservados a startup ou encerramento pós-turno conforme FR-10.
- [x] Título truncado em 57 chars + `...`; status terminal `RunStatus.FINISHED`, não `"success"`.

**Aprendizados a registrar:**

- [ ] UX do REPL async (latência percebida, cold start)
- [ ] Pontos de integração para CommandRouter e Rich
- [ ] Exit codes observados vs. contrato facade
- [ ] Packaging PyPI / entry points ([ADR-019](../decisions/ADR-019-packaging-license.md))
- [ ] Implicações para memória v1 (PRD-008) no primeiro turn
