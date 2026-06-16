---
id: ADR-023
title: Harness para agentes de longa duração
status: accepted
date: 2026-06-13
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [process, agents, planning, quality]
related:
  - path: ../STRATEGY.md
    section: "14.6"
    role: see-also
  - path: ../DECISIONS.md
    role: index
  - path: ADR-022-tdd-prd-feedback-loop.md
    role: see-also
  - path: ../../engineering/tasks/README.md
    role: implements
  - path: ../../AGENTS.md
    role: see-also
  - path: ../../.cursor/commands/generate-tasks.md
    role: spec
  - path: ../../.cursor/commands/development.md
    role: spec
  - path: ../../.cursor/commands/code-review.md
    role: spec
  - path: ../../.cursor/rules/code-review.mdc
    role: spec
  - path: ADR-026-quality-tooling.md
    role: see-also
---

# ADR-023: Harness para agentes de longa duração

## Contexto

O projeto será desenvolvido principalmente por **agentes de longa duração** no Cursor ([long-running agents](https://cursor.com/blog/long-running-agents)). Esse modelo exige:

1. **Planejamento antes da execução** — propor plano e obter aprovação (LGTM) antes de codar.
2. **Follow-through** — checkpoints e listas de tarefas rastreáveis; não parar em implementação parcial.
3. **Código production-ready** — TDD, lint e testes verdes antes de marcar progresso.

[ADR-022](ADR-022-tdd-prd-feedback-loop.md) cobre TDD e retro entre PRDs, mas não formaliza o gate de planejamento nem o índice central de tasks exigido por sessões longas.

## Decisão

### 1. Índice mestre de tasks obrigatório

Todo plano de execução de um PRD deve ter arquivo em `engineering/tasks/` com convenção `tasks-PRD-{NNN}-{slug}.md`, indexado em [engineering/tasks/README.md](../../engineering/tasks/README.md).

Agentes devem **ler ou criar** esse arquivo no início de cada sessão de PRD, antes de implementar.

### 2. Gate LGTM (planejamento)

Antes de escrever código de produção em uma sessão:

1. Propor **parent tasks** (via `/generate-tasks` fase 1) ou resumir as **próximas sub-tasks** pendentes.
2. **Aguardar LGTM** explícito do usuário (ou aprovação equivalente no fluxo long-running).
3. Só então gerar sub-tasks detalhadas (fase 2) e/ou implementar.

Exceção: sub-tasks já aprovadas em sessão anterior podem continuar sem novo LGTM, desde que o escopo não tenha mudado.

### 3. Checkpoints de qualidade

Ao concluir cada sub-task, rodar o **gate canônico de qualidade** ([ADR-026](ADR-026-quality-tooling.md)) quando `src/`/`tests/` existirem:

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
```

- Marcar `[x]` no arquivo de tasks.
- Atualizar seção **Relevant Files** do arquivo de tasks.

Ao concluir o DoD de um PRD:

- Executar retro [ADR-022](ADR-022-tdd-prd-feedback-loop.md) no PRD-(N+1).
- Executar **`/code-review`** ([.cursor/commands/code-review.md](../../.cursor/commands/code-review.md)) com gates em [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc).

### 4. Modos de execução (development.md)

| Modo | Quando | Comportamento |
|------|--------|---------------|
| **Guiado** | Usuário presente, uma sub-task por vez | Pausar após cada sub-task; aguardar "yes" / "y" |
| **Long-running** | Sessão autônoma horas/dias | LGTM no plano; executar sub-tasks em sequência com o gate canônico de qualidade ([ADR-026](ADR-026-quality-tooling.md)) em cada checkpoint; reportar progresso na tabela do índice |

Ambos os modos respeitam TDD ([ADR-022](ADR-022-tdd-prd-feedback-loop.md)) e o índice de tasks.

## Opções consideradas

### Opção A — Harness com índice + LGTM + checkpoints (escolhida)

| Prós | Contras |
|------|---------|
| Alinha com blog Cursor long-running | Exige disciplina na manutenção do índice |
| Reduz deriva de escopo em sessões longas | LGTM pode atrasar início se usuário ausente |
| Complementa ADR-022 sem duplicar TDD | Dois modos em development.md aumentam documentação |

### Opção B — Apenas ADR-022, sem ADR dedicado

| Prós | Contras |
|------|---------|
| Menos ADRs | Gate de planejamento não explícito para agentes |
| | Índice de tasks não obrigatório |

### Opção C — LGTM em toda sub-task

| Prós | Contras |
|------|---------|
| Controle máximo | Inviável para sessões de horas/dias |
| | Contradiz princípio de follow-through autônomo |

## Consequências

### Positivas

- Agentes encontram sempre o plano atual em `engineering/tasks/README.md`.
- Planejamento e código desacoplados: LGTM no plano, execução autônoma nas sub-tasks.
- Code review formalizado antes de fechar PRD.

### Negativas

- Índice de tasks precisa de manutenção manual ao criar novos arquivos.
- Score de prontidão do repo permanece **Partial** até scaffold Python e CI ([engineering/tasks/README.md](../../engineering/tasks/README.md#prontidão-para-desenvolvimento-autônomo)).

## Referências

- [Cursor — Long-running agents](https://cursor.com/blog/long-running-agents)
- [engineering/tasks/README.md](../../engineering/tasks/README.md)
- [ADR-022 — TDD e retro entre PRDs](ADR-022-tdd-prd-feedback-loop.md)
- [ADR-026 — Ferramentas de qualidade](ADR-026-quality-tooling.md)
- [.cursor/commands/generate-tasks.md](../../.cursor/commands/generate-tasks.md)
- [.cursor/commands/development.md](../../.cursor/commands/development.md)
- [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md)
- [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc)
