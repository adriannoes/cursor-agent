# AGENTS.md — Guia para agentes de IA

> **Ponto de entrada principal** para sessões de agente neste repositório. Leia este arquivo antes de implementar qualquer coisa.

---

## Start here

Ordem de leitura recomendada para uma **nova sessão de agente**:

1. **Este arquivo** (`AGENTS.md`) — orientação geral, mapa e convenções.
2. **[docs/STRATEGY.md](docs/STRATEGY.md)** — visão, arquitetura e roadmap (Fases 0–4).
3. **[docs/DECISIONS.md](docs/DECISIONS.md)** — ADRs aceitos; fonte de verdade para *como* implementar.
4. **[docs/prd/README.md](docs/prd/README.md)** — cadeia de PRDs e fluxo TDD + retro.
5. **PRD ativo** — hoje: [docs/prd/PRD-000-sdk-spike.md](docs/prd/PRD-000-sdk-spike.md).
6. **[engineering/tasks/README.md](engineering/tasks/README.md)** — índice mestre de planos de tarefas (tasks vivem separadas dos PRDs).
7. **Tasks do PRD ativo** — [engineering/tasks/tasks-PRD-000-sdk-spike.md](engineering/tasks/tasks-PRD-000-sdk-spike.md).
8. **[.cursor/rules/](.cursor/rules/)** — convenções de código, estilo e gates de code review para agentes.
9. **[.cursor/skills/](.cursor/skills/)** — playbooks de workflow (TDD, debug, verificação, worktrees, paralelismo).

Só depois disso: implementar seguindo o PRD, as tasks e os ADRs referenciados.

---

## O que é cursor-agent

O **cursor-agent** é um agente *clean-room* inspirado no **comportamento** do [Hermes Agent](https://github.com/NousResearch/hermes-agent) e em padrões de gateway do [OpenClaw](https://github.com/openclaw/openclaw), mas **não é** fork nem cópia desses codebases. Pode estudar **docs e codebases** de referência para entender como problemas foram resolvidos — **zero código copiado**; reimplementação com [Cursor Python SDK](https://cursor.com/docs/sdk/python) + **Composer 2.5**. Delega loop agentic, tools e inferência ao SDK, implementando apenas orquestração (sessões, config, concorrência), UX (CLI, slash commands, gateway) e policy (hooks, perfis, allowlists). Projetos relacionados do mesmo autor (ex.: shellclaw) são **separados** — ver [STRATEGY.md §1.4](docs/STRATEGY.md#14-relação-com-outros-projetos). Status atual: **planejamento / Fase 0** — ver [docs/STRATEGY.md](docs/STRATEGY.md).

---

## Mapa do repositório

```text
cursor-agent/
├── AGENTS.md                    ← você está aqui (índice para agentes)
├── README.md                    ← visão humana do projeto
├── .env.example                 ← variáveis de ambiente documentadas
│
├── docs/
│   ├── README.md                ← hub de documentação
│   ├── STRATEGY.md              ← estratégia, arquitetura, fases 0–4
│   ├── DECISIONS.md             ← índice de ADRs (26 decisões)
│   ├── BACKLOG-PHASE5.md        ← backlog pós-MVP (paridade Hermes)
│   ├── gateway-security.md      ← threat model do gateway de mensagens
│   ├── prd/                     ← PRDs executáveis (PRD-000 … PRD-010)
│   ├── decisions/               ← ADRs individuais (ADR-001 … ADR-023)
│   ├── contracts/               ← contratos técnicos (ex.: async-sdk-facade)
│   └── prompts/                 ← prompts reutilizáveis (ex.: compress.txt)
│
├── engineering/
│   └── tasks/
│       ├── README.md            ← índice mestre de planos de tarefas
│       └── tasks-PRD-*.md       ← listas de tarefas derivadas dos PRDs
│
└── .cursor/
    ├── commands/
    │   ├── prd.md                    ← template/comando para gerar PRDs
    │   ├── generate-tasks.md           ← template/comando para gerar tasks a partir de PRD
    │   ├── development.md              ← protocolo de execução de tasks (guiado ou long-running)
    │   ├── code-review.md              ← checklist de revisão antes de fechar PRD/PR
    │   ├── clarify-task.md             ← gate LGTM antes de codar (ADR-023)
    │   ├── run-all-tests-and-fix.md    ← recuperação de suíte de testes
    │   ├── security-audit.md           ← auditoria de segurança Python/SDK/gateway
    │   └── slop.md                     ← remover slop de IA no diff
    ├── skills/
    │   ├── test-driven-development/    ← TDD Red-Green-Refactor (ADR-022)
    │   ├── systematic-debugging/       ← root cause antes de fix
    │   ├── verification-before-completion/ ← evidência antes de claims
    │   ├── finishing-a-development-branch/ ← merge, PR ou cleanup
    │   ├── using-git-worktrees/        ← worktrees isolados (.worktrees/)
    │   └── dispatching-parallel-agents/ ← Task tool em paralelo
    └── rules/
        ├── agent-clean-code.mdc        ← código legível para agentes (grep, SRP, testes)
        ├── python-best-practices.mdc   ← Python 3.11+, pytest, ruff, uv, Pydantic v2
        ├── code-review.mdc             ← gates obrigatórios ao fechar PRD ou merge
        ├── secure-dev-python.mdc       ← segurança Python (secrets, subprocess, pickle)
        ├── secure-mcp-dev.mdc          ← MCP no perfil dev/coding
        └── secure-mcp-messaging.mdc    ← MCP/tool deny no perfil gateway
```

---

## Como trabalhar

### Fluxo obrigatório (ADR-022)

```text
PRD → generate-tasks → implementar (TDD) → DoD do PRD → /code-review → retro no PRD seguinte → próximo PRD
```

1. **Ler o PRD** ativo e os ADRs referenciados no frontmatter.
2. **Seguir as tasks** em `engineering/tasks/` — uma sub-task por vez quando o usuário pedir execução guiada (ver [.cursor/commands/development.md](.cursor/commands/development.md)).
3. **TDD:** para cada requisito funcional, escrever teste pytest **falhando** → implementar → verde.
4. **CI local sem API key:** `pytest -m "not integration" -v`
5. **Definition of Done:** critérios de §10 do PRD atendidos.
6. **Code review:** executar [`/code-review`](.cursor/commands/code-review.md) com gates em [.cursor/rules/code-review.mdc](.cursor/rules/code-review.mdc) — veredito **Aprovado** antes de encerrar o PRD.
7. **Retroalimentação:** antes de iniciar o PRD seguinte, atualizar §7, §9 e §11 do próximo PRD com aprendizados do código (ver [ADR-022](docs/decisions/ADR-022-tdd-prd-feedback-loop.md)).

### Comandos Cursor úteis

| Comando | Arquivo | Uso |
|---------|---------|-----|
| PRD | [.cursor/commands/prd.md](.cursor/commands/prd.md) | Gerar ou revisar PRDs |
| Generate tasks | [.cursor/commands/generate-tasks.md](.cursor/commands/generate-tasks.md) | Quebrar PRD em tasks executáveis |
| Development | [.cursor/commands/development.md](.cursor/commands/development.md) | Protocolo de marcação e progresso nas tasks |
| Clarify task | [.cursor/commands/clarify-task.md](.cursor/commands/clarify-task.md) | Desambiguar escopo e obter LGTM antes de codar |
| Run tests & fix | [.cursor/commands/run-all-tests-and-fix.md](.cursor/commands/run-all-tests-and-fix.md) | Executar suíte e corrigir falhas sistematicamente |
| Code review | [.cursor/commands/code-review.md](.cursor/commands/code-review.md) | Protocolo executável (`/code-review`) antes de fechar PRD ou merge |
| Security audit | [.cursor/commands/security-audit.md](.cursor/commands/security-audit.md) | Auditoria de secrets, subprocess, MCP e gateway |
| Code review (gates) | [.cursor/rules/code-review.mdc](.cursor/rules/code-review.mdc) | Gates obrigatórios da stack — aplicar com o comando acima |

### Skills de workflow

Adaptadas de [awesome-vibe-coding/cursor-claude-codex](https://github.com/adriannoes/awesome-vibe-coding/tree/main/cursor-claude-codex/skills) (obra/superpowers, MIT).

| Skill | Quando usar |
|-------|-------------|
| [test-driven-development](.cursor/skills/test-driven-development/SKILL.md) | Antes de escrever código de produção (ADR-022) |
| [systematic-debugging](.cursor/skills/systematic-debugging/SKILL.md) | Bug ou test failure — root cause antes de fix |
| [verification-before-completion](.cursor/skills/verification-before-completion/SKILL.md) | Antes de marcar task/PRD como concluído |
| [finishing-a-development-branch](.cursor/skills/finishing-a-development-branch/SKILL.md) | Merge, PR ou descarte de branch |
| [using-git-worktrees](.cursor/skills/using-git-worktrees/SKILL.md) | Isolamento paralelo em `.worktrees/` |
| [dispatching-parallel-agents](.cursor/skills/dispatching-parallel-agents/SKILL.md) | 2+ problemas independentes via Task tool |

---

## PRD atual / próximo passo

| Item | Caminho |
|------|---------|
| **PRD ativo** | [docs/prd/PRD-000-sdk-spike.md](docs/prd/PRD-000-sdk-spike.md) — spike de validação do SDK (Fase 0) |
| **Tasks** | [engineering/tasks/tasks-PRD-000-sdk-spike.md](engineering/tasks/tasks-PRD-000-sdk-spike.md) |
| **Próximo na cadeia** | [docs/prd/PRD-001-facade.md](docs/prd/PRD-001-facade.md) — AsyncSdkFacade (após retro do 000) |

Cadeia completa: [docs/prd/README.md](docs/prd/README.md).

---

## Convenções

| Conceito | Valor |
|----------|-------|
| Nome do projeto | `cursor-agent` |
| Pacote Python | `cursor_agent` |
| Diretório de config | `~/.cursor-agent` |
| Variáveis de ambiente | prefixo `CURSOR_AGENT__*` (ver também `CURSOR_API_KEY` no `.env.example`) |
| CLI (futuro) | `cursor-agent` |
| Gerenciador de deps | `uv` (conforme `pyproject.toml`) |
| Linter / formatter | `ruff` |
| Testes | `pytest` em `./tests` |
| Idioma dos docs | português brasileiro (código e comentários em inglês) |

---

## O que NÃO fazer

- **Não copiar código** de projetos de referência (Hermes, OpenClaw, etc.) — pode estudar docs **e** codebases para padrões, mas reimplementar em `cursor_agent` (clean-room; sem vendoring/fork).
- **Não fazer commit** a menos que o usuário peça explicitamente.
- **Não implementar** fora do escopo do PRD/tasks ativos sem alinhamento.
- **Não pular TDD** nem a retro do PRD seguinte (ADR-022).
- **Não assumir** que este repo já tem CLI, facade ou SessionStore — ainda estão em planejamento (Fase 0).
- **Não criar** arquivos de documentação não solicitados (README extras, ADRs espontâneos).
- **Não usar** `cursor-hermes` — o nome correto é `cursor-agent`.

---

## Links rápidos

| Documento | Descrição |
|-----------|-----------|
| [docs/README.md](docs/README.md) | Hub de documentação |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Estratégia e arquitetura v1.2 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Índice de ADRs |
| [docs/BACKLOG-PHASE5.md](docs/BACKLOG-PHASE5.md) | Backlog pós-MVP |
| [docs/prd/README.md](docs/prd/README.md) | Índice de PRDs |
| [docs/prd/PRD-000-sdk-spike.md](docs/prd/PRD-000-sdk-spike.md) | PRD ativo (Fase 0) |
| [engineering/tasks/README.md](engineering/tasks/README.md) | Índice mestre de planos de tarefas |
| [engineering/tasks/tasks-PRD-000-sdk-spike.md](engineering/tasks/tasks-PRD-000-sdk-spike.md) | Tasks do PRD-000 |
| [docs/decisions/ADR-023-long-running-agent-harness.md](docs/decisions/ADR-023-long-running-agent-harness.md) | Harness para agentes de longa duração |
| [docs/contracts/async-sdk-facade.md](docs/contracts/async-sdk-facade.md) | Contrato da facade async |
| [docs/gateway-security.md](docs/gateway-security.md) | Threat model do gateway |
| [docs/decisions/ADR-022-tdd-prd-feedback-loop.md](docs/decisions/ADR-022-tdd-prd-feedback-loop.md) | TDD + retro entre PRDs |
| [.cursor/commands/code-review.md](.cursor/commands/code-review.md) | Protocolo executável de code review (`/code-review`) |
| [.cursor/rules/code-review.mdc](.cursor/rules/code-review.mdc) | Gates obrigatórios de review (stack Python + cursor-sdk) |
| [docs/decisions/ADR-005-testing-strategy.md](docs/decisions/ADR-005-testing-strategy.md) | Estratégia de testes |
| [.cursor/commands/prd.md](.cursor/commands/prd.md) | Comando/template PRD |
| [.cursor/commands/generate-tasks.md](.cursor/commands/generate-tasks.md) | Comando/template tasks |
| [.cursor/commands/development.md](.cursor/commands/development.md) | Protocolo de desenvolvimento |
| [.cursor/rules/agent-clean-code.mdc](.cursor/rules/agent-clean-code.mdc) | Regras de código para agentes |
| [.cursor/rules/python-best-practices.mdc](.cursor/rules/python-best-practices.mdc) | Boas práticas Python |
| [.cursor/rules/secure-dev-python.mdc](.cursor/rules/secure-dev-python.mdc) | Segurança Python (secrets, subprocess) |
| [.cursor/rules/secure-mcp-dev.mdc](.cursor/rules/secure-mcp-dev.mdc) | MCP no perfil dev |
| [.cursor/rules/secure-mcp-messaging.mdc](.cursor/rules/secure-mcp-messaging.mdc) | MCP deny no gateway |
| [.cursor/skills/test-driven-development/SKILL.md](.cursor/skills/test-driven-development/SKILL.md) | Skill TDD |
| [.cursor/commands/clarify-task.md](.cursor/commands/clarify-task.md) | Gate LGTM (ADR-023) |
| [.cursor/commands/security-audit.md](.cursor/commands/security-audit.md) | Auditoria de segurança |
