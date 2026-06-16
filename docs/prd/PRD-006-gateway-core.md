---
id: PRD-006
title: Gateway core
status: draft
phase: 3
depends_on: [PRD-005]
adrs:
  - ADR-008
  - ADR-014
  - ADR-018
  - ADR-021
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "11"
  - path: ../gateway-security.md
---

# PRD-006 — Gateway core

## 1. Introdução / Visão geral

O gateway é o processo **long-running** que conecta plataformas de mensagem (Telegram na Fase 3) ao `SessionAgentPool` e `AsyncSdkFacade`. Este PRD cobre o núcleo: runner, configuração, autenticação por allowlist, interface `PlatformAdapter` e políticas de concorrência/shutdown — **sem** implementar o adapter Telegram (PRD-007).

**Objetivo:** subir `gateway/runner.py` com `gateway.yaml`, forçar `tool_profile: messaging`, recusar config insegura, tratar `AgentBusyError` com mensagem amigável ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)) e encerrar graciosamente em SIGINT/SIGTERM ([ADR-021](../decisions/ADR-021-graceful-shutdown.md)).

## 2. Objetivos

- Processo async único compartilhando facade e pool com o CLI.
- Configuração em `~/.cursor-agent/gateway.yaml` (plataformas, allowlist, workspace).
- Allowlist obrigatória — mensagens de usuários não autorizados ignoradas silenciosamente ou com log.
- Enforcement: gateway **recusa subir** se `tool_profile != messaging` ([ADR-014](../decisions/ADR-014-tool-profiles-mvp.md)).
- Deploy automático de hooks messaging (PRD-005) na subida.
- Interface `PlatformAdapter` para desacoplar Telegram de futuros canais.
- Shutdown ordenado sem orphan processes do SDK.

## 3. User Stories

- **Como** operador, **quero** iniciar o gateway com um comando e config YAML **para** manter o bot sempre disponível.
- **Como** operador, **quero** que apenas usuários na allowlist conversem com o bot **para** evitar acesso público não autorizado.
- **Como** usuário no Telegram, **quero** receber mensagem clara se enviar texto durante processamento **para** saber que devo aguardar ou usar `/stop`.
- **Como** operador em deploy, **quero** SIGTERM encerrar runs ativos e liberar o bridge SDK **para** reiniciar sem processos zumbis.
- **Como** desenvolvedor, **quero** `PlatformAdapter` como contrato **para** adicionar Discord/Slack no backlog sem reescrever o runner.

## 4. Requisitos funcionais

1. O sistema deve expor entry point `cursor-agent gateway` (ou módulo `gateway/runner.py` invocável).
2. O runner deve carregar `~/.cursor-agent/gateway.yaml` com validação Pydantic.
3. O gateway deve usar `AsyncSdkFacade` + `SessionAgentPool` — mesma stack do CLI ([STRATEGY §2.2](../STRATEGY.md#22-facade-async-first)).
4. Na subida, se `tool_profile != messaging`, o processo deve abortar com erro explícito e exit code ≠ 0.
5. Na subida com perfil messaging, o sistema deve copiar hooks (PRD-005) para o `cwd` configurado.
6. O módulo `gateway/auth.py` deve validar identidade do remetente contra `allowed_users` por plataforma.
7. Mensagens de usuários não allowlisted não devem criar sessão nem chamar o agente.
8. O sistema deve definir protocolo/classe `PlatformAdapter` com métodos mínimos: `start()`, `stop()`, callback de inbound → pool.
9. Em `AgentBusyError`, o adapter deve enviar ao usuário: *“Estou processando sua mensagem anterior. Aguarde ou envie /stop.”* ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).
10. O pool deve manter lock por `session_key`; uma mensagem inbound por vez por chave.
11. Em SIGINT/SIGTERM, o runner deve: parar adapters → cancelar runs (timeout 30s) → dispose facade → flush logs → exit 0 ([ADR-021](../decisions/ADR-021-graceful-shutdown.md)).
12. Após sinal de shutdown, novas mensagens inbound devem ser rejeitadas (flag `shutting_down`).
13. Config de exemplo deve suportar bloco `platforms.telegram` (implementação no PRD-007).

## 5. Não-objetivos

- Implementação completa do adapter Telegram (PRD-007).
- Fila FIFO de mensagens ([BACKLOG-PHASE5](../BACKLOG-PHASE5.md)).
- Múltiplas plataformas habilitadas simultaneamente no MVP (Telegram apenas).
- HTTPS webhook mode (MVP usa polling via PRD-007).
- Cron ou jobs em background (Fase 4).
- Métricas Prometheus / dashboard ops.

## 6. Considerações de design

- **Topologia:** um processo, um event loop, N adapters (MVP: N=1 Telegram).
- **Config:** secrets via variáveis de ambiente (`${TELEGRAM_BOT_TOKEN}`) no YAML.
- **Session key:** definida pelo adapter (`telegram:{chat_id}:{workspace_hash}` — [ADR-004](../decisions/ADR-004-session-key-workspace.md)); runner não hardcoda formato.
- **Logs:** NDJSON em `~/.cursor-agent/logs/` com `session_id`, `platform`, `event` ([ADR-018](../decisions/ADR-018-observability-logs.md)).
- **Fail-fast:** config inválida ou perfil errado → não subir parcialmente.

## 7. Considerações técnicas

- **Pré-requisito bloqueante:** Fase 2b (PRD-005) concluída com aceite de [gateway-security.md](../gateway-security.md).
- **ADRs aplicáveis:**
  - [ADR-008](../decisions/ADR-008-agent-busy-gateway.md) — rejeitar com mensagem, sem fila MVP.
  - [ADR-021](../decisions/ADR-021-graceful-shutdown.md) — sequência SIGTERM.
  - [ADR-014](../decisions/ADR-014-tool-profiles-mvp.md) — só messaging no gateway.
  - [ADR-004](../decisions/ADR-004-session-key-workspace.md) — formato de `session_key` (consumido pelo adapter).
- **Estrutura alvo:** `gateway/runner.py`, `gateway/auth.py`, `gateway/config.py`, `platforms/base.py` (interface).
- **Testes:** runner com `FakeSdkFacade` + adapter mock; auth allowlist; shutdown com runs simulados.

## 8. Métricas de sucesso

- Gateway sobe com `tool_profile: messaging` e recusa `coding`.
- Allowlist bloqueia usuário não listado (teste com adapter mock).
- `AgentBusyError` retorna mensagem amigável em ≤ 1s após segundo inbound.
- SIGTERM encerra em ≤ 35s sem processo bridge órfão (observação manual ou teste integrado).
- Demo: processo estável aguardando adapter Telegram (PRD-007).

## 9. Questões em aberto

- Usuário não allowlisted: ignorar silenciosamente ou responder “não autorizado”?
- `gateway.yaml` único ou override por `--config`?
- Health check HTTP local para systemd (backlog ops)?

## 10. Tarefas de implementação

### Definition of Done

- [ ] Gateway sobe com `tool_profile: messaging`; recusa `coding`
- [ ] Allowlist bloqueia usuário não listado
- [ ] `AgentBusyError` retorna mensagem amigável
- [ ] SIGTERM encerra em ≤ 35s sem bridge órfão ([ADR-021](../decisions/ADR-021-graceful-shutdown.md))

### Tabela de tarefas

| ID | Tarefa | Est. | Dep |
|----|--------|------|-----|
| T1 | `runner.py` + handlers SIGTERM | 6h | PRD-005 |
| T2 | `auth.py` allowlist | 4h | T1 |
| T3 | Interface `PlatformAdapter` | 4h | T1 |
| T4 | `gateway.yaml` + loader Pydantic | 2h | T1 |

### T1 — Runner

- [ ] T1.1 `asyncio` main com `launch_bridge` / facade lifecycle
- [ ] T1.2 Wire `SessionAgentPool` + deploy hooks messaging
- [ ] T1.3 Abort se `tool_profile != messaging`
- [ ] T1.4 SIGINT/SIGTERM → sequência [ADR-021](../decisions/ADR-021-graceful-shutdown.md)
- [ ] T1.5 Flag `shutting_down` para rejeitar novos inbound

### T2 — Auth

- [ ] T2.1 Parser `allowed_users` por plataforma
- [ ] T2.2 `is_allowed(platform, user_id) -> bool`
- [ ] T2.3 Log de tentativa bloqueada (sem vazar token)

### T3 — PlatformAdapter

- [ ] T3.1 Protocol/ABC: `start`, `stop`, `on_message` callback
- [ ] T3.2 Integração inbound → auth → pool.send
- [ ] T3.3 Tratamento `AgentBusyError` → mensagem outbound ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md))

### T4 — Config

- [ ] T4.1 Schema `gateway.yaml` (workspace, tool_profile, platforms)
- [ ] T4.2 Expansão de env vars em strings
- [ ] T4.3 Exemplo documentado em README ou `gateway.yaml.example`

### Demo

1. `cursor-agent gateway` com `tool_profile: messaging` — processo sobe e aguarda adapter.
2. Alterar config para `tool_profile: coding` — processo aborta com erro explícito.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR profile gate | `tests/unit/test_gateway_runner.py` — aborta se `tool_profile != messaging` | `pytest tests/unit/test_gateway_runner.py -k profile -v` |
| FR auth | `tests/unit/test_gateway_auth.py` — allowlist por plataforma | `pytest tests/unit/test_gateway_auth.py -v` |
| FR busy | `tests/unit/test_gateway_busy.py` — `AgentBusyError` → mensagem outbound | `pytest tests/unit/test_gateway_busy.py -v` |
| FR shutdown | `tests/unit/test_gateway_shutdown.py` — SIGTERM ≤35s, flag `shutting_down` | `pytest tests/unit/test_gateway_shutdown.py -v` |
| FR adapter | `tests/unit/test_platform_adapter.py` — Protocol inbound → pool.send | `pytest tests/unit/test_platform_adapter.py -v` |

Ordem sugerida: config loader → auth → adapter protocol → runner lifecycle → shutdown.

### Retroalimentação

**Após concluir PRD-006:** revisar e atualizar [PRD-007](PRD-007-telegram-adapter.md) (§7, §9, §11) antes do adapter Telegram.

**Aprendizados a registrar:**

- [ ] Formato final de `gateway.yaml` e expansão de env vars
- [ ] Comportamento de usuário não allowlisted (silêncio vs. mensagem)
- [ ] Tempo real de graceful shutdown com bridge ativo
- [ ] Contrato `PlatformAdapter` validado em código
- [ ] Implicações para cron coexistindo (PRD-010)
