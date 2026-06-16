---
id: ADR-005
title: Pirâmide de testes e CI
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [testing, ci, quality, phase-0]
related:
  - path: ../STRATEGY.md
    section: "14.5"
  - path: ../prd/PRD-000-sdk-spike.md
    role: implements
  - path: ADR-002-async-sdk-facade.md
    role: see-also
  - path: ADR-017-sdk-version-pin.md
    role: see-also
  - path: ADR-026-quality-tooling.md
    role: see-also
---

# ADR-005: Pirâmide de testes e CI

## Contexto

O plano original previa apenas `test_sdk_smoke.py` com skip sem API key. PRs precisam ser rápidos e determinísticos.

## Decisão

```text
unit/         → FakeSdkFacade, SessionStore, pool, commands (pytest + pytest-asyncio)
integration/  → test_sdk_smoke.py (marker integration; skip sem CURSOR_API_KEY)
e2e/          → manual ou nightly com secret
```

**Stack:** `pytest`, `pytest-asyncio` (asyncio_mode=auto), `pytest-mock`, `pytest-cov`, `ruff`, `mypy`.

**CI (GitHub Actions):**

- Todo PR roda o **gate canônico de qualidade** ([ADR-026](ADR-026-quality-tooling.md)):

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

- Nightly ou `workflow_dispatch`: `pytest -m integration` com `CURSOR_API_KEY`.

Formatter (`ruff format`), type-checker (`mypy --strict`) e limiar de cobertura (`--cov-fail-under=85`) são padronizados em [ADR-026](ADR-026-quality-tooling.md).

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = ["integration: requires CURSOR_API_KEY"]
asyncio_mode = "auto"
```

## Opções consideradas

### Opção A — Pirâmide com fake facade (escolhida)

| Prós | Contras |
|------|---------|
| PRs rápidos e determinísticos | Smoke real não roda em todo PR |
| Padrão maduro 2025–2026 | Setup inicial de fixtures |

### Opção B — Só integração com API key

| Prós | Contras |
|------|---------|
| Simples | CI caro, flaky, bloqueia forks |

### Opção C — VCR/cassettes de streams SDK

| Prós | Contras |
|------|---------|
| Replay offline | SDK evolui; cassettes quebram |

## Consequências

### Positivas

- Cobertura real de orquestração sem vendor lock-in em CI.
- Integração validada periodicamente.

### Negativas

- Regressões SDK-only podem passar até nightly falhar.

## Referências

- [STRATEGY.md §14.5](../STRATEGY.md#145-verificação-global)
- [ADR-026 — Ferramentas de qualidade](ADR-026-quality-tooling.md)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
