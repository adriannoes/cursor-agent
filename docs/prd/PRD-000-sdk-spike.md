---
id: PRD-000
title: SDK spike — validação Fase 0
status: draft
phase: 0
depends_on: []
adrs:
  - ADR-005
  - ADR-017
  - ADR-022
  - ADR-026
related:
  - path: ../STRATEGY.md
    section: "7"
  - path: ../contracts/async-sdk-facade.md
    role: see-also
---

# PRD-000 — SDK spike (Fase 0)

## 1. Introdução / Visão geral

Antes de construir a arquitetura do **cursor-agent** (facade, sessões, CLI), precisamos validar que o ambiente Cursor Python SDK funciona de ponta a ponta neste repositório. Este spike confirma autenticação, bridge async, inventário de tools disponíveis na conta e o caminho async que a Fase 1 usará como base.

**Problema:** sem evidência local de que `cursor-sdk`, `AsyncClient.launch_bridge` e Composer 2.5 respondem corretamente, qualquer arquitetura construída em cima do SDK pode falhar tarde e de forma cara.

**Objetivo:** entregar exemplos executáveis, smoke test de integração e snapshot de tools — sem SessionStore, facade formal ou CLI instalável.

Contexto de fase: [STRATEGY.md §7](../STRATEGY.md#7-fase-0-spike).

## 2. Objetivos

1. Configurar `pyproject.toml` com dependências pinadas e markers de teste conforme [ADR-017](../decisions/ADR-017-sdk-version-pin.md) e [ADR-005](../decisions/ADR-005-testing-strategy.md).
2. Demonstrar conversa async com Composer 2.5, incluindo cold start documentado e segundo turn com contexto preservado.
3. Gerar inventário de tools em `docs/sdk-tools-snapshot.txt` como baseline da conta.
4. Provar que `CURSOR_API_KEY` + bridge funcionam via teste de integração com skip automático quando a key não está presente.
5. Deixar o repositório pronto para iniciar [PRD-001](PRD-001-facade.md) (facade async).

## 3. User Stories

| ID | História |
|----|----------|
| US-1 | Como **desenvolvedor**, quero rodar um exemplo async mínimo para confirmar que o SDK responde no meu workspace. |
| US-2 | Como **desenvolvedor**, quero um smoke test marcado `@integration` para validar CI/nightly sem bloquear PRs sem API key. |
| US-3 | Como **arquiteto**, quero um snapshot das tools expostas pelo SDK para planejar perfis e hooks nas fases seguintes. |
| US-4 | Como **desenvolvedor**, quero ver cold start documentado para calibrar expectativas de latência do REPL. |

## 4. Requisitos funcionais

**FR-1.** O repositório deve ter `pyproject.toml` com `cursor-sdk` em pin exato (`==X.Y.Z`), dev deps `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `[tool.pytest.ini_options]` com marker `integration` e `asyncio_mode = "auto"`, e seções `[tool.ruff]`, `[tool.mypy]`, `[tool.coverage.run]` conforme [ADR-026](../decisions/ADR-026-quality-tooling.md).

**FR-2.** Deve existir `examples/async_repl.py` usando `AsyncClient.launch_bridge`, modelo Composer 2.5, com comentário documentando cold start medido.

**FR-3.** O exemplo async deve suportar pelo menos dois turns na mesma sessão, demonstrando que o contexto é mantido.

**FR-4.** Deve existir `examples/tools_list.py` (ou equivalente) que introspeciona tools do SDK e cujo output é salvo em `docs/sdk-tools-snapshot.txt`.

**FR-5.** Deve existir `tests/integration/test_sdk_smoke.py` marcado `@pytest.mark.integration` que valida bridge + turn básico; deve fazer **skip** quando `CURSOR_API_KEY` não estiver definida.

**FR-6.** O smoke test deve cobrir pelo menos um turn que acione tool nativa (ex.: `grep` ou leitura de arquivo).

**FR-7.** Documentação inline nos exemplos deve registrar decisão **local-first** para CLI/gateway (cloud reservado para batch), alinhada a [STRATEGY.md §7](../STRATEGY.md#7-fase-0-spike).

## 5. Não-objetivos (fora de escopo)

- `AsyncSdkFacade`, `SessionStore`, `SessionAgentPool` — ver Fase 1 ([PRD-001](PRD-001-facade.md), [PRD-002](PRD-002-session-store.md)).
- CLI instalável `cursor-agent` — ver [PRD-003](PRD-003-cli-repl.md).
- Gateway Telegram, memória, slash commands além do mínimo nos exemplos.
- Nightly de integração (`pytest -m integration` com secret) — workflow separado após o spike; o **workflow mínimo de PR** está no escopo (DoD §10, [ADR-026](../decisions/ADR-026-quality-tooling.md)).
- Empacotamento PyPI — ver [ADR-019](../decisions/ADR-019-packaging-license.md) na Fase 1.

## 6. Considerações de design

Não aplicável — spike técnico sem UI. Os exemplos devem ser legíveis em terminal (stdout simples, sem Rich obrigatório nesta fase).

## 7. Considerações técnicas

| Tópico | Referência |
|--------|------------|
| Pin de versão do SDK | [ADR-017](../decisions/ADR-017-sdk-version-pin.md) |
| Pirâmide de testes (unit / integration / e2e) | [ADR-005](../decisions/ADR-005-testing-strategy.md) |
| Gate de qualidade (format, mypy, cov) | [ADR-026](../decisions/ADR-026-quality-tooling.md) |
| Contrato futuro da facade (somente leitura nesta fase) | [contracts/async-sdk-facade.md](../contracts/async-sdk-facade.md) |
| Roadmap Fase 0 | [STRATEGY.md §7](../STRATEGY.md#7-fase-0-spike) |

**Stack:** Python 3.11+, `uv` para deps (conforme `pyproject.toml` do repo), `cursor-sdk`, `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`.

**Variável de ambiente:** `CURSOR_API_KEY` obrigatória apenas para testes/exemplos de integração.

## 8. Métricas de sucesso

| Métrica | Critério de aceite |
|---------|-------------------|
| Autenticação | Exemplos e smoke passam com API key válida |
| Bridge async | `AsyncClient.launch_bridge` inicializa sem erro |
| Contexto multi-turn | Segundo turn referencia conteúdo do primeiro |
| Inventário | `docs/sdk-tools-snapshot.txt` existe e é versionado |
| CI local / PR | Gate canônico [ADR-026](../decisions/ADR-026-quality-tooling.md) passa sem API key |
| Integração | `pytest tests/integration/test_sdk_smoke.py -m integration` passa com key |

## 9. Perguntas em aberto

Nenhuma — decisões de pin, testes e local-first estão em [ADR-017](../decisions/ADR-017-sdk-version-pin.md) e [ADR-005](../decisions/ADR-005-testing-strategy.md).

## 10. Tarefas de implementação

### Definition of Done

- [ ] API key funciona; bridge OK
- [ ] Inventário de tools em `docs/sdk-tools-snapshot.txt`
- [ ] Caminho async documentado nos exemplos
- [ ] `.github/workflows/ci.yml` com gate canônico ([ADR-026](../decisions/ADR-026-quality-tooling.md))

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T1 | pyproject.toml + deps + tooling | 3h | — |
| T2 | examples/async_repl.py | 4h | T1 |
| T3 | examples/tools_list.py | 2h | T1 |
| T4 | test_sdk_smoke.py | 3h | T2 |
| T5 | sdk-tools-snapshot.txt | 1h | T3 |

### T1 — pyproject.toml

- [ ] T1.1 `cursor-sdk` pin exato ([ADR-017](../decisions/ADR-017-sdk-version-pin.md))
- [ ] T1.2 `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`
- [ ] T1.3 `[tool.pytest.ini_options]` markers integration
- [ ] T1.4 `[tool.ruff]`, `[tool.mypy]`, `[tool.coverage]` + CI workflow

### T2 — async_repl

- [ ] T2.1 `AsyncClient.launch_bridge`
- [ ] T2.2 Composer 2.5, cold start comentado
- [ ] T2.3 Segundo turn com contexto

### T4 — smoke test

- [ ] T4.1 `@pytest.mark.integration`
- [ ] T4.2 skip sem `CURSOR_API_KEY`

### Demo

1. `pytest tests/integration/test_sdk_smoke.py -m integration` — valida integração com API key.
2. `python examples/async_repl.py` — demonstra REPL async manual.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR-1 | `tests/test_pyproject_config.py` — marker `integration` e `asyncio_mode` | `pytest tests/test_pyproject_config.py -v` |
| FR-5, FR-6 | `tests/integration/test_sdk_smoke.py` — skip sem key, bridge + tool nativa | `pytest tests/integration/test_sdk_smoke.py -m integration -v` |
| FR-3 | Teste opcional de contrato async (ou validação manual documentada no exemplo) | `python examples/async_repl.py` (após smoke verde) |

Ordem sugerida: FR-1 (config) → esqueleto smoke (falha) → `async_repl` → smoke verde → `tools_list` + snapshot.

### Retroalimentação

**Após concluir PRD-000:** revisar e atualizar [PRD-001](PRD-001-facade.md) (§7, §9, §11) antes de iniciar a facade.

**Aprendizados a registrar:**

- [ ] Versão pinada real do `cursor-sdk` e breaking changes observados
- [ ] Cold start medido (segundos) para calibrar PRD-003 REPL
- [ ] Tools disponíveis no snapshot vs. expectativa de perfis (PRD-005)
- [ ] Comportamento multi-turn e limites de contexto
- [ ] Quirks de `launch_bridge` / auth relevantes para `AsyncSdkFacade`
