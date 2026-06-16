---
id: ADR-026
title: Ferramentas de qualidade — ruff format, mypy strict, pytest-cov
status: accepted
date: 2026-06-15
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [quality, ci, lint, typing, coverage, phase-0]
related:
  - path: ADR-005-testing-strategy.md
    role: extends
  - path: ../STRATEGY.md
    section: "14.5"
    role: implements
  - path: ../DECISIONS.md
    role: index
  - path: ../prd/PRD-000-sdk-spike.md
    role: implements
  - path: ../../.cursor/rules/code-review.mdc
    role: spec
  - path: ../../.cursor/commands/code-review.md
    role: spec
  - path: ADR-023-long-running-agent-harness.md
    role: see-also
---

# ADR-026: Ferramentas de qualidade — ruff format, mypy strict, pytest-cov

## Contexto

[ADR-005](ADR-005-testing-strategy.md) define `ruff` e `pytest`, mas não formatter, type-checker estrito nem threshold de cobertura. Gates divergentes entre STRATEGY, code-review e checkpoints de agente geram falsos positivos de “pronto para merge”.

## Decisão

### 1. Stack de qualidade (Fase 0+)

| Ferramenta | Papel | Notas |
|------------|-------|-------|
| `ruff check` | Linter | `src/`, `tests/` |
| `ruff format` | Formatter | **Sem black** — único formatter |
| `mypy --strict` | Type-checker | Escopo `src/` |
| `pytest-cov` | Cobertura | `--cov-fail-under=85` em PR |

### 2. Gate único de PR (comando canônico)

Rodar na raiz do repositório:

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
```

Este bloco deve aparecer **identicamente** em [STRATEGY §14.5](../STRATEGY.md#145-verificação-global), [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc), [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md), [.cursor/commands/development.md](../../.cursor/commands/development.md), [engineering/templates/task-template.md](../../engineering/templates/task-template.md) e [ADR-023](ADR-023-long-running-agent-harness.md).

Integração (`pytest -m integration`) permanece nightly ou `workflow_dispatch` com `CURSOR_API_KEY` — fora do gate de PR.

### 3. `pyproject.toml` (seções obrigatórias)

```toml
[tool.ruff]
line-length = 88
target-version = "py311"

[tool.ruff.format]
# ruff format — sem black

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["cursor_agent"]

[tool.coverage.run]
source = ["cursor_agent"]
branch = true

[tool.coverage.report]
fail_under = 85
show_missing = true
```

Dev dependencies: `pytest-cov`, `mypy` (além de `pytest`, `pytest-asyncio`, `ruff`).

## Opções consideradas

### Opção A — ruff format + mypy strict + cov 85% (escolhida)

| Prós | Contras |
|------|---------|
| Um comando reproduzível; alinhado a agentes | Threshold 85% exige disciplina em Fase 1 |

### Opção B — black + pyright

| Prós | Contras |
|------|---------|
| Ecossistema comum | Duplica formatter; pyright ≠ mypy no repo |

## Consequências

### Positivas

- CI mínima do PRD-000 e reviews humanos/agentes usam o mesmo gate.
- Tipos explícitos em `src/` validados antes do merge.

### Negativas

- Fase 0 com pouco código em `src/` pode exigir `# pragma: no cover` pontual até Fase 1.

## Referências

- [ADR-005 — Pirâmide de testes](ADR-005-testing-strategy.md)
- [ADR-023 — Harness long-running](ADR-023-long-running-agent-harness.md)
- [STRATEGY.md §14.5](../STRATEGY.md#145-verificação-global)
