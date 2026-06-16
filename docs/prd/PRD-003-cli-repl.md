---
id: PRD-003
title: CLI REPL
status: draft
phase: 1
depends_on: [PRD-002]
adrs:
  - ADR-019
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

**FR-4.** Entrada de texto livre (não começando com `/`) deve ser enviada via `pool.send(session_key, message)` na sessão ativa.

**FR-5.** `/quit` deve encerrar o REPL com exit code 0 e chamar `facade.close()` no shutdown.

**FR-6.** `/new` deve criar novo `agent_id` via facade, novo row no SQLite, e tornar essa sessão a ativa.

**FR-7.** `/resume` sem argumento deve resolver última sessão do `session_key` atual; `/resume <session-id>` deve resolver pelo UUID.

**FR-8.** Resume com runtime mismatch deve exibir erro claro e sugerir `/new` ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md) — validado no pool/store).

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

- REPL deve ser legível: prompt claro, indicação de sessão ativa (id curto ou título).
- Streaming: repassar tokens do assistente via `StreamCallbacks` para stdout (Rich opcional para formatação).
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

Nenhuma — packaging e escopo de API estão em [ADR-019](../decisions/ADR-019-packaging-license.md).

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
| FR REPL | `tests/unit/test_cli_repl.py` — `/new`, `/quit`, streaming com fake | `pytest tests/unit/test_cli_repl.py -v` |
| FR sessions | `tests/unit/test_cli_sessions.py` — `sessions list` | `pytest tests/unit/test_cli_sessions.py -v` |
| FR exit codes | `tests/unit/test_cli_exit_codes.py` — 0/1/2 conforme contrato | `pytest tests/unit/test_cli_exit_codes.py -v` |
| FR resume | `tests/unit/test_cli_resume.py` — restart simulado, mesmo `agent_id` | `pytest tests/unit/test_cli_resume.py -v` |

Ordem sugerida: entry point → wire fake pool → comandos → exit codes → resume pós-restart.

### Retroalimentação

**Após concluir PRD-003:** revisar e atualizar [PRD-004](PRD-004-slash-commands.md) (§7, §9, §11) antes de slash commands.

**Aprendizados a registrar:**

- [ ] UX do REPL async (latência percebida, cold start)
- [ ] Pontos de integração para CommandRouter e Rich
- [ ] Exit codes observados vs. contrato facade
- [ ] Packaging PyPI / entry points ([ADR-019](../decisions/ADR-019-packaging-license.md))
- [ ] Implicações para memória v1 (PRD-008) no primeiro turn
