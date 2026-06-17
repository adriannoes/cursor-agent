---
id: PRD-004
title: Slash commands e display Rich
status: implemented
phase: 2
depends_on: [PRD-003]
adrs:
  - ADR-011
  - ADR-013
  - ADR-018
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "9"
  - path: ../prompts/compress.txt
---

# PRD-004 — Slash commands e display Rich

## 1. Introdução / Visão geral

A Fase 2 evolui o CLI básico (PRD-003) para uma experiência **Hermes-like**: slash commands, streaming visual com Rich e fluxo de compressão de contexto. O problema central é que o REPL atual só cobre sessões mínimas (`/new`, `/resume`, `/quit`); falta controle operacional do agente (`/stop`, `/compress`, `/help`) e feedback visual durante runs com tools.

**Objetivo:** entregar um `CommandRouter` unificado, 8+ comandos priorizados (P0–P2), display Rich com badges de tool e saga `/compress` conforme [ADR-011](../decisions/ADR-011-compress-flow.md) e [ADR-013](../decisions/ADR-013-slash-commands-skills.md).

## 2. Objetivos

- Implementar registry de slash commands com resolução determinística (built-in → skills → mensagem livre).
- Cobrir pelo menos 8 comandos P0–P2 listados na [STRATEGY §9.1](../STRATEGY.md#91-slash-commands).
- Exibir streaming do SDK com Rich (texto do assistant + badges de tool em execução).
- Executar `/compress` com prompt versionado em [prompts/compress.txt](../prompts/compress.txt), mantendo o mesmo `session id`.
- Tratar `/reset` como alias de `/new` ([ADR-013](../decisions/ADR-013-slash-commands-skills.md)).
- Garantir testes unitários do router e dos handlers críticos.

## 3. User Stories

- **Como** desenvolvedor no CLI, **quero** digitar `/help` e ver todos os comandos disponíveis **para** descobrir a UX sem ler a documentação.
- **Como** desenvolvedor, **quero** `/stop` durante um run longo **para** cancelar sem fechar o REPL.
- **Como** desenvolvedor, **quero** `/compress` em sessão longa **para** reduzir contexto sem perder o histórico lógico da sessão (mesmo `session id`).
- **Como** desenvolvedor, **quero** ver badges de tool e streaming em tempo real **para** entender o que o agente está fazendo.
- **Como** desenvolvedor, **quero** `/reset` e `/new` com o mesmo comportamento **para** não me confundir com semânticas diferentes.

## 4. Requisitos funcionais

1. O sistema deve implementar `CommandRouter` com registro de handlers por nome de comando (sem `/`).
2. O router deve resolver input na ordem: comandos built-in reservados → skills (Fase 4; stub vazio aceitável) → mensagem livre ao agente ([ADR-013](../decisions/ADR-013-slash-commands-skills.md)).
3. O sistema deve implementar comandos P0: `/new`, `/reset` (alias de `/new`), `/resume [id]`, `/help`, `/quit`.
4. O sistema deve implementar comandos P1: `/stop` (chama `run.cancel()` via facade), `/model [id]` (default `composer-2.5`).
5. O sistema deve implementar comandos P2: `/retry` (reenvia última mensagem do usuário), `/usage` (tokens se `TurnEndedUpdate.usage` disponível), `/compress`.
6. `/compress` deve seguir a saga de [ADR-011](../decisions/ADR-011-compress-flow.md): status `compressing` → prompt de [compress.txt](../prompts/compress.txt) → `run.wait()` → novo `agent_id` → atualizar mesmo row SQLite → enviar resumo como primeira mensagem.
7. Em falha de `/compress`, o sistema deve manter `agent_id` anterior, limpar status e exibir erro ao usuário.
8. O display Rich deve renderizar streaming de texto do assistant e badges indicando tool em execução (nome + estado).
9. O sistema deve configurar `setting_sources: ["project", "user"]` na facade para carregar rules e MCP do workspace ([STRATEGY §9.2](../STRATEGY.md#92-contexto-e-personalidade)).
10. O sistema deve documentar template opcional `.cursor/hooks.json` para dev e risco de auto-approve no README.
11. O sistema deve incluir testes unitários cobrindo registro de comandos, alias `/reset`, e saga `/compress` com `FakeSdkFacade`.

## 5. Não-objetivos

- Perfil `messaging` e hooks de segurança (PRD-005 / Fase 2b).
- Comandos `/skills`, `/memory`, `/personality`, `/title` (Fases 4 ou backlog).
- TUI completa estilo Hermes ([ADR-015](../decisions/ADR-015-tui-stretch-goal.md) — stretch Fase 5).
- Loader custom de skills paralelo ao SDK.
- Fila de mensagens ou comportamento de gateway (`AgentBusyError` no CLI aguarda ou `/stop`).

## 6. Considerações de design

- **UX do REPL:** manter prompt simples; comandos começam com `/`; mensagens livres passam direto ao pool.
- **Rich:** usar painéis/spinners discretos; badges de tool não devem poluir o stream de texto.
- **`/help`:** listar comandos por prioridade (P0/P1/P2) e indicar que `/reset` = `/new`.
- **`/compress`:** feedback explícito (“Comprimindo contexto…”) durante a saga; em sucesso, confirmar novo agent ativo.
- **Personalidade:** apenas via `.cursor/rules` — não prefixar SOUL.md na mensagem ([STRATEGY §2.4](../STRATEGY.md#24-personalidade-e-contexto)).

## 7. Considerações técnicas

- **Dependências:** PRD-003 merged ([PR #6](https://github.com/adriannoes/cursor-agent/pull/6)); REPL, pool, facade, exit codes, and `sessions list` are on `main`. PRD-002 (`SessionStore` with `metadata`) remains the persistence layer.
- **ADRs aplicáveis:**
  - [ADR-011](../decisions/ADR-011-compress-flow.md) — saga `/compress` e prompt versionado.
  - [ADR-013](../decisions/ADR-013-slash-commands-skills.md) — `/reset` alias, ordem de resolução, denylist de nomes reservados.
  - [ADR-018](../decisions/ADR-018-observability-logs.md) — NDJSON schema v1 for command events (not yet emitted).
- **New runtime dependency:** `rich` — must be added explicitly via `uv add rich` (PRD-003 added only `typer>=0.12`; Typer pulls Rich transitively for `--help` but the project does not declare it yet).
- **Tests:** `FakeSdkFacade` + pytest; saga `/compress` testable without API key. Reuse `tests/unit/cli_repl_helpers.py` and `tests/unit/conftest.py` (`config` fixture) from PRD-003.
- **Logs:** emit command-level NDJSON events (ADR-018) in addition to existing `facade.send` start/end.

### PRD-003 module map (build on — do not recreate)

| Module | Responsibility | PRD-004 touch |
|--------|----------------|---------------|
| `cli/app.py` | Typer entry, `cli_entry` exit codes, `sessions list`, `run_default` | Unchanged unless `/help` needs app-level wiring |
| `cli/startup.py` | `repl_runtime`, `create_store`, `session_key_for` | Reuse; `/compress` may open store via same helpers |
| `cli/repl_session.py` | `run_repl` loop, auto-resume, free-text turns | **Replace inline `/` branch (lines 81–108) with `CommandRouter`** |
| `cli/slash_commands.py` | `handle_new`, `handle_resume` | Register as built-ins; add new handlers here or in `cli/commands/` |
| `cli/stream_renderer.py` | `build_stream_callbacks` (text deltas only) | Extend or supersede with `cli/rich_display.py` for tool badges |
| `cli/exit_codes.py` | `exit_code_for_status`, `exit_code_for_error` | Reuse; `/stop` → `CANCELLED` → 0 |
| `cli/error_display.py` | `format_error` | Reuse in all new handlers (avoids import cycle) |

### `run_repl` contract (integration point for T1.4)

```python
async def run_repl(
    pool, session_key, store, *,
    config: CursorAgentConfig,
    facade: SdkFacade,
    reader: AsyncIterator[str],
    writer: Callable[[str], None],
    stream_writer: Callable[[str], None] | None = None,
    auto_resume: bool = True,
) -> RunStatus | None
```

- **Return value:** last turn `RunStatus` (or `None`); consumed by `cli_entry` → `exit_code_for_status`.
- **Loop error policy (PRD-003 §9, confirmed in review):** catch `CursorAgentError` inside the loop, print via `format_error`, continue. `RunStatus.ERROR` prints a notice and continues; exit 2 applies only at process shutdown.
- **Two output sinks (critical for Rich T3):**
  - `writer` — line-oriented messages (`typer.echo` in production): status, errors, help, session confirmations.
  - `stream_writer` — inline assistant deltas (`typer.echo(..., nl=False)` via `_echo_delta` in production). After each successful turn, `stream_sink("\n")` terminates the streamed line.
  - Unit tests proved deltas must not land on the line writer (`test_cli_streaming.py`). Rich `Live` must respect the same split.
- **Auto-resume (post-review):** goes through `pool.get(session_key)` first (lazy resume + ADR-003 runtime guard). `store.resolve` is only a fallback probe to choose between the `/new` hint and the error message — do not use `store.resolve` as the primary resume path.

### `ReplState` (introduce with CommandRouter — T1.1)

PRD-003 keeps session state as local variables inside `run_repl`. PRD-004 needs a small mutable state object passed to the router and handlers:

```python
@dataclass
class ReplState:
    active_session_id: str | None = None
    last_user_message: str | None = None      # /retry
    last_status: RunStatus | None = None      # exit code + /usage context
    # Optional: active_agent_id: str | None   # /stop — or resolve via store on demand
```

`run_repl` owns `ReplState`; the router reads/writes it. Do not introduce hidden globals.

### CommandRouter design (T1)

**New module:** `src/cursor_agent/cli/command_router.py`

```text
parse "/foo bar" → (name="foo", arg="bar")
resolve:
  1. built-in registry (denylist from ADR-013)
  2. skills stub (empty list until PRD-009; return None → fall through)
  3. unknown slash → friendly message (replace "_SLASH_PLACEHOLDER")
free text → pool.send (stays in run_repl, not the router)
```

- **Handler signature:** keyword-only, same style as `handle_new` / `handle_resume`:
  `async def handle_*(ctx: CommandContext, arg: str | None, writer: Callable[[str], None]) -> CommandResult`
  where `CommandContext` bundles `pool`, `store`, `config`, `facade`, `session_key`, and `ReplState`.
- **Existing handlers:** register `new`, `resume`, `quit` from PRD-003; `/reset` aliases `new` (ADR-013).
- **`/quit`:** router returns a sentinel (e.g. `QuitRequested`) so `run_repl` breaks the loop — do not call `sys.exit` inside handlers.

### Per-command implementation notes

| Command | Implementation hint |
|---------|---------------------|
| `/stop` | Resolve `agent_id` from `store.resolve(session_key, session_id=state.active_session_id)`; call `facade.cancel(agent_id)`. Must work while `pool.send` is blocking — may need async cancellation wiring; CLI uses `blocking=True` so consider cancel from another task or document MVP as "stop takes effect after current turn". |
| `/model [id]` | **Decision (see §9):** update in-memory model override on `ReplState` + call `facade.resume_agent(agent_id, ..., model=new_model)` before next send. Persisting model in store metadata is optional for MVP. |
| `/retry` | Resend `state.last_user_message` via `pool.send(..., session_id=state.active_session_id)`; error if `last_user_message is None`. |
| `/usage` | Read `RunResult.usage` from last turn (`state.last_status` path) or `SessionRecord.metadata["last_run_id"]` / `last_status`; display shape TBD until integration test with API key. |
| `/compress` | Saga in dedicated module `cli/compress.py` (T4); updates same `session.id`, new `agent_id`, `metadata.status = "compressing"`. |
| `/help` | Static registry introspection — list commands by P0/P1/P2 priority, document `/reset` = `/new`. |

### Streaming and Rich (T3)

- Replace or wrap `build_stream_callbacks` so `on_tool_start` / `on_tool_end` drive Rich badges (currently ignored).
- Keep `writer` / `stream_writer` injectable — Rich `Console` behind a thin interface so unit tests mock `Console` instead of importing Rich in `repl_session.py`.
- Do not call `typer.echo` from handlers; always use the injected `writer`.

### Known deferred risks (tracked)

- **Orphan SDK agent on `/new` failure** — if `store.create` fails after `create_agent`, the agent leaks. Tracked: [issue #7](https://github.com/adriannoes/cursor-agent/issues/7). `/compress` saga must implement rollback explicitly.
- **SIGINT during blocking send** — no explicit `facade.cancel` on Ctrl+C today; `async with repl_runtime` disposes on teardown. Explicit signal handling deferred to gateway scope (ADR-021 / PRD-006). `/stop` is the user-facing cancel for MVP.

### Test layout carryover (PRD-003)

| File | Role |
|------|------|
| `tests/unit/conftest.py` | Shared `config` fixture |
| `tests/unit/cli_repl_helpers.py` | `drive_repl`, spy pools, `seed_session`, `line_reader` |
| `tests/unit/test_cli_bootstrap.py` | Startup / auto-resume skeleton |
| `tests/unit/test_cli_repl.py` | Slash commands + error loop |
| `tests/unit/test_cli_streaming.py` | Separate `stream_writer` vs `writer` sinks |
| `tests/unit/test_cli_exit_codes.py` | Pure mappers + end-to-end `CliRunner` default invoke |

PRD-004 adds: `test_commands_router.py`, `test_commands_handlers.py`, `test_commands_compress.py`, `test_display_rich.py`. Keep each file under 500 lines; extract helpers to `tests/unit/commands_helpers.py` if needed.

## 8. Métricas de sucesso

- 8+ comandos implementados e listados em `/help`.
- `/compress` em sessão longa reduz tokens perceptíveis sem perder `session id` no SQLite.
- Demo manual: `/help`, `/compress`, `/stop` funcionam em sessão com tools.
- `pytest` dos testes de commands passa sem `CURSOR_API_KEY`.
- Rules do projeto (`.cursor/rules`) alteram comportamento do agente em turn livre.

## 9. Questões em aberto

### Resolved during PRD-003 (do not re-litigate)

| Topic | Decision |
|-------|----------|
| Resolution order | [ADR-013](../decisions/ADR-013-slash-commands-skills.md): built-in → skills → free message. PRD-003 only handled `/quit`, `/new`, `/resume` inline; T1.2 is greenfield at the existing dispatch point. |
| `/reset` | Alias of `/new` — same handler, documented in `/help`. |
| Auto-resume path | `pool.get` primary; `store.resolve` only for hint vs error on failure. |
| Exit codes | `FINISHED`/`CANCELLED`/`None` → 0; `CursorAgentError` at startup → 1; `RunStatus.ERROR` at shutdown → 2. |
| Error formatting | `format_error` in `cli/error_display.py` — reuse everywhere. |
| `/new` semantics | CLI orchestration only: `facade.create_agent` + `store.create` — **no** `pool.new`. |
| `active_session_id` | Must be passed to every `pool.send(..., session_id=active_session_id)`. |

### Still open — resolve before or during PRD-004

| Topic | Options / notes |
|-------|-----------------|
| `/usage` scope | Session cumulative vs last turn only. `RunResult.usage` is `dict \| None`; `FakeSdkFacade` returns `None`. Decide displayed fields after one integration run with API key. |
| Tool badge detail | Tool name only vs truncated arguments. Prefer name-only for MVP (less PII in terminal). |
| `/stop` during blocking send | `pool.send(..., blocking=True)` may not return until the turn ends. MVP: `/stop` calls `facade.cancel` and documents that cancellation takes effect when the SDK cooperates; hard interrupt (SIGINT → cancel) deferred to PRD-006. |
| `/model` persistence | In-memory override on `ReplState` for MVP; optional `store.update_metadata(model=...)` if resume across restart must honor model. **Recommended:** `resume_agent(..., model=...)` before next send. |
| `/retry` empty state | Show `"No previous message to retry."` — do not send to agent. |
| Command NDJSON events | Which fields: `command`, `session_id`, `duration_ms`, `outcome`? Align with ADR-018 v1 schema in T1 or T2. |
| `/personality` | Backlog Fase 5; personality via `.cursor/rules` only ([STRATEGY §9.2](../STRATEGY.md#92-contexto-e-personalidade)). |

## 10. Tarefas de implementação

### Definition of Done

- [x] 8+ comandos P0–P2 implementados e listados em `/help`
- [x] Saga `/compress` com status `compressing` e rollback em falha ([ADR-011](../decisions/ADR-011-compress-flow.md))
- [x] Display Rich com streaming e badges de tool
- [x] Testes do router sem `CURSOR_API_KEY`

### Tabela de tarefas

> Estimates revised after PRD-003: router integration is surgical (replace ~30 lines in `repl_session.py`) but `ReplState`, Rich two-sink wiring, and `/compress` rollback add scope. T3 and T4 can run in parallel after T1 lands.

| ID | Tarefa | Est. | Dep |
|----|--------|------|-----|
| T0 | `uv add rich` + stub `cli/rich_display.py` interface | 1h | PRD-003 |
| T1 | CommandRouter + `ReplState` + `CommandContext` | 5h | PRD-003 |
| T2 | Comandos P0/P1/P2 (handlers + `/help`) | 8h | T1 |
| T3 | Display Rich (stream + badges, two-sink) | 6h | T0, PRD-003 |
| T4 | Saga `/compress` + rollback | 5h | T2 |
| T5 | Testes de commands + NDJSON events | 5h | T2, T4 |

### T0 — Dependency + display interface

- [x] T0.1 `uv add rich` in `pyproject.toml`
- [x] T0.2 Define `RichStreamRenderer` protocol or class with injectable `Console` (test seam)

### T1 — CommandRouter

- [x] T1.1 `ReplState` + `CommandContext` dataclasses
- [x] T1.2 `CommandRouter` registry + parse `name`/`arg` from slash line
- [x] T1.3 Ordem de resolução: built-in → skills (stub) → unknown slash message
- [x] T1.4 Denylist de nomes reservados ([ADR-013](../decisions/ADR-013-slash-commands-skills.md))
- [x] T1.5 Integração: replace inline `/` branch in `repl_session.py`; migrate `/new`, `/resume`, `/quit`

### T2 — Comandos

- [x] T2.1 P0: `/new`, `/reset` (alias), `/resume`, `/help`, `/quit` — register existing `handle_new`/`handle_resume`
- [x] T2.2 P1: `/stop` (`facade.cancel`), `/model` (`resume_agent` + `ReplState` override)
- [x] T2.3 P2: `/retry` (`ReplState.last_user_message`), `/usage`, `/compress` (handler delegates to T4)
- [x] T2.4 `/help` lists P0/P1/P2 and documents `/reset` → `/new`
- [x] T2.5 Persist `last_user_message` on each free-text turn in `run_repl`

### T3 — Display Rich

- [x] T3.1 Wire `on_assistant_text` to Rich Live (respect `stream_writer` vs `writer` split)
- [x] T3.2 Badges via `on_tool_start`/`on_tool_end` (name + running/done state)
- [x] T3.3 Command status messages via `writer` (not Rich) — errors reuse `format_error`

### T4 — Saga `/compress`

- [x] T4.1 Load [prompts/compress.txt](../prompts/compress.txt) from package or repo path
- [x] T4.2 `metadata.status = "compressing"` via `store.update_metadata`
- [x] T4.3 New `agent_id` on same `session.id`; first post-compress message = summary
- [x] T4.4 Rollback on failure: restore previous `agent_id`, clear status ([ADR-011](../decisions/ADR-011-compress-flow.md)); compensate orphan agent per [issue #7](https://github.com/adriannoes/cursor-agent/issues/7)

### T5 — Testes

- [x] T5.1 Router: built-in → skills stub → unknown slash; alias `/reset`
- [x] T5.2 Handlers P0/P1/P2 with `drive_repl` + spy pool/facade
- [x] T5.3 Saga `/compress` happy path + mid-flight failure with `FakeSdkFacade`
- [x] T5.4 `test_display_rich.py` — mock `Console`, assert badge lifecycle
- [x] T5.5 Gate: `pytest -m "not integration"` includes all new CLI test files

### Demo

1. `cursor-agent` → `/help` — lista comandos P0–P2.
2. Sessão longa → `/compress` — confirma mesmo `session id` com novo `agent_id`.
3. Run longo → `/stop` — cancela sem fechar o REPL.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR router | `tests/unit/test_commands_router.py` — built-in → skills stub → unknown slash; `/reset` alias | `pytest tests/unit/test_commands_router.py -v` |
| FR compress | `tests/unit/test_commands_compress.py` — saga happy path + rollback | `pytest tests/unit/test_commands_compress.py -v` |
| FR display | `tests/unit/test_display_rich.py` — mock `Console`, stream + badge callbacks | `pytest tests/unit/test_display_rich.py -v` |
| FR comandos | `tests/unit/test_commands_handlers.py` — P0/P1/P2 via `drive_repl` | `pytest tests/unit/test_commands_handlers.py -v` |

**Suggested implementation order:** T0 (`rich`) → T1 (router + `ReplState` + migrate existing slash) → T2 P0 handlers → T3 Rich wiring → T2 P1/P2 → T4 compress → T5 full gate.

**Test patterns from PRD-003 (reuse, do not reinvent):**

- `drive_repl(...)` in `cli_repl_helpers.py` — feeds scripted lines, captures `writer` output.
- Spy `SessionAgentPool` / `FakeSdkFacade` — assert `send`, `cancel`, `create_agent` call shapes.
- `CliRunner` + `monkeypatch` for end-to-end `cli_entry` exit codes (`test_cli_exit_codes.py`).
- Separate file for streaming sink assertions (`test_cli_streaming.py` pattern).
- `tmp_path` store + two-pool restart pattern for persistence (`test_cli_resume.py`).

### Retroalimentação

**Após concluir PRD-004:** revisar e atualizar [PRD-005](PRD-005-messaging-profile.md) (§7, §9, §11) antes do gate messaging.

### Learnings from PRD-003 (CLI REPL) — post-merge, post-review

> Recorded after [PR #6](https://github.com/adriannoes/cursor-agent/pull/6) merged to `main`. English per repo docs convention.

**Architecture & integration**

- [x] `CommandRouter` (T1) replaces the inline `/` branch in `repl_session.py` (~lines 81–108), not the whole loop. Free-text turns and `pool.send` stay in `run_repl`.
- [x] Resolution order (built-in → skills → free message) was **not** implemented in PRD-003; only `/quit`, `/new`, `/resume` + placeholder. T1.2–T1.3 are greenfield at the dispatch point.
- [x] Existing handlers in `slash_commands.py` are the template for new commands: keyword-only args, `writer` callback, `format_error` on failure.
- [x] `error_display.py` exists specifically to break an import cycle between `repl_session` and `slash_commands` — new handler modules should import `format_error` from there, not duplicate.
- [x] Introduce `ReplState` with the router (T1.1) — `active_session_id`, `last_user_message`, `last_status` are currently locals in `run_repl`.
- [x] `/new` = `facade.create_agent` + `store.create` only; never `pool.new`.

**Streaming & display**

- [x] `StreamCallbacks.on_tool_start` / `on_tool_end` exist in the facade but `build_stream_callbacks` ignores them — tool badges (T3.2) are net-new wiring.
- [x] Production uses **two sinks**: `writer` (lines) vs `stream_writer` (inline deltas). Rich must honor this; tests already guard against regressions.
- [x] `rich` is not a declared dependency — T0 must add it before T3.

**Exit codes & errors**

- [x] Exit mapping lives in `cli/exit_codes.py`; `/stop` should set `RunStatus.CANCELLED` → exit 0 at shutdown.
- [x] In-loop `CursorAgentError` → print and continue; startup errors → exit 1 via `cli_entry`.
- [x] `RunStatus.ERROR` → notice in loop, exit 2 only when REPL ends.

**Testing & process**

- [x] PRD-003 ended with 149 unit tests and ~90.6% coverage. Split large test files early (`test_cli_bootstrap`, `test_cli_streaming` extracted from `test_cli_repl`).
- [x] Onda 3 tasks (REPL loop + app wiring) had to be **serialized** — `run_repl` signature and `app.py` are tightly coupled; plan PRD-004 waves so T1 lands before parallel T2/T3.
- [x] No CI workflow in repo yet — local ADR-026 gate is the merge bar.
- [x] E2E exit-code tests for default `cursor-agent` invoke (`test_default_invoke_exits_1_on_broken_config`, `test_default_invoke_exits_2_on_run_error`) caught gaps pure unit tests missed.

**Security & follow-ups**

- [x] Command-level NDJSON events do not exist yet; only `facade.send` start/end (ADR-018). PRD-004 should add command events.
- [x] Destructive tools still reachable — `tool_profile` resolves to empty MCP map (stub). Reinforces PRD-005 motivation.
- [x] Orphan SDK agent if `store.create` fails after `create_agent` — [issue #7](https://github.com/adriannoes/cursor-agent/issues/7). `/compress` rollback must not make this worse.

**Aprendizados a registrar (fill during PRD-004 implementation):**

- [x] Ordem de resolução confirmada em produção vs. [ADR-013](../decisions/ADR-013-slash-commands-skills.md)
- [ ] Duração típica da saga `/compress` e estados `metadata.status`
- [ ] Shape real de `RunResult.usage` após run com API key
- [ ] Comportamento de `/stop` com `blocking=True` no SDK real
- [x] Comandos que o perfil messaging deve expor ou omitir (input para PRD-005)
- [x] Eventos NDJSON úteis para auditoria de comandos
