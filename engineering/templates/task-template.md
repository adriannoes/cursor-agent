# Tarefas — [PRD-ID] [Título curto]

> **PRD:** [PRD-XXX-nome.md](../../docs/prd/PRD-XXX-nome.md)  
> **ADRs:** [ADR-XXX](../../docs/decisions/ADR-XXX-nome.md) (breve descrição), …  
> **Escopo deste documento:** [Fase N — resumo do escopo; o que fica fora].  
> **Status:** [Rascunho | Fase 1 completa — parent tasks | Fase 2 completa — sub-tasks prontas para implementação]

## Relevant Files

- `path/to/file.py` — breve descrição do propósito (FR-X, TX).
- `tests/path/to/test_file.py` — testes para `file.py` (FR-X, TX).
- `docs/artefato.txt` — artefato versionado gerado por script (se aplicável).

### Notes

- **TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)):** Em sub-tasks de implementação, preferir **Verify** com pytest **antes** do código de produção quando aplicável.
- Testes de integração em `tests/integration/` conforme [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md).
- PRs locais sem API key — gate canônico de qualidade ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

- Com API key (quando aplicável):

  ```bash
  export CURSOR_API_KEY="sua-chave"
  pytest tests/integration/ -m integration -v
  ```

- Stack e convenções: [STRATEGY.md](../../docs/STRATEGY.md), [DECISIONS.md](../../docs/DECISIONS.md).

## Tasks

- [ ] **1.0 [Título da parent task]** — PRD T1 (T1.1–T1.N)

  **Trigger / entry point:** [O que inicia este trabalho].  
  **Enables:** [O que esta tarefa desbloqueia].  
  **Depends on:** [Tarefas ou pré-requisitos; ou "Nenhuma"].

  **Acceptance criteria:**
  - [Critério verificável 1]
  - [Critério verificável 2]

  - [ ] 1.1 [Verbo] [item específico]
    - **File**: `path/to/file.py` (create new | modify existing)
    - **What**: [Descrição detalhada do que criar ou modificar]
    - **Why**: [FR-X / contexto — por que é necessário]
    - **Pattern**: [Referência a ADR, PRD, código existente ou STRATEGY.md]
    - **Verify**: [Comando pytest ou observação — TDD red→green quando aplicável]

  - [ ] 1.2 [Verbo] [item específico]
    - **File**: `path/to/file.py` (create new | modify existing)
    - **What**: […]
    - **Why**: […]
    - **Pattern**: […]
    - **Verify**: […]

- [ ] **2.0 [Título da parent task]** — PRD T2

  **Trigger / entry point:** […]  
  **Enables:** […]  
  **Depends on:** [Tarefa 1.0 ou outra].

  **Acceptance criteria:**
  - [Critério verificável]

  - [ ] 2.1 [Verbo] [item específico]
    - **File**: `path/to/file.py` (create new | modify existing)
    - **What**: […]
    - **Why**: […]
    - **Pattern**: […]
    - **Verify**: […]
    - **Integration** (opcional): [Como o output é consumido por outra tarefa]

- [ ] **N.0 Validar Definition of Done e handoff**

  **Trigger / entry point:** Revisão final antes de iniciar [PRD-(N+1)](../../docs/prd/PRD-XXX.md).  
  **Enables:** [Próxima fase / PRD seguinte].  
  **Depends on:** Tarefas anteriores concluídas.

  **Acceptance criteria:**
  - Definition of Done do PRD atendida (ver PRD §10).
  - **Retroalimentação:** [PRD-(N+1)](../../docs/prd/PRD-XXX.md) §7, §9 e §11 atualizados ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)).

  - [ ] N.1 Executar gate de qualidade local
    - **File**: — (verificação manual / CI local)
    - **What**: Rodar o gate canônico ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):

      ```bash
      ruff check src tests
      ruff format --check src tests
      mypy --strict src
      pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
      ```

    - **Why**: PRs sem API key não devem quebrar ([ADR-005](../../docs/decisions/ADR-005-testing-strategy.md)).
    - **Pattern**: Pipeline PR em [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: Todos os comandos terminam com exit code 0.

  - [ ] N.2 Revisar PRD-(N+1) com aprendizados (retroalimentação)
    - **File**: [PRD-(N+1).md](../../docs/prd/PRD-XXX.md) (modify existing)
    - **What**: Atualizar §7, §9 e §11 com evidência desta fase.
    - **Why**: Gate obrigatório [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md).
    - **Pattern**: Checklist em PRD §11.
    - **Verify**: Bullets de aprendizado preenchidos ou N/A com justificativa.

---

## Mapeamento PRD §10 → tarefas

| PRD | Sub-tarefa neste documento |
|-----|---------------------------|
| T1.1 | 1.1 |
| T1.2 | 1.2 |
| … | … |
