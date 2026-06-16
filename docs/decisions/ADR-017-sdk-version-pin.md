---
id: ADR-017
title: Pin exato cursor-sdk e Dependabot
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [dependencies, sdk, ops]
related:
  - path: ../STRATEGY.md
    section: "14.3"
  - path: ADR-005-testing-strategy.md
    role: see-also
  - path: ADR-026-quality-tooling.md
    role: see-also
  - path: ../prd/PRD-000-sdk-spike.md
    role: implements
---

# ADR-017: Pin exato `cursor-sdk` + Dependabot

## Contexto

Risco de breaking changes no SDK ([STRATEGY §14.3](../STRATEGY.md#143-riscos-principais)). Política de upgrade ausente — tanto para `cursor-sdk` quanto para as demais dependências (dev tooling, libs de runtime). Sem lockfile versionado, builds locais e de CI não são reproduzíveis.

## Decisão

### `cursor-sdk` (pin exato)

1. **`pyproject.toml`:** `cursor-sdk==X.Y.Z` (pin exato).
2. **Demais dependências:** ranges compatíveis no `pyproject.toml` + **`uv.lock` versionado** para reprodutibilidade local e em CI.
3. **Dependabot** semanal para **todo o ecossistema** Python do repo (não apenas `cursor-sdk`), com PR automático.
4. **Merge** só se gate de PR ([ADR-026](ADR-026-quality-tooling.md)) passar; upgrades de `cursor-sdk` exigem adicionalmente `pytest -m integration` (nightly ou PR com label `run-integration`).
5. Facade ([ADR-002](ADR-002-async-sdk-facade.md)) isola superfície de mudança do SDK.

> **Ranges compatíveis** (`>=X.Y,<X+1` ou `~=X.Y`) para runtime e dev tooling (`pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`); pin exato é reservado a `cursor-sdk`. O `uv.lock` versionado fixa a resolução, enquanto o `pyproject.toml` mantém ranges legíveis — `uv sync` reproduz o mesmo ambiente em qualquer máquina e na CI.

## Opções consideradas

### Pin exato + Dependabot (escolhida)

| Prós | Contras |
|------|---------|
| Reproduzível; upgrades conscientes | Updates manuais de revisão |

### Range `>=X,<X+1` (rejeitada **para `cursor-sdk`**, adotada para as demais deps)

| Prós | Contras |
|------|---------|
| Patches automáticos | Pode quebrar em minor |

Para `cursor-sdk` o risco de quebra em minor justifica pin exato; para as demais deps o range + `uv.lock` equilibra reprodutibilidade e manutenção (ver Decisão §2 e §3).

### Sem pin (rejeitada)

| Prós | Contras |
|------|---------|
| Sempre latest | CI não reproduzível |

## Consequências

### Positivas

- Builds determinísticos (pin do SDK + `uv.lock` para o restante).
- Upgrades visíveis em PRs, com gate de qualidade ([ADR-026](ADR-026-quality-tooling.md)) em todo o ecossistema.

### Negativas

- Lag de dias/semanas em fixes do SDK até merge Dependabot.
- `uv.lock` precisa ser regenerado e commitado a cada mudança de deps.

## Referências

- [Cursor Python SDK](https://cursor.com/docs/sdk/python)
- [ADR-026 — Ferramentas de qualidade](ADR-026-quality-tooling.md)
- [uv — lockfile](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile)
- [Dependabot — package ecosystems](https://docs.github.com/en/code-security/dependabot)
