# Architecture Decision Records (ADRs)

> Índice central de decisões do **cursor-agent**. Cada ADR usa YAML frontmatter para navegação entre documentos.

| Campo | Valor |
|-------|-------|
| Versão | **1.3** (2026-06-15) |
| Formato | [MADR](https://adr.github.io/madr/) simplificado + frontmatter |
| Status | `accepted` \| `deprecated` \| `superseded` |

---

## Como ler

1. **Frontmatter** — cada ADR em `decisions/` tem `id`, `related[]` com paths e papéis.
2. **Campo `section`** — referência a uma seção do documento linkado (ex.: `"8"` → STRATEGY §8, `"9.1"` → subseção). Usado para navegação precisa sem âncoras frágeis.
3. **Campo `role`** — papel da relação entre documentos:

| `role` | Significado |
|--------|-------------|
| `implements` | Este ADR/PRD implementa o documento referenciado |
| `see-also` | Leitura complementar; sem dependência de implementação |
| `spec` | Especificação técnica ou threat model que o ADR formaliza |
| `decided-by` | Decisão arquitetural que governa o documento |
| `extends` | Este ADR estende/complementa o documento referenciado sem o substituir |
| `index` | Índice ou catálogo (ex.: DECISIONS.md) |

4. **Opções rejeitadas** — documentadas com prós/contras para revisão futura.
5. **STRATEGY.md** — visão e fases; ADRs são a fonte de verdade para *como* implementar.

---

## Índice por fase

### Segurança e policy

| ID | Título | Fase | Status |
|----|--------|------|--------|
| [ADR-001](decisions/ADR-001-messaging-security.md) | Segurança do perfil `messaging` | 2b | accepted |
| [ADR-014](decisions/ADR-014-tool-profiles-mvp.md) | Perfis `coding` + `messaging` no MVP | 2b | accepted |
| [ADR-025](decisions/ADR-025-secrets-policy.md) | Política de secrets e redaction | 0+ | accepted |

### Core (facade, sessões, config)

| ID | Título | Fase | Status |
|----|--------|------|--------|
| [ADR-002](decisions/ADR-002-async-sdk-facade.md) | `Protocol` + `FakeSdkFacade` | 1 | accepted |
| [ADR-003](decisions/ADR-003-cross-runtime-resume.md) | Proibir resume cross-runtime | 1 | accepted |
| [ADR-004](decisions/ADR-004-session-key-workspace.md) | `session_key` com `workspace_hash` | 1 | accepted |
| [ADR-007](decisions/ADR-007-config-loader.md) | pydantic-settings + precedência | 1 | accepted |
| [ADR-009](decisions/ADR-009-session-titles.md) | Títulos de sessão (truncar 1ª msg) | 1 | accepted |
| [ADR-013](decisions/ADR-013-slash-commands-skills.md) | `/new` unificado + namespace skills | 2 | accepted |
| [ADR-024](decisions/ADR-024-error-taxonomy-retry.md) | Taxonomia `CursorAgentError` + retry | 1+ | accepted |

### Gateway e Telegram

| ID | Título | Fase | Status |
|----|--------|------|--------|
| [ADR-006](decisions/ADR-006-telegram-library.md) | aiogram 3.x | 3 | accepted |
| [ADR-008](decisions/ADR-008-agent-busy-gateway.md) | `AgentBusyError` → rejeitar com mensagem | 3 | accepted |
| [ADR-012](decisions/ADR-012-telegram-chunking.md) | Chunking 4096 + typing indicator | 3 | accepted |
| [ADR-021](decisions/ADR-021-graceful-shutdown.md) | Shutdown SIGTERM no gateway | 3 | accepted |

### Memória, compress, extensões

| ID | Título | Fase | Status |
|----|--------|------|--------|
| [ADR-010](decisions/ADR-010-memory-v1.md) | Injeção memória v1 + flag `memory_injected` | 4 | accepted |
| [ADR-011](decisions/ADR-011-compress-flow.md) | `/compress` saga + prompt versionado | 2 | accepted |
| [ADR-016](decisions/ADR-016-honcho-memory-path.md) | Caminho v1 → Honcho MCP | 5 | accepted |

### Processo

| ID | Título | Fase | Status |
|----|--------|------|--------|
| [ADR-022](decisions/ADR-022-tdd-prd-feedback-loop.md) | TDD obrigatório + retroalimentação entre PRDs | 0+ | accepted |
| [ADR-023](decisions/ADR-023-long-running-agent-harness.md) | Harness para agentes de longa duração | 0+ | accepted |

### Ops, testes, packaging

| ID | Título | Fase | Status |
|----|--------|------|--------|
| [ADR-005](decisions/ADR-005-testing-strategy.md) | Pirâmide de testes + CI | 0+ | accepted |
| [ADR-017](decisions/ADR-017-sdk-version-pin.md) | Pin exato `cursor-sdk` + Dependabot | 0+ | accepted |
| [ADR-018](decisions/ADR-018-observability-logs.md) | Logs JSON schema v1 | 1+ | accepted |
| [ADR-019](decisions/ADR-019-packaging-license.md) | MIT + PyPI + semver `0.x` | 1+ | accepted |
| [ADR-020](decisions/ADR-020-backlog-promotion.md) | Critérios promoção Fase 5 → PRD | 5 | accepted |
| [ADR-015](decisions/ADR-015-tui-stretch-goal.md) | TUI como stretch goal | 5 | accepted |
| [ADR-026](decisions/ADR-026-quality-tooling.md) | ruff format + mypy strict + pytest-cov 85% | 0+ | accepted |

---

## Documentos relacionados

| Documento | Papel |
|-----------|-------|
| [STRATEGY.md](STRATEGY.md) | Visão, fases 0–4, roadmap |
| [BACKLOG-PHASE5.md](BACKLOG-PHASE5.md) | Catálogo pós-MVP |
| [gateway-security.md](gateway-security.md) | Threat model messaging (implementa ADR-001) |
| [contracts/async-sdk-facade.md](contracts/async-sdk-facade.md) | Contrato técnico (implementa ADR-002) |
| [prd/](prd/) | PRDs executáveis com tasks |
| [../engineering/tasks/README.md](../engineering/tasks/README.md) | Índice mestre de planos de tarefas |
| [prompts/compress.txt](prompts/compress.txt) | Prompt `/compress` (ADR-011) |

---

## Template para novos ADRs

Copiar `decisions/_template.md` ao registrar decisões futuras.

---

*Changelog: v1.3 — ADR-024 erros/retry, ADR-025 secrets, ADR-026 quality tooling (2026-06-15). v1.2 — ADR-023 harness long-running agents (2026-06-13). v1.1 — ADR-022 processo TDD + retro PRD (2026-06-13). v1.0 — ADRs iniciais D1–D21 da revisão de planejamento 2026-06-12 (26 ADRs no índice).*
