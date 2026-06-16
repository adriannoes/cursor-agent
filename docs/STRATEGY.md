# cursor-agent — Estratégia e Plano de Implementação

> Agent *clean-room* inspirado no **comportamento** do [Hermes Agent](https://github.com/NousResearch/hermes-agent) e em padrões de gateway do [OpenClaw](https://github.com/openclaw/openclaw). Pode estudar **docs e codebases** de referência para entender como problemas foram resolvidos — **zero código copiado** (reimplementação com Cursor SDK). Motor: [Cursor Python SDK](https://cursor.com/docs/sdk/python) + **Composer 2.5**.

| Campo | Valor |
|-------|-------|
| Versão | **1.2** (2026-06-12) |
| Linguagem | Python 3.11+ |
| Motor | `cursor-sdk` |
| Backlog pós-MVP | [BACKLOG-PHASE5.md](BACKLOG-PHASE5.md) |
| ADRs | [DECISIONS.md](DECISIONS.md) |
| PRDs | [prd/README.md](prd/README.md) |
| Contratos | [contracts/async-sdk-facade.md](contracts/async-sdk-facade.md) |

---

## Sumário

1. [Visão](#1-visão)
2. [Decisões fechadas](#2-decisões-fechadas)
3. [Arquitetura](#3-arquitetura)
4. [Topologia de deploy](#4-topologia-de-deploy)
5. [Stack e estrutura do repo](#5-stack-e-estrutura-do-repo)
6. [Roadmap e dependências entre fases](#6-roadmap-e-dependências-entre-fases)
7. [Fase 0 — Spike](#7-fase-0-spike)
8. [Fase 1 — CLI + sessões](#8-fase-1-cli-sessões)
9. [Fase 2 — CLI Hermes-like + segurança](#9-fase-2-cli-hermes-like-segurança)
10. [Fase 2b — Perfil messaging (gate do gateway)](#10-fase-2b-perfil-messaging-gate-do-gateway)
11. [Fase 3 — Gateway Telegram](#11-fase-3-gateway-telegram)
12. [Fase 4 — Memória, skills, cron](#12-fase-4-memória-skills-cron)
13. [Fase 5](#13-fase-5)
14. [Segurança, ops, riscos, DoD](#14-segurança-ops-riscos-dod)
15. [Referências e apêndices](#15-referências-e-apêndices)

---

## 1. Visão

### 1.1 Tese

O Hermes implementa internamente loop agentic, 70+ tools, 18+ providers e gateway multi-plataforma. O **cursor-agent** delega loop, tools e inferência ao **Cursor SDK** e implementa apenas:

- **Orquestração** — sessões, config, concorrência
- **UX** — CLI, slash commands, gateway
- **Policy** — hooks, perfis, allowlists

### 1.2 Objetivos (Fases 0–4)

| Objetivo | Métrica |
|----------|---------|
| Agent + Composer 2.5 | Setup < 5 min; turn com tools |
| Sessões | `/new`, `/resume` por **session id** nosso |
| CLI | REPL com streaming |
| Gateway | Telegram + allowlist + perfil `messaging` |
| Extensibilidade | `.cursor/rules`, MCP, skills via SDK |
| Clean room | Zero código copiado de referências (Hermes, OpenClaw, etc.) |

### 1.3 Não-objetivos

- Multi-provider (OpenRouter, etc.)
- Self-hosted inference
- Paridade 1:1 com 70+ tools do Hermes
- TUI completa estilo Hermes — **stretch goal** Fase 5 ([ADR-015](decisions/ADR-015-tui-stretch-goal.md)); MVP usa CLI Rich
- API Python pública como produto (ver §2.6)

### 1.4 Relação com outros projetos

> **Este repositório é apenas o cursor-agent.** Outros projetos citados abaixo são complementares — não são dependências nem fazem parte do roadmap Fases 0–4.

| Projeto | Papel | Relação com cursor-agent |
|---------|-------|--------------------------|
| **cursor-agent** (este repo) | Orquestração + UX sobre **Cursor SDK** (Composer 2.5) | — |
| **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** | Referência **comportamental** (paridade UX/escopo) | Docs públicas **e** codebase para entender sessão, gateway, slash UX, perfis; **zero código** copiado |
| **[OpenClaw](https://github.com/openclaw/openclaw)** | Referência **arquitetural** de gateway | Multi-canal, onboarding, plugins/channels — especialmente ao desenhar `PlatformAdapter` (Fase 3+); **zero código** copiado |
| **[shellclaw](https://github.com/adriannoes/shellclaw)** | Runtime agent em C, self-hosted, canais próprios | **Projeto separado** do mesmo autor; sem código nem roadmap compartilhado |

**Quando usar qual:** cursor-agent quando o motor Cursor for desejado; shellclaw para runtime self-hosted em C. OpenClaw e Hermes informam **como** implementar gateway e UX — não entram como dependência de runtime.

#### Como usar referências

Projetos externos são **inspiração arquitetural e comportamental**, não dependências. Podemos ler docs públicas **e** navegar codebases de referência para entender *como* um problema foi resolvido — sempre em cruzamento com nossos ADRs e restrições do Cursor SDK.

| Projeto | O que estudar | Limite |
|---------|---------------|--------|
| **Hermes Agent** | Modelo de sessão, gateway, slash UX, perfis de tools | **Clean-room:** reimplementar em `cursor_agent`; nunca copiar trechos do repo |
| **OpenClaw** | Gateway multi-canal, onboarding, arquitetura plugin/channel, roteamento | Referência para `PlatformAdapter` e Fase 3+; mesmo limite clean-room |
| **shellclaw** | — | Projeto separado; sem estudo obrigatório nem código compartilhado |

**Método (por feature):**

1. Identificar o problema no PRD/task ativo.
2. Ver como a referência resolve (docs + codebase, quando útil).
3. Cruzar com ADRs ([002](decisions/ADR-002-async-sdk-facade.md), [008](decisions/ADR-008-agent-busy-gateway.md), [014](decisions/ADR-014-tool-profiles-mvp.md)…) e limitações do Cursor SDK.
4. Implementar em `cursor_agent` com TDD ([ADR-022](decisions/ADR-022-tdd-prd-feedback-loop.md)).

**Regras explícitas:**

- Inspiração **≠** dependência: sem vendoring, fork ou submodule de projetos de referência.
- Código deste repositório é **nosso** — padrões estudados, implementação original.

---

## 2. Decisões fechadas

> Consolidadas da revisão v1.0–v1.2. **Fonte de verdade detalhada:** [DECISIONS.md](DECISIONS.md) (ADRs com opções rejeitadas).

### 2.1 Modelo de sessão (dupla persistência)

```text
session_key  →  SessionStore (SQLite)  →  agent_id  →  SDK (histórico + checkpoint)
```

| Conceito | Responsabilidade |
|----------|------------------|
| `session_key` | Identidade lógica: `cli:{profile}:{workspace_hash}`, `telegram:{chat_id}:{workspace_hash}` — ver [ADR-004](decisions/ADR-004-session-key-workspace.md) |
| `session id` (UUID) | PK no SQLite; exposto ao usuário em `/resume` |
| `agent_id` | ID Cursor (`agent-*` / `bc-*`); **interno**, não é UX principal |
| Histórico de conversa | **Fonte da verdade: SDK** via `agent_id` |
| Metadados (título, plataforma, workspace) | **Fonte da verdade: SessionStore** |

**Regras:**

- `/resume` sem argumento → última sessão do `session_key` atual
- `/resume <session-id>` → sessão pelo UUID nosso → `Agent.resume(agent_id)`; **runtime deve coincidir** ([ADR-003](decisions/ADR-003-cross-runtime-resume.md))
- `/new` → novo `agent_id` + novo row SQLite; sessão anterior permanece listável (`/reset` é alias — [ADR-013](decisions/ADR-013-slash-commands-skills.md))
- `/compress` → fluxo explícito (§9.1); atualiza `agent_id` no mesmo `session id` ([ADR-011](decisions/ADR-011-compress-flow.md))

### 2.2 Facade async-first

- Implementar **`AsyncSdkFacade`** como API principal (`AsyncClient.launch_bridge`) — contrato em [contracts/async-sdk-facade.md](contracts/async-sdk-facade.md), decisão [ADR-002](decisions/ADR-002-async-sdk-facade.md)
- CLI sync usa `asyncio.run()` por comando ou REPL async único
- Gateway e cron usam a mesma facade — **sem** segunda implementação sync

### 2.3 Concorrência — SessionAgentPool

```text
SessionAgentPool
  ├── get(session_key) → AsyncAgent (lazy resume via agent_id)
  ├── send(session_key, msg) → asyncio.Lock por session_key
  └── cron / background → agent_id dedicado por job (nunca compartilha com chat)
```

- **CLI:** `send` usa lock **bloqueante** (`await lock.acquire()`) — aguarda fim do run ou `/stop`
- **Gateway:** `send` usa **`try_acquire`** — se lock ocupado, levanta `AgentBusyError` com mensagem amigável ([ADR-008](decisions/ADR-008-agent-busy-gateway.md))
- Uma mensagem inbound por vez por `session_key`

### 2.4 Personalidade e contexto

| Mecanismo | Uso |
|-----------|-----|
| `.cursor/rules` | **Canal principal** de personalidade e instruções |
| `setting_sources: ["project", "user"]` | Carrega rules, MCP, agents, skills do SDK |
| `~/.cursor-agent/rules/` | Rules globais do usuário (via symlink ou cópia para path referenciado) |
| `SOUL.md` | Opcional; **não** injetar como prefix manual — converter ou symlink para rules |

**Não fazer:** prefixar SOUL.md na mensagem do usuário (quebra cache e duplica `.cursor/rules`).

### 2.5 Skills

- **Fase 4:** descoberta via `setting_sources` + `.cursor/skills/` (padrão Cursor / agentskills.io)
- Comando `/skills` lista o que o workspace expõe
- **Sem** loader custom salvo gap comprovado após Fase 4

### 2.6 Memória (v1 — Fase 4)

- Arquivos `~/.cursor-agent/MEMORY.md` e `USER.md`
- Injeção: conteúdo no **primeiro turn** após `/new` ou `/resume` (flag `memory_injected`); cap **8 KB** — [ADR-010](decisions/ADR-010-memory-v1.md)
- Atualização: agent escreve via tools do SDK ou template `/memory update`
- Busca semântica / FTS → [BACKLOG-PHASE5.md](BACKLOG-PHASE5.md)

### 2.7 Perfis de tools e segurança

O SDK **não desliga** tools nativas (`shell`, `edit`, …). Controle real:

1. **Hooks** `.cursor/hooks.json` — deny/allow shell e MCP
2. **MCP** — perfil define quais servers inline
3. **Gateway** — obrigatório `tool_profile: messaging` + hooks + sandbox ([Fase 2b](#10-fase-2b-perfil-messaging-gate-do-gateway), [ADR-001](decisions/ADR-001-messaging-security.md), [gateway-security.md](gateway-security.md))

**MVP:** apenas perfis `coding` e `messaging` ([ADR-014](decisions/ADR-014-tool-profiles-mvp.md)).

### 2.8 Escopo de API pública

- **Entregue:** CLI (`cursor-agent`) e módulos internos testáveis
- **Fora do escopo Fase 0–4:** biblioteca Python estável para terceiros (`import cursor_agent as lib`) — ver [ADR-019](decisions/ADR-019-packaging-license.md)
- Diagramas não incluem “Library API” como entry point até decisão explícita

---

## 3. Arquitetura

```text
┌──────────────────────────────────────────────────────────────┐
│  Entry points: CLI (cursor-agent)  |  Gateway (long-run)     │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│  Config │ SessionStore │ Commands │ SessionAgentPool         │
│  PlatformAdapter (Telegram)                                  │
└────────────────────────────┬─────────────────────────────────┘
                             ▼
                    AsyncSdkFacade  ← único import cursor_sdk
                             ▼
                    Cursor SDK (Composer 2.5 + tools)
                             ▼
                  Local cwd  |  Cloud VM
```

### 3.1 Fluxo CLI

```text
input → CommandRouter → SessionStore.resolve(session_key)
     → SessionAgentPool.send → AsyncSdkFacade
     → stream → display → SessionStore.touch()
```

### 3.2 Contrato AsyncSdkFacade

Especificação completa: **[contracts/async-sdk-facade.md](contracts/async-sdk-facade.md)** ([ADR-002](decisions/ADR-002-async-sdk-facade.md)).

```python
# Conceitual — ver contrato para tipos e erros
class AsyncSdkFacade:
    async def create_agent(self, *, workspace, model="composer-2.5", ...) -> str: ...
    async def resume_agent(self, agent_id: str, *, workspace) -> AsyncAgent: ...
    async def send(self, agent, message: str, *, callbacks...) -> RunResult: ...
    async def cancel(self, agent) -> None: ...
```

Bridge, retry, dispose e re-injeção de MCP no resume ficam na facade. `AgentBusyError` é levantado pelo `SessionAgentPool` quando o lock está ocupado (modo gateway) — ver §2.3 e [ADR-008](decisions/ADR-008-agent-busy-gateway.md).

---

## 4. Topologia de deploy

| Modo | Runtime SDK | Onde roda | Uso |
|------|-------------|-----------|-----|
| **dev** | Local | Laptop | CLI, desenvolvimento |
| **gateway** | Local | VPS / macOS sempre-on | `cwd` = workspace do projeto no host |
| **batch** | Cloud | VM Cursor | Cron pesado, PRs, jobs longos |

**Regras:**

- Gateway **não** usa cloud por padrão (latência, custo, `cwd` local)
- Cron leve (resumo diário) → local + `agent_id` dedicado
- Cron que altera repo remoto / abre PR → cloud

### Deploy pessoal (laptop / PC antigo)

Para uso **24/7 em máquina própria** (laptop ligado, Mac mini, PC antigo dedicado), **não é necessária VM na nuvem** no MVP. O gateway é um processo long-running local (`cursor-agent gateway`) na mesma máquina onde o workspace vive — `runtime.mode: local` e `cwd` apontando para o repo no host.

| Cenário | Onde roda | VM cloud? |
|---------|-----------|-----------|
| CLI interativo | Qualquer máquina | Não |
| Gateway Telegram 24/7 | Laptop/PC sempre-on **ou** VPS | Não (local-first); VPS só se quiser isolamento/uptime separado do laptop |
| Cron pesado / PR remoto | VM Cursor (`runtime: cloud`) | Sim — opcional, Fase 4 |

**Ops mínimas:** `systemd` / `launchd` / `tmux` para manter o gateway vivo; allowlist Telegram obrigatória (Fase 2b antes de expor bot).

```yaml
# Exemplo gateway em VPS
runtime:
  mode: local
  local:
    cwd: "/home/agent/projects/my-repo"
    setting_sources: ["project"]
tool_profile: messaging   # obrigatório para gateway
```

---

## 5. Stack e estrutura do repo

### 5.1 Stack

| Pacote | Fase |
|--------|------|
| `cursor-sdk` | 0 — pin exato ([ADR-017](decisions/ADR-017-sdk-version-pin.md)) |
| `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy` | 0 ([ADR-005](decisions/ADR-005-testing-strategy.md), [ADR-026](decisions/ADR-026-quality-tooling.md)) |
| `typer`, `pydantic-settings`, `pyyaml` | 1 ([ADR-007](decisions/ADR-007-config-loader.md)) |
| `rich` | 2 |
| `aiosqlite` | 1 (store async-ready) |
| `aiogram` | 3 ([ADR-006](decisions/ADR-006-telegram-library.md)) |
| `apscheduler` | 4 |

### 5.2 Estrutura alvo (Fase 4)

```text
src/cursor_agent/
├── cli/              # REPL, display
├── commands/         # slash registry
├── config/
├── gateway/          # runner, auth, platforms/telegram
├── memory/           # MEMORY.md loader (v1)
├── sessions/         # models, store
├── pool.py           # SessionAgentPool
└── sdk_facade.py     # AsyncSdkFacade — único import cursor_sdk
```

Dados do usuário: `~/.cursor-agent/{config.yaml,sessions.db,MEMORY.md,logs/}`

---

## 6. Roadmap e dependências entre fases

```text
Fase 0 ──► Fase 1 ──► Fase 2 ──► Fase 2b ──► Fase 3 ──► Fase 4
(spike)    (CLI)      (UX)       (segurança)  (Telegram)  (mem+cron)
         PRD-008/009 podem iniciar após PRD-004 (paralelo ao gate 2b e Fase 3)
```

| Fase | Duração | Entrega |
|------|---------|---------|
| 0 | 2–4 dias | SDK validado, async, `tools list` |
| 1 | 1 sprint | CLI + SessionStore + AsyncSdkFacade |
| 2 | 1 sprint | Slash commands, rules, streaming |
| **2b** | 2–3 dias | Perfil `messaging` + hooks deny — **bloqueia Fase 3** |
| 3 | 1–2 sprints | Gateway Telegram |
| 4 | 1–2 sprints | MEMORY.md, skills via SDK, cron |

**Total Fases 0–4:** ~6–8 semanas (1 dev, parcial).

> **Memória e skills — agrupamento de roadmap:** PRD-008 (memória) e PRD-009 (skills) aparecem na Fase 4 por organização de roadmap, **não** por restrição técnica. Ambos dependem apenas de PRD-004 (slash commands + Rich, Fase 2) e podem ser antecipados em paralelo ao gate 2b (PRD-005) e à Fase 3. Apenas PRD-010 (cron) permanece preso à Fase 3, por exigir delivery Telegram (PRD-006 + PRD-007). Ver [prd/README.md — Ordem de execução](prd/README.md#ordem-de-execução).

---

## 7. Fase 0 — Spike

**PRD:** [prd/PRD-000-sdk-spike.md](prd/PRD-000-sdk-spike.md)

**Objetivo:** Validar ambiente antes de arquitetura.

### Sprint 0.1 — Spike SDK

- [ ] `pyproject.toml` (`cursor-sdk`, `pytest`, `ruff`)
- [ ] `examples/async_repl.py` — `AsyncClient.launch_bridge`, Composer 2.5
- [ ] `examples/tools_list.py` — introspecção `SDKSystemMessage.tools`
- [ ] Salvar output em `docs/sdk-tools-snapshot.txt` (baseline da conta)
- [ ] Medir cold start; documentar em comentário no exemplo
- [ ] `tests/integration/test_sdk_smoke.py` — skip sem `CURSOR_API_KEY`
- [ ] Teste: turn com tool (`grep` / read file); segundo turn mantém contexto
- [ ] Decisão registrada: **local-first** para CLI/gateway; cloud para batch

**Aceite:** API key funciona; bridge async OK; inventário de tools documentado; pronto para Fase 1 facade ([PRD-000](prd/PRD-000-sdk-spike.md)).

---

## 8. Fase 1 — CLI + sessões

**PRDs:** [PRD-001](prd/PRD-001-facade.md), [PRD-002](prd/PRD-002-session-store.md), [PRD-003](prd/PRD-003-cli-repl.md)

**Objetivo:** CLI instalável; contrato de sessão (§2.1).

### Tarefas

- [ ] `AsyncSdkFacade` + context manager (`async with`)
- [ ] `SessionStore` (SQLite + `aiosqlite`)
- [ ] `SessionAgentPool` (locks por `session_key`)
- [ ] `config/loader.py` — YAML + env; precedência CLI > env `CURSOR_AGENT__*` > YAML > defaults ([ADR-007](decisions/ADR-007-config-loader.md))
- [ ] Títulos de sessão: primeira mensagem truncada a 60 chars ([ADR-009](decisions/ADR-009-session-titles.md))
- [ ] REPL: `cursor-agent` (Typer + asyncio)
- [ ] Comandos: conversa livre, `/quit`
- [ ] `/new`, `/resume [session-id]`, `cursor-agent sessions list`
- [ ] Erros: exit 1 = `CursorAgentError`; exit 2 = `result.status == "error"`

### Schema SQLite

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    session_key TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    title TEXT,
    workspace TEXT NOT NULL,
    runtime TEXT NOT NULL,
    tool_profile TEXT DEFAULT 'coding',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata JSON
);
CREATE INDEX idx_sessions_key ON sessions(session_key, updated_at DESC);
```

### Config mínimo

```yaml
model: composer-2.5
tool_profile: coding
runtime:
  mode: local
  local:
    cwd: "."
    setting_sources: ["project", "user"]
```

**Aceite:** Reiniciar processo e `/resume` restaura conversa via `agent_id`.

---

## 9. Fase 2 — CLI Hermes-like + segurança

**PRD:** [prd/PRD-004-slash-commands.md](prd/PRD-004-slash-commands.md)

**Objetivo:** UX próxima ao Hermes; rules; hooks para dev.

### 9.1 Slash commands

| Comando | Prioridade | Notas |
|---------|------------|-------|
| `/new`, `/reset` | P0 | Novo `agent_id`; `/reset` = alias ([ADR-013](decisions/ADR-013-slash-commands-skills.md)) |
| `/resume [id]` | P0 | §2.1 |
| `/help`, `/quit` | P0 | |
| `/stop` | P1 | `run.cancel()` |
| `/model [id]` | P1 | Default `composer-2.5` |
| `/retry` | P2 | Reenvia última mensagem usuário |
| `/usage` | P2 | Tokens se `TurnEndedUpdate.usage` |
| `/compress` | P2 | Fluxo abaixo |

**Fluxo `/compress`:** ver [ADR-011](decisions/ADR-011-compress-flow.md); prompt em [prompts/compress.txt](prompts/compress.txt).

1. Setar `metadata.status = "compressing"` no SessionStore
2. Enviar prompt de resumo ao agent atual → `run.wait()` → obter resumo
3. `/new` interno → novo `agent_id`
4. Atualizar **mesmo** `session id` no SQLite com novo `agent_id`
5. Enviar resumo como primeira mensagem da nova sessão
6. Limpar `metadata.status`
7. **Em falha:** manter `agent_id` anterior; limpar status; mensagem de erro ao usuário

### 9.2 Contexto e personalidade

- [ ] `setting_sources: ["project", "user"]` na facade
- [ ] Documentar: personalidade via `.cursor/rules` apenas (§2.4)
- [ ] `/personality` — backlog Fase 5 ([BACKLOG-PHASE5.md](BACKLOG-PHASE5.md)); não implementar no MVP
- [ ] MCP via `.cursor/mcp.json` do workspace

### 9.3 Display e hooks (dev)

- [ ] `rich` — streaming, badges de tool
- [ ] Template `.cursor/hooks.json` para dev (documentado, não obrigatório)
- [ ] Documentar risco auto-approve em README

**Aceite:** 8+ comandos; rules do projeto afetam comportamento; MCP funciona.

---

## 10. Fase 2b — Perfil messaging (gate do gateway)

**PRD:** [prd/PRD-005-messaging-profile.md](prd/PRD-005-messaging-profile.md)  
**Threat model:** [gateway-security.md](gateway-security.md) ([ADR-001](decisions/ADR-001-messaging-security.md))

**Objetivo:** Pré-requisito de segurança antes de qualquer bot público.

> **Fase 3 não inicia sem 2b concluída.**

### Entregas

- [ ] `tool_profile: messaging` em config
- [ ] Hooks deny para gateway workspace — exemplos:
  - `rm -rf`, `mkfs`, `dd if=`
  - pipe para shell remoto (`curl|bash`, `wget|sh`)
  - alteração de `~/.ssh`, `/etc`
- [ ] MCP desligado no perfil messaging (`mcp_servers: {}` inline)
- [ ] `sandbox_options.enabled: true` no perfil messaging (rede off)
- [ ] `docs/gateway-security.md` — threat model completo
- [ ] Teste manual: pedir comando destrutivo via CLI com perfil messaging → hook bloqueia

**Aceite:** Perfil messaging comprovadamente mais restritivo que `coding`.

---

## 11. Fase 3 — Gateway Telegram

**PRDs:** [PRD-006](prd/PRD-006-gateway-core.md), [PRD-007](prd/PRD-007-telegram-adapter.md)

**Objetivo:** Processo long-running; Telegram com allowlist.

**Pré-requisitos:** Fase 2b ✅

### Tarefas

- [ ] `gateway/runner.py` — `AsyncSdkFacade` + `SessionAgentPool`
- [ ] `session_key = telegram:{chat_id}:{workspace_hash}` ([ADR-004](decisions/ADR-004-session-key-workspace.md))
- [ ] `platforms/telegram.py` — aiogram 3.x ([ADR-006](decisions/ADR-006-telegram-library.md))
- [ ] Chunking 4096 + typing ([ADR-012](decisions/ADR-012-telegram-chunking.md))
- [ ] Slash: `/new`, `/stop`, `/help` no adapter
- [ ] `gateway/auth.py` — allowlist obrigatória
- [ ] Config `~/.cursor-agent/gateway.yaml`
- [ ] Shutdown gracioso SIGINT/SIGTERM ([ADR-021](decisions/ADR-021-graceful-shutdown.md))
- [ ] Forçar `tool_profile: messaging` no gateway (recusa subir se `coding`)

```yaml
platforms:
  telegram:
    enabled: true
    bot_token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users: [123456789]
```

**Aceite:** Allowlist funciona; perfil messaging ativo; `/new` isola sessão; pool evita `AgentBusyError` em uso normal.

---

## 12. Fase 4 — Memória, skills, cron

**PRDs:** [PRD-008](prd/PRD-008-memory-v1.md), [PRD-009](prd/PRD-009-skills.md), [PRD-010](prd/PRD-010-cron.md).

> **Roadmap vs técnica:** o agrupamento na Fase 4 é escolha de roadmap. **PRD-008** e **PRD-009** dependem apenas de **PRD-004** e podem iniciar em paralelo com o gate 2b (PRD-005) e a Fase 3. **PRD-010** exige PRD-006 + PRD-007 (delivery Telegram no DoD). Os três irmãos paralelizam após retro mínima do PRD-007 — sem retro encadeada entre si ([ADR-022](decisions/ADR-022-tdd-prd-feedback-loop.md), [prd/README](prd/README.md)).

### 12.1 Skills (via SDK)

- [ ] `/skills` — lista skills visíveis via project rules/skills
- [ ] `/<skill-name>` — injeta conteúdo da skill ([ADR-013](decisions/ADR-013-slash-commands-skills.md))
- [ ] Sem loader paralelo ao SDK

### 12.2 Memória v1

- [ ] `memory/store.py` — ler `MEMORY.md` + `USER.md`
- [ ] Cap 8 KB injetado no primeiro turn (§2.6, [ADR-010](decisions/ADR-010-memory-v1.md))
- [ ] `/memory show`

### 12.3 Cron

- [ ] `apscheduler` + `~/.cursor-agent/cron/jobs.yaml`
- [ ] **Cada job → `agent_id` dedicado** (não compartilha com chat)
- [ ] Delivery opcional → Telegram `chat_id`
- [ ] `cursor-agent cron list|add|remove`
- [ ] Jobs cloud: flag `runtime: cloud` no job (batch mode)

**Aceite:** Cron dispara e entrega; gateway e cron sem busy conflict; memória persiste entre sessões novas.

---

## 13. Fase 5

Backlog completo (tools, plataformas, trimestres): **[BACKLOG-PHASE5.md](BACKLOG-PHASE5.md)**

Não bloqueia Fases 0–4.

---

## 14. Segurança, ops, riscos, DoD

### 14.1 Segurança

| Contexto | Postura |
|----------|---------|
| CLI dev (`coding`) | Auto-approve SDK; dev responsável |
| Gateway | Allowlist + `messaging` + hooks deny |
| Cloud batch | VM isolada; secrets via `env_vars` |

### 14.2 Observabilidade

Logs JSON NDJSON em `~/.cursor-agent/logs/` — schema v1: [ADR-018](decisions/ADR-018-observability-logs.md). Campos: `session_id`, `agent_id`, `run_id`, `request_id`, `duration_ms`.

### 14.3 Riscos principais

| Risco | Mitigação |
|-------|-----------|
| SDK breaking changes | Pin versão; facade isolada |
| Gateway com shell | Fase 2b obrigatória |
| `AgentBusyError` | SessionAgentPool + locks |
| Vendor lock-in | Aceito; documentado |
| Custo cron | Limites de frequência; cloud só quando necessário |

### 14.4 Definition of Done por fase

| Fase | DoD |
|------|-----|
| 0 | Smoke + async + `tools list` snapshot |
| 1 | CLI instalável; resume funciona após restart |
| 2 | 8+ comandos; rules + MCP |
| 2b | Perfil messaging testado com hooks deny |
| 3 | Telegram E2E; allowlist; sem profile coding |
| 4 | MEMORY 8KB + cron dedicado + skills list |

### 14.5 Verificação global

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
pytest -m integration  # requer CURSOR_API_KEY
cursor-agent --help
cursor-agent sessions list
cursor-agent tools list
```

### 14.6 Processo de desenvolvimento

Todo PRD segue **TDD obrigatório** e **retroalimentação** antes do PRD seguinte — ver [ADR-022](decisions/ADR-022-tdd-prd-feedback-loop.md) e [prd/README.md — Fluxo de desenvolvimento](prd/README.md#fluxo-de-desenvolvimento).

| Etapa | Regra |
|-------|-------|
| Por FR | Teste pytest falhando → implementar → verde |
| Fim do PRD-N | Atualizar PRD-(N+1) com aprendizados (§11) |
| Gate | Não iniciar o **próximo PRD numerado** sem retro concluída |
| Fase 4 paralelo | PRD-008/009 após PRD-004; PRD-010 após PRD-007; retro mínima do PRD-007 como gate dos irmãos — sem retro 008→009→010 |

> **Retro vs paralelismo (Fase 4):** o gate de retro vale para o **próximo PRD numérico** da cadeia principal; os irmãos da Fase 4 (PRD-008/009/010) paralelizam após a retro mínima do PRD-007, **sem** retro encadeada entre si — ver [prd/README.md — Fluxo de desenvolvimento](prd/README.md#fluxo-de-desenvolvimento).

---

## 15. Referências e apêndices

### Documentação

- [DECISIONS.md](DECISIONS.md) — ADRs (26 decisões)
- [prd/README.md](prd/README.md) — PRDs executáveis
- [gateway-security.md](gateway-security.md) — threat model messaging
- [contracts/async-sdk-facade.md](contracts/async-sdk-facade.md)
- [Cursor Python SDK](https://cursor.com/docs/sdk/python)
- [Hermes — arquitetura](https://hermes-agent.nousresearch.com/docs/developer-guide/architecture) e [repo](https://github.com/NousResearch/hermes-agent) (estudo de padrões; zero código copiado)
- [OpenClaw](https://github.com/openclaw/openclaw) — gateway multi-canal (estudo de padrões; ver §1.4)
- [BACKLOG-PHASE5.md](BACKLOG-PHASE5.md)

### Apêndice A — Template de sprint

```markdown
## Sprint X.Y — [Nome]
**Objetivo:** ...
### Escopo
- [ ] ...
### Pré-requisitos
- Fase X concluída
### Aceite
- [ ] ...
### Demo
1. ...
```

### Apêndice B — Prompt Fase 0

> Implemente a Fase 0 do `docs/STRATEGY.md` v1.2: `pyproject.toml`, `examples/async_repl.py`, `examples/tools_list.py`, `tests/integration/test_sdk_smoke.py`. AsyncSdkFacade pattern. `composer-2.5`. Sem código do hermes-agent.

### Glossário

| Termo | Definição |
|-------|-----------|
| `session_key` | `cli:{profile}:{workspace_hash}`, `telegram:{chat_id}:{workspace_hash}` — [ADR-004](decisions/ADR-004-session-key-workspace.md) |
| `session id` | UUID nosso; UX de `/resume` |
| `agent_id` | ID Cursor; interno |
| `SessionAgentPool` | 1 agent por session_key + lock |
| `tool_profile` | MVP: `coding` \| `messaging` — [ADR-014](decisions/ADR-014-tool-profiles-mvp.md) |

---

*Changelog: v1.2 — ADRs, PRDs, gateway-security, contrato facade; v1.1 — decisões de sessão, async-first, Fase 2b, pool, deploy, memória v1; Fase 5 extraída para BACKLOG-PHASE5.md.*
