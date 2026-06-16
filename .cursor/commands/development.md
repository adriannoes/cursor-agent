# Task List Management

Guidelines for managing task lists in markdown files to track progress on completing a PRD.

Índice mestre: [engineering/tasks/README.md](../../engineering/tasks/README.md). Harness long-running: [ADR-023](../../docs/decisions/ADR-023-long-running-agent-harness.md).

## Modos de execução

Escolha o modo conforme o contexto da sessão. As regras de pausa **não** se aplicam igualmente nos dois modos.

### Modo guiado (usuário presente)

Uma sub-task por vez. Após cada sub-task concluída:

1. Marcar `[x]` na sub-task (e no parent se todas as sub-tasks estiverem feitas).
2. Atualizar **Relevant Files**.
3. **Parar e aguardar** permissão explícita do usuário (“yes”, “y”, “continue”) antes da próxima sub-task.

### Modo long-running ([Cursor blog](https://cursor.com/blog/long-running-agents))

Para sessões autônomas de horas ou dias ([ADR-023](../../docs/decisions/ADR-023-long-running-agent-harness.md)):

1. **Planejar primeiro** — propor parent tasks ou próximas sub-tasks; aguardar **LGTM** antes de codar.
2. **Follow-through** — após LGTM do plano, executar sub-tasks em sequência **sem pausar** para aprovação entre cada uma.
3. **Checkpoints** — após cada sub-task: marcar `[x]`, rodar o gate de qualidade ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
```

Atualizar **Relevant Files**; reportar progresso ao usuário nos checkpoints, mas **não** parar a execução.
4. **Fechar PRD** — executar **`/code-review`** ([code-review.md](./code-review.md) + gates em [code-review.mdc](../rules/code-review.mdc)); retro no PRD-(N+1) ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)) conforme veredito do review.

## Task Implementation

- **Modo guiado:** do **NOT** start the next sub-task until the user gives explicit permission.
- **Modo long-running:** continue through sub-tasks after **LGTM** on the plan; use checkpoints for status, not for blocking on user input between sub-tasks.
- **Completion protocol (ambos os modos):**
  1. When you finish a **sub-task**, immediately mark it as completed by changing `[ ]` to `[x]`.
  2. If **all** subtasks underneath a parent task are now `[x]`, also mark the **parent task** as completed.

## Task List Maintenance

1. **Update the task list as you work:**
   - Mark tasks and subtasks as completed (`[x]`) per the protocol above.
   - Add new tasks as they emerge.

2. **Maintain the “Relevant Files” section:**
   - List every file created or modified.
   - Give each file a one-line description of its purpose.

## AI Instructions

When working with task lists, the AI must:

1. Regularly update the task list file after finishing any significant work.
2. Follow the completion protocol:
   - Mark each finished **sub-task** `[x]`.
   - Mark the **parent task** `[x]` once **all** its subtasks are `[x]`.
3. Add newly discovered tasks.
4. Keep “Relevant Files” accurate and up to date.
5. Before starting work, check which sub-task is next and confirm the execution mode (guiado vs long-running).
6. **Modo guiado only:** after implementing a sub-task, update the file and pause for user approval.
7. **Modo long-running:** after implementing a sub-task, update the file and proceed to the next sub-task (report at checkpoints).
