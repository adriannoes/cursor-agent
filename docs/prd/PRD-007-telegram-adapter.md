---
id: PRD-007
title: Adapter Telegram
status: draft
phase: 3
depends_on: [PRD-006]
adrs:
  - ADR-006
  - ADR-008
  - ADR-012
  - ADR-022
related:
  - path: ../decisions/ADR-006-telegram-library.md
  - path: ../decisions/ADR-004-session-key-workspace.md
---

# PRD-007 — Adapter Telegram

## 1. Introdução / Visão geral

Este PRD implementa o **adapter Telegram** como primeira implementação de `PlatformAdapter`, entregando o agente cursor-agent no chat com allowlist, sessões isoladas por chat e entrega de respostas longas dentro dos limites da Bot API.

**Objetivo:** polling aiogram 3.x ([ADR-006](../decisions/ADR-006-telegram-library.md)), `session_key = telegram:{chat_id}:{workspace_hash}`, chunking ≤4096 com typing indicator ([ADR-012](../decisions/ADR-012-telegram-chunking.md)), slash commands mínimos no adapter (`/new`, `/stop`, `/help`) e testes E2E de allowlist.

## 2. Objetivos

- Integrar aiogram 3.x ao gateway runner (PRD-006).
- Mapear cada chat Telegram a um `session_key` estável ([ADR-004](../decisions/ADR-004-session-key-workspace.md)).
- Entregar respostas do agente respeitando limite de 4096 caracteres por mensagem.
- Exibir typing durante runs ativos.
- Suportar comandos essenciais no canal Telegram sem depender do CLI.
- Validar allowlist end-to-end: usuário não listado não recebe respostas do agente.

## 3. User Stories

- **Como** usuário autorizado no Telegram, **quero** enviar uma pergunta sobre o repositório **para** obter resposta do agente no chat.
- **Como** usuário, **quero** ver “digitando…” durante processamento **para** saber que o bot está ativo.
- **Como** usuário, **quero** `/new` no Telegram **para** iniciar conversa limpa sem perder outras sessões CLI.
- **Como** usuário, **quero** `/stop` **para** cancelar uma resposta longa em andamento.
- **Como** operador, **quero** que estranhos na allowlist sejam ignorados **para** manter o bot privado.

## 4. Requisitos funcionais

1. O adapter deve implementar `PlatformAdapter` em `platforms/telegram.py` usando **aiogram 3.x** ([ADR-006](../decisions/ADR-006-telegram-library.md)).
2. O adapter deve usar **long polling** no MVP (sem webhook).
3. Para cada mensagem inbound válida, o `session_key` deve ser `telegram:{chat_id}:{workspace_hash}` ([ADR-004](../decisions/ADR-004-session-key-workspace.md)).
4. Antes de processar, o adapter deve consultar `gateway/auth.py` (allowlist); usuários não autorizados não disparam o agente.
5. Texto livre (não comando) deve ser encaminhado ao `SessionAgentPool.send`.
6. Durante run ativo, o adapter deve enviar `send_chat_action(typing)` com refresh ~5s ([ADR-012](../decisions/ADR-012-telegram-chunking.md)).
7. O adapter deve bufferizar texto do assistant durante o stream e, ao final (ou buffer > 3800 chars), dividir em chunks ≤ 4096, preferindo quebras em `\n\n` ou `\n`.
8. Mensagens outbound devem usar `parse_mode=HTML` com escape do conteúdo do modelo.
9. O adapter **não** deve usar `edit_message_text` para simular streaming (rate limits; limite 4096).
10. Comandos no adapter: `/new` (nova sessão/agent), `/stop` (cancel run), `/help` (lista comandos do canal).
11. `/new` no Telegram deve isolar sessão daquele chat sem afetar outras chaves.
12. Em `AgentBusyError`, reutilizar mensagem do gateway core ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).
13. Testes com bot mock devem cobrir chunking, escape HTML e allowlist.

## 5. Não-objetivos

- Comandos completos do CLI (`/compress`, `/resume`, `/model`, …) no Telegram MVP.
- Streaming token-a-token visível no chat.
- Webhook + TLS / reverse proxy.
- Inline keyboards, grupos, tópicos ou multi-bot.
- Discord/Slack ([BACKLOG-PHASE5](../BACKLOG-PHASE5.md)).
- MarkdownV2 ou entidades complexas (HTML escapado apenas).

## 6. Considerações de design

- **UX Telegram:** resposta aparece ao final do run (buffer), não token a token — compensar com typing indicator.
- **Comandos:** subset mínimo; `/help` lista só o que funciona no canal.
- **HTML:** escapar `<`, `>`, `&` do modelo; evitar que o Telegram rejeite a mensagem.
- **Chunks:** mensagens sequenciais na ordem; numerar opcionalmente se múltiplos chunks (“1/3”) — decisão de polish.
- **Privacidade:** não logar conteúdo completo de mensagens em produção (só metadados).

## 7. Considerações técnicas

- **Dependências:** PRD-006 (runner, auth, pool, shutdown).
- **ADRs aplicáveis:**
  - [ADR-006](../decisions/ADR-006-telegram-library.md) — aiogram 3.x, abstração `PlatformAdapter`.
  - [ADR-012](../decisions/ADR-012-telegram-chunking.md) — buffer, split, typing, HTML escape.
  - [ADR-004](../decisions/ADR-004-session-key-workspace.md) — formato `session_key`.
  - [ADR-008](../decisions/ADR-008-agent-busy-gateway.md) — mensagem em busy (via core).
- **Config:** `platforms.telegram.enabled`, `bot_token`, `allowed_users` em `gateway.yaml` ([STRATEGY §11](../STRATEGY.md#11-fase-3-gateway-telegram)).
- **Pacote:** pin `aiogram` 3.x em `pyproject.toml`.
- **Testes:** mock aiogram Bot/Dispatcher; testes unitários de chunking/escape; integração opcional com token de teste.

## 8. Métricas de sucesso

- Mensagem de usuário allowlisted → resposta entregue no Telegram.
- Usuário não allowlisted → ignorado (sem sessão criada).
- Resposta > 4096 chars → múltiplas mensagens sem erro da API.
- `/new` reinicia contexto do chat; `/stop` cancela run em andamento.
- Typing visível em runs > 5s.
- Testes do adapter passam em CI sem token real (mocks).

## 9. Questões em aberto

- Prefixar chunks longos com “(continuação)” ou numeração?
- `/help` deve mencionar limitações vs CLI?
- Tratar mensagens de grupo (mention obrigatória) no MVP ou só DM?

## 10. Tarefas de implementação

### Definition of Done

- [ ] Mensagem allowlisted → resposta entregue no Telegram
- [ ] Usuário não allowlisted → ignorado
- [ ] Resposta > 4096 chars → múltiplas mensagens sem erro
- [ ] `/new`, `/stop`, `/help` funcionam no canal
- [ ] Testes do adapter passam em CI com mocks

### Tabela de tarefas

| ID | Tarefa | Est. | Dep |
|----|--------|------|-----|
| T1 | `platforms/telegram.py` (aiogram polling) | 8h | PRD-006 |
| T2 | Chunking + HTML escape | 4h | T1 |
| T3 | Slash commands no adapter | 4h | T1 |
| T4 | Testes adapter (mock bot) | 4h | T1 |

### T1 — Adapter base

- [ ] T1.1 Bot + Dispatcher aiogram 3.x
- [ ] T1.2 Handler de mensagens de texto
- [ ] T1.3 `session_key = telegram:{chat_id}:{workspace_hash}`
- [ ] T1.4 Integração auth allowlist + pool.send
- [ ] T1.5 `start()` / `stop()` para lifecycle do runner

### T2 — Entrega de respostas

- [ ] T2.1 Buffer de stream do assistant
- [ ] T2.2 Split ≤4096 com quebras preferenciais ([ADR-012](../decisions/ADR-012-telegram-chunking.md))
- [ ] T2.3 `parse_mode=HTML` + escape
- [ ] T2.4 `send_chat_action(typing)` com refresh ~5s

### T3 — Comandos Telegram

- [ ] T3.1 `/new` → novo agent para o `session_key`
- [ ] T3.2 `/stop` → `run.cancel()`
- [ ] T3.3 `/help` → texto de ajuda do canal

### T4 — Testes

- [ ] T4.1 Mock bot: inbound allowlisted → outbound
- [ ] T4.2 Mock bot: inbound bloqueado
- [ ] T4.3 Unit: chunking e HTML escape
- [ ] T4.4 Unit: comandos `/new`, `/stop`

### Demo

1. Enviar mensagem no Telegram (usuário allowlisted) → resposta entregue.
2. Usuário não na allowlist → sem resposta do agente.
3. Resposta longa (> 4096 chars) → múltiplas mensagens sequenciais.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR chunking | `tests/unit/test_telegram_chunking.py` — split ≤4096, HTML escape | `pytest tests/unit/test_telegram_chunking.py -v` |
| FR adapter | `tests/unit/test_telegram_adapter.py` — inbound allowlisted → outbound (mock bot) | `pytest tests/unit/test_telegram_adapter.py -v` |
| FR auth | `tests/unit/test_telegram_adapter.py` — inbound bloqueado ignorado | `pytest tests/unit/test_telegram_adapter.py -k blocked -v` |
| FR commands | `tests/unit/test_telegram_commands.py` — `/new`, `/stop`, `/help` | `pytest tests/unit/test_telegram_commands.py -v` |

Ordem sugerida: chunking/escape (puro) → adapter mock → comandos → integração manual com token.

### Retroalimentação

**Após concluir PRD-007:** revisar e atualizar [PRD-008](PRD-008-memory-v1.md) (§7, §9, §11) antes de memória v1.

**Aprendizados a registrar:**

- [ ] Latência polling + typing indicator refresh
- [ ] Edge cases de chunking (markdown/HTML, mensagens vazias)
- [ ] `session_key` Telegram confirmado em produção
- [ ] Comandos Telegram vs. CLI — divergências aceitáveis
- [ ] Delivery opcional para cron (PRD-010)
