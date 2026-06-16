---
id: ADR-022
title: TDD obrigatório e retroalimentação entre PRDs
status: accepted
date: 2026-06-13
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [process, tdd, prd, quality]
related:
  - path: ../STRATEGY.md
    section: "14.6"
    role: see-also
  - path: ../DECISIONS.md
    role: index
  - path: ADR-005-testing-strategy.md
    role: see-also
  - path: ../prd/README.md
    section: "Fluxo de desenvolvimento"
    role: see-also
  - path: ../prd/PRD-000-sdk-spike.md
    section: "11"
    role: implements
  - path: ../../.cursor/commands/prd.md
    role: spec
  - path: ../../.cursor/commands/generate-tasks.md
    role: spec
  - path: ../../engineering/tasks/tasks-PRD-000-sdk-spike.md
    role: see-also
  - path: ADR-023-long-running-agent-harness.md
    role: see-also
---

# ADR-022: TDD obrigatório e retroalimentação entre PRDs

## Contexto

[ADR-005](ADR-005-testing-strategy.md) define a pirâmide de testes e CI, mas não obriga **test-first** nem um gate formal entre PRDs consecutivos. Na prática, implementações que começam sem teste falhando geram retrabalho quando o spike (PRD-000) revela quirks do SDK, timings de cold start ou dependências não previstas — informação que deveria alimentar o PRD seguinte **antes** de iniciá-lo.

O roadmap tem 11 PRDs sequenciais (000–010) com dependências explícitas. Sem retroalimentação documentada, PRD-(N+1) permanece desatualizado em relação ao que PRD-N aprendeu em código.

## Decisão

### 1. TDD obrigatório desde PRD-000

Para **cada requisito funcional (FR)** de um PRD:

1. Escrever teste que **falha** (pytest), espelhando `tests/` sobre `src/`.
2. Implementar o mínimo para o teste passar.
3. Refatorar mantendo a suíte verde.

Ordem preferida por FR: **Verify** (comando pytest) antes de código de produção nas tasks geradas por [generate-tasks.md](../../.cursor/commands/generate-tasks.md).

Integração (`@pytest.mark.integration`) segue [ADR-005](ADR-005-testing-strategy.md): skip sem `CURSOR_API_KEY`; TDD unitário com fakes tem prioridade em todo PR.

### 2. Gate "PRD retrospective" antes do PRD seguinte

Ao concluir o Definition of Done de **PRD-N**, **não** iniciar **PRD-(N+1)** até:

1. Revisar o PRD seguinte na cadeia de retroalimentação (ver [prd/README.md](../prd/README.md#fluxo-de-desenvolvimento)).
2. Atualizar §7 (considerações técnicas), §9 (perguntas em aberto) e §11 (aprendizados) do PRD alvo com: quirks do SDK, timings medidos, versões/deps, riscos novos, ajustes de estimativa.
3. Registrar na sub-task **5.x** da lista de tasks (ou equivalente DoD) do PRD-N.

Cadeia padrão: `PRD-000 → 001 → … → 010`. PRD-010 retroalimenta [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md) / promoções [ADR-020](ADR-020-backlog-promotion.md).

## Opções consideradas

### Opção A — TDD + retrospective gate (escolhida)

| Prós | Contras |
|------|---------|
| Feedback do spike chega ao PRD seguinte antes do código | Overhead de documentação por PRD |
| Regressões detectadas cedo; alinha com ADR-005 | Exige disciplina na geração de tasks |
| Cadeia 000→010 rastreável em §11 de cada PRD | Gate pode atrasar início se retro for negligenciada |

### Opção B — TDD recomendado, não obrigatório

| Prós | Contras |
|------|---------|
| Menos atrito no spike inicial | Testes escritos após implementação; mocks inadequados |
| Flexível para exploração | Quirks do SDK descobertos tarde em PRD-001+ |

### Opção C — Retrospective só em marcos de fase (0, 1, 2b, 3, 4)

| Prós | Contras |
|------|---------|
| Menos interrupções | PRD-002 e PRD-003 na mesma fase sem troca de aprendizado |
| Documentação concentrada | Gate distante do código que gerou o aprendizado |

### Opção D — Implementar primeiro, documentar depois (rejeitada)

| Prós | Contras |
|------|---------|
| Velocidade aparente imediata | PRD-(N+1) desatualizado; duplicação de investigação |
| Sem curva de TDD | Viola pirâmide de testes e dificulta CI determinístico |

## Consequências

### Positivas

- PRDs vivos: estimativas e riscos calibrados com evidência local.
- Tasks geradas já incluem passo **Verify** e sub-task de retro no parent 5.x.
- Continuidade com [ADR-005](ADR-005-testing-strategy.md) e §11 padronizado em todos os PRDs.

### Negativas

- Cada PRD ganha seção §11 a manter durante o desenvolvimento.
- Retrospective mal feita bloqueia o próximo PRD sem valor — exige revisão humana do checklist.

## Referências

- [STRATEGY.md §14.6](../STRATEGY.md#146-processo-de-desenvolvimento)
- [prd/README.md — Fluxo de desenvolvimento](../prd/README.md#fluxo-de-desenvolvimento)
- [ADR-005 — Pirâmide de testes](ADR-005-testing-strategy.md)
