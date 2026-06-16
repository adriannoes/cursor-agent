---
id: PRD-004
title: Slash commands e display Rich
status: draft
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

- **Dependências:** PRD-003 (REPL, pool, facade) e PRD-002 (SessionStore com `metadata.status`).
- **ADRs aplicáveis:**
  - [ADR-011](../decisions/ADR-011-compress-flow.md) — saga `/compress` e prompt versionado.
  - [ADR-013](../decisions/ADR-013-slash-commands-skills.md) — `/reset` alias, ordem de resolução, denylist de nomes reservados.
- **Pacotes:** `rich` para display; sem novas dependências de comando além do stack Fase 1.
- **Testes:** `FakeSdkFacade` + pytest; saga `/compress` testável sem API key.
- **Logs:** reutilizar schema JSON v1 ([ADR-018](../decisions/ADR-018-observability-logs.md)) em eventos de comando.

## 8. Métricas de sucesso

- 8+ comandos implementados e listados em `/help`.
- `/compress` em sessão longa reduz tokens perceptíveis sem perder `session id` no SQLite.
- Demo manual: `/help`, `/compress`, `/stop` funcionam em sessão com tools.
- `pytest` dos testes de commands passa sem `CURSOR_API_KEY`.
- Rules do projeto (`.cursor/rules`) alteram comportamento do agente em turn livre.

## 9. Questões em aberto

- `/personality` — backlog Fase 5; personalidade via `.cursor/rules` apenas ([STRATEGY §9.2](../STRATEGY.md#92-contexto-e-personalidade)).
- `/usage` deve exibir custo acumulado da sessão ou só do último turn?
- Badge de tool: mostrar argumentos resumidos ou só o nome da tool?

## 10. Tarefas de implementação

### Definition of Done

- [ ] 8+ comandos P0–P2 implementados e listados em `/help`
- [ ] Saga `/compress` com status `compressing` e rollback em falha ([ADR-011](../decisions/ADR-011-compress-flow.md))
- [ ] Display Rich com streaming e badges de tool
- [ ] Testes do router sem `CURSOR_API_KEY`

### Tabela de tarefas

| ID | Tarefa | Est. | Dep |
|----|--------|------|-----|
| T1 | CommandRouter + registry | 4h | PRD-003 |
| T2 | Comandos P0/P1/P2 | 8h | T1 |
| T3 | Display Rich (stream + badges) | 6h | PRD-003 |
| T4 | Saga `/compress` | 4h | T2 |
| T5 | Testes de commands | 4h | T2 |

### T1 — CommandRouter

- [ ] T1.1 Protocol/handler por comando com assinatura consistente
- [ ] T1.2 Ordem de resolução: built-in → skills → mensagem livre
- [ ] T1.3 Denylist de nomes reservados ([ADR-013](../decisions/ADR-013-slash-commands-skills.md))
- [ ] T1.4 Integração com REPL async (PRD-003)

### T2 — Comandos

- [ ] T2.1 P0: `/new`, `/reset`, `/resume`, `/help`, `/quit`
- [ ] T2.2 P1: `/stop`, `/model`
- [ ] T2.3 P2: `/retry`, `/usage`, `/compress` (handler delega saga a T4)
- [ ] T2.4 `/help` documenta alias `/reset` → `/new`

### T3 — Display Rich

- [ ] T3.1 Callbacks de stream mapeados para Live/Panel Rich
- [ ] T3.2 Badges de tool (nome + estado)
- [ ] T3.3 Mensagens de erro/status de comando formatadas

### T4 — Saga `/compress`

- [ ] T4.1 Carregar [prompts/compress.txt](../prompts/compress.txt)
- [ ] T4.2 `metadata.status = "compressing"` no SessionStore
- [ ] T4.3 Novo `agent_id` + mesmo `session id` + primeira mensagem = resumo
- [ ] T4.4 Rollback em falha ([ADR-011](../decisions/ADR-011-compress-flow.md))

### T5 — Testes

- [ ] T5.1 Registry e resolução de alias `/reset`
- [ ] T5.2 Saga `/compress` happy path com fake
- [ ] T5.3 Saga `/compress` falha mid-flight

### Demo

1. `cursor-agent` → `/help` — lista comandos P0–P2.
2. Sessão longa → `/compress` — confirma mesmo `session id` com novo `agent_id`.
3. Run longo → `/stop` — cancela sem fechar o REPL.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR router | `tests/unit/test_commands_router.py` — built-in → skills → livre, alias `/reset` | `pytest tests/unit/test_commands_router.py -v` |
| FR compress | `tests/unit/test_commands_compress.py` — saga happy path + rollback | `pytest tests/unit/test_commands_compress.py -v` |
| FR display | `tests/unit/test_display_rich.py` — callbacks stream/badges (snapshot ou mock Console) | `pytest tests/unit/test_display_rich.py -v` |
| FR comandos | `tests/unit/test_commands_handlers.py` — P0/P1/P2 com fake pool | `pytest tests/unit/test_commands_handlers.py -v` |

Ordem sugerida: router/registry → handlers P0 → saga compress → Rich display.

### Retroalimentação

**Após concluir PRD-004:** revisar e atualizar [PRD-005](PRD-005-messaging-profile.md) (§7, §9, §11) antes do gate messaging.

**Aprendizados a registrar:**

- [ ] Ordem de resolução confirmada vs. [ADR-013](../decisions/ADR-013-slash-commands-skills.md)
- [ ] Duração típica da saga `/compress` e estados `metadata.status`
- [ ] Comandos que o perfil messaging deve expor ou omitir
- [ ] Eventos NDJSON úteis para auditoria de comandos
- [ ] Riscos de tools destrutivas ainda acessíveis sem hooks (motiva PRD-005)
