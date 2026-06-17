---
id: PRD-005
title: Perfil messaging e hooks
status: draft
phase: 2b
depends_on: [PRD-004]
adrs:
  - ADR-001
  - ADR-014
  - ADR-022
related:
  - path: ../gateway-security.md
    role: spec
  - path: ../decisions/ADR-001-messaging-security.md
---

# PRD-005 — Perfil messaging e hooks

## 1. Introdução / Visão geral

Antes de expor o agente via gateway público (Fase 3), o cursor-agent precisa de um **perfil `messaging` comprovadamente restritivo**. O SDK Cursor não desliga tools nativas; a postura de segurança depende de hooks, sandbox e MCP vazio ([ADR-001](../decisions/ADR-001-messaging-security.md)).

**Objetivo:** implementar `tool_profile: messaging` em config, instalar hooks deny em `~/.cursor-agent/hooks/messaging/`, ativar sandbox com rede desligada e validar o threat model em [gateway-security.md](../gateway-security.md). **A Fase 3 fica bloqueada até este PRD estar concluído.**

## 2. Objetivos

- Disponibilizar perfil `coding` e `messaging` no MVP ([ADR-014](../decisions/ADR-014-tool-profiles-mvp.md)).
- Copiar hooks de messaging para o `cwd` na subida de processos que usam o perfil.
- Bloquear escrita, shell destrutivo, MCP arbitrário e leitura de paths sensíveis via hooks.
- Ativar `sandbox_options.enabled: true` (rede off) no perfil messaging via facade.
- Passar no teste de aceite manual documentado em [gateway-security.md §6](../gateway-security.md#6-teste-de-aceite-fase-2b).
- Demonstrar que messaging é materialmente mais restritivo que `coding`.

## 3. User Stories

- **Como** operador do gateway, **quero** que o bot messaging não possa editar arquivos **para** evitar mutação do workspace via Telegram.
- **Como** operador, **quero** que `rm -rf` e pipes destrutivos sejam bloqueados **para** impedir danos mesmo com auto-approve do SDK.
- **Como** desenvolvedor testando localmente, **quero** subir o CLI com `--profile messaging` **para** validar hooks antes do gateway.
- **Como** auditor de segurança, **quero** threat model documentado e testável **para** aceitar o go-live da Fase 3.

## 4. Requisitos funcionais

1. O config loader deve suportar `tool_profile: messaging` além de `coding` ([ADR-014](../decisions/ADR-014-tool-profiles-mvp.md)).
2. O perfil `messaging` deve definir `mcp_servers: {}` (MCP desligado inline).
3. O perfil `messaging` deve definir `sandbox_options.enabled: true` na facade (rede off por padrão).
4. O sistema deve manter hooks em `~/.cursor-agent/hooks/messaging/` com estrutura documentada em [gateway-security.md §4](../gateway-security.md#4-hooks-instalados):
   - `hooks.json`
   - `pre-tool-deny-write.sh`
   - `shell-gate.sh`
   - `mcp-deny.sh`
   - `read-sensitive-deny.sh`
5. Na subida com perfil messaging, o sistema deve copiar hooks para o `cwd` do workspace (gateway ou CLI de teste).
6. `preToolUse` deve negar `Write|StrReplace|Delete|Task`.
7. `beforeShellExecution` deve aplicar denylist destrutiva e allowlist read-only (`git status`, `ls`, `cat`, …).
8. `beforeMCPExecution` deve negar execução MCP (redundante com MCP vazio).
9. `beforeReadFile` deve negar paths sensíveis (`.env`, `~/.ssh`, `*.pem`).
10. O CLI com perfil messaging deve bloquear pedidos destrutivos via hooks (teste manual).
11. Processo configurado com `tool_profile: coding` em contexto de gateway deve ser recusado na Fase 3 (validação preparatória documentada; enforcement completo no PRD-006).

## 5. Não-objetivos

- Implementação do gateway runner (PRD-006).
- Adapter Telegram (PRD-007).
- Perfis `minimal` e `full` ([BACKLOG-PHASE5](../BACKLOG-PHASE5.md)).
- Hooks programáticos por run (limitação do SDK — ver [gateway-security.md §5](../gateway-security.md#5-limitações-conhecidas)).
- Suporte Windows como alvo primário de hooks (testar Linux/macOS VPS).
- Allowlist de usuários Telegram (PRD-006).

## 6. Considerações de design

- **Postura:** messaging = read-only sobre o workspace — Q&A sobre código, sem mutação ([gateway-security.md §1](../gateway-security.md#1-postura)).
- **Deploy de hooks:** cópia para `cwd` na subida, não symlink frágil entre perfis.
- **DX dev:** perfil `coding` mantém auto-approve e hooks moderados (template documentado, não obrigatório).
- **Mensagens de deny:** hooks devem retornar motivo legível quando o SDK expõe feedback ao usuário.
- **Matriz de capacidades:** seguir tabelas “pode / não pode” em [gateway-security.md §2–3](../gateway-security.md#2-o-que-o-bot-messaging-pode-fazer).

## 7. Considerações técnicas

- **Dependências:** PRD-004 (CLI maduro), PRD-001 (facade com `sandbox_options`).
- **ADRs aplicáveis:**
  - [ADR-001](../decisions/ADR-001-messaging-security.md) — hooks em camadas + sandbox + MCP vazio.
  - [ADR-014](../decisions/ADR-014-tool-profiles-mvp.md) — apenas `coding` e `messaging` no MVP; gateway exige messaging.
- **Spec de threat model:** [gateway-security.md](../gateway-security.md) (já aceito; este PRD implementa).
- **Limitações:** sandbox não bloqueia file edit — depende de `preToolUse`; classifier auto-review não é security boundary.
- **Teste destrutivo:** manual na Fase 2b; automatizar cenários críticos onde possível com mocks de hook response.

### Learnings from PRD-004 (pre-implementation)

> Recorded after PRD-004 Wave 7 documentation gate. English per repo docs convention.

**CLI behavior carry-over**

- [x] `/stop` is **cooperative only** — calls `facade.cancel(agent_id)` on the active session; SIGINT handling and gateway busy-state cancellation remain deferred to PRD-006.
- [x] `/usage` reports **last-turn usage** from `ReplState.last_usage` only, not cumulative session totals. Gateway token reporting must define its own aggregation policy.
- [x] `/compress` sets `metadata.status="compressing"`, swaps `agent_id` on the same SQLite session row, and rolls back store state on failure. Crash mid-saga cleanup and orphan SDK agent cleanup ([issue #7](https://github.com/adriannoes/cursor-agent/issues/7)) remain known risks — messaging hooks must not worsen rollback paths.

**Observability and privacy (PRD-004 → PRD-005)**

- [x] Command events emit NDJSON `command_start` / `command_end` (schema v1) with `command`, `session_id` / `session_key`, optional `agent_id`, `duration_ms`, and `outcome`. **Prompt bodies and tool args are omitted** — reuse this shape for gateway audit logs.
- [x] Rich tool badges render **tool name + lifecycle state only**; raw tool args and payloads are intentionally not displayed. Gateway replies and structured logs should follow the same omission policy.

**Config and runtime**

- [x] Local `setting_sources` are threaded from `config.runtime.local.setting_sources` into `AsyncSdkFacade` `LocalAgentOptions` for **local runtime only**. Cloud runtime does not use local `setting_sources` — messaging gateway runs are expected to be local; do not assume project/user rules load on cloud agents.

## 8. Métricas de sucesso

- Todos os 5 cenários de [gateway-security.md §6](../gateway-security.md#6-teste-de-aceite-fase-2b) passam manualmente.
- `git status` permitido; `rm -rf /` e edit de `README.md` bloqueados no perfil messaging.
- Leitura de `.env` bloqueada por `beforeReadFile`.
- Documentação `gateway-security.md` referenciada no PRD permanece alinhada com hooks reais.
- Gate explícito: checklist “Fase 2b ✅” antes de iniciar PRD-006.

## 9. Questões em aberto

- ~~Hooks devem ser copiados também no CLI `coding` como template opt-in, ou só no fluxo messaging?~~ **Resolvido (PRD-004):** README documents an optional `.cursor/hooks.json` dev template for `coding` only; automatic copy/deploy of deny hooks stays **messaging-only** in this PRD (see [gateway-security.md §4](../gateway-security.md#4-hooks-instalados)).
- Workspace de teste dedicado para aceite destrutivo vs. `cwd` do desenvolvedor?
- Versionar hooks no repo (`cursor-agent/hooks/messaging/`) além de `~/.cursor-agent/`?
- **Novo (PRD-004):** Gateway runner must not expose `/stop`-style cooperative cancel as the only interrupt path — SIGINT and busy-session behavior are PRD-006 scope; document expected operator UX when a messaging turn is in flight.
- **Novo (PRD-004):** Should gateway audit logs extend PRD-004 command events (schema v1) for hook deny outcomes, or introduce a separate `hook_deny` event type?
- **Novo (PRD-004):** `/usage` last-turn semantics do not map to per-user Telegram billing — define whether gateway surfaces usage at all before PRD-007.

## 10. Tarefas de implementação

### Definition of Done

- [ ] Todos os 5 cenários de [gateway-security.md §6](../gateway-security.md#6-teste-de-aceite-fase-2b) passam manualmente
- [ ] Perfil `messaging` materialmente mais restritivo que `coding`
- [ ] Hooks deployados para `cwd` na subida com perfil messaging
- [ ] `sandbox_options.enabled: true` propagado à facade

### Tabela de tarefas

| ID | Tarefa | Est. | Dep |
|----|--------|------|-----|
| T1 | hooks.json + scripts shell | 8h | PRD-004 |
| T2 | Deploy hooks para `cwd` | 4h | T1 |
| T3 | `sandbox_options` no perfil messaging (facade) | 2h | PRD-001 |
| T4 | Teste manual destrutivo | 2h | T2 |
| T5 | Review `gateway-security.md` vs implementação | 1h | T4 |

### T1 — Hooks messaging

- [ ] T1.1 `hooks.json` com matchers conforme [ADR-001](../decisions/ADR-001-messaging-security.md)
- [ ] T1.2 `pre-tool-deny-write.sh`
- [ ] T1.3 `shell-gate.sh` (denylist + allowlist read-only)
- [ ] T1.4 `mcp-deny.sh`
- [ ] T1.5 `read-sensitive-deny.sh`
- [ ] T1.6 Instalar em `~/.cursor-agent/hooks/messaging/`

### T2 — Deploy

- [ ] T2.1 Função copiar hooks → `cwd/.cursor/hooks/` (ou path SDK)
- [ ] T2.2 Invocar na subida quando `tool_profile == messaging`
- [ ] T2.3 Log estruturado de deploy de hooks

### T3 — Sandbox e config

- [ ] T3.1 Entrada `tool_profile: messaging` no config loader
- [ ] T3.2 `mcp_servers: {}` inline no perfil
- [ ] T3.3 `sandbox_options.enabled: true` propagado à facade

### T4 — Aceite manual

- [ ] T4.1 Cenário 1: `rm -rf /` bloqueado
- [ ] T4.2 Cenário 2: edit `README.md` bloqueado
- [ ] T4.3 Cenário 3: `git status` permitido
- [ ] T4.4 Cenário 4: ler `.env` bloqueado
- [ ] T4.5 Registrar evidência (log ou nota de teste)

### T5 — Documentação

- [ ] T5.1 Confirmar alinhamento [gateway-security.md](../gateway-security.md) ↔ scripts reais
- [ ] T5.2 Atualizar README com risco auto-approve em `coding` vs postura `messaging`

### Demo

1. `cursor-agent --profile messaging` — pedir `rm -rf /` → hook bloqueia.
2. Mesmo perfil — `git status` → permitido.
3. Pedir editar `README.md` → `preToolUse` deny.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR hooks deploy | `tests/unit/test_hooks_deploy.py` — cópia para `cwd`, matchers | `pytest tests/unit/test_hooks_deploy.py -v` |
| FR sandbox | `tests/unit/test_messaging_profile.py` — `sandbox_options`, MCP vazio | `pytest tests/unit/test_messaging_profile.py -v` |
| FR aceite | Checklist manual [gateway-security.md §6](../gateway-security.md#6-teste-de-aceite-fase-2b) (5 cenários) | Evidência em nota de teste / log |

Ordem sugerida: testes unitários de deploy/config → implementar hooks → aceite manual destrutivo.

### Retroalimentação

**Após concluir PRD-005 (gate 2b):** revisar e atualizar [PRD-006](PRD-006-gateway-core.md) (§7, §9, §11) antes do gateway.

### Learnings from PRD-004 (slash commands) — pre-PRD-005 gate

> Input for this PRD from [PRD-004](PRD-004-slash-commands.md) implementation. English per repo docs convention.

**Commands and gateway surface**

- [x] `/stop` — cooperative `facade.cancel(agent_id)` only; no SIGINT or gateway busy handling yet. Messaging profile should assume destructive tools may still run until hook deny fires — do not treat `/stop` as a security control.
- [x] `/usage` — shape is last-turn `RunResult.usage` cached in `ReplState.last_usage`, not session cumulative. Omit or redesign before exposing via Telegram.
- [x] Command NDJSON events (`command_start`, `command_end`, schema v1) are the baseline audit trail; prompt bodies and tool args excluded by design.

**Display and logging privacy**

- [x] Rich tool badges: name + state only — no raw args/payloads in CLI output. Gateway bot replies and NDJSON logs must apply the same rule ([ADR-018](../decisions/ADR-018-observability-logs.md)).

**Config limitations**

- [x] `setting_sources` flow: `config.runtime.local.setting_sources` → facade `LocalAgentOptions` for local runtime; cloud agents ignore local setting sources. Messaging deploy and hook copy target local `cwd` only.

**Compress saga risks (do not amplify in hooks deploy)**

- [x] `/compress` rollback on failure is implemented in SQLite; crash mid-saga and orphan SDK agents remain open risks. Hook deploy and profile switch must not leave `metadata.status` stuck or duplicate agents.

**Aprendizados a registrar (during PRD-005 implementation):**

- [ ] Cenários de aceite que falharam e ajustes nos scripts
- [ ] Latência dos hooks no caminho crítico do send
- [ ] Path real de deploy (`cwd/.cursor/hooks/`) vs. documentação
- [ ] Diferenças observadas `coding` vs. `messaging` na prática
- [ ] Requisitos extras para runner gateway (SIGTERM, allowlist, cooperative cancel vs hook deny ordering)
