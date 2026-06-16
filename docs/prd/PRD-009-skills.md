---
id: PRD-009
title: Skills via SDK
status: draft
phase: 4
depends_on: [PRD-004]
adrs:
  - ADR-013
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "12.1"
  - path: ../decisions/ADR-013-slash-commands-skills.md
    role: spec
---

# PRD-009 — Skills

## 1. Introdução/Visão Geral

Skills são instruções reutilizáveis do workspace Cursor (`.cursor/skills/`) que o usuário invoca com `/<skill-name>`. O cursor-agent deve listá-las e injetar o conteúdo no turno atual **sem** implementar um loader paralelo ao SDK — alinhado à [Fase 4 — §12.1](../STRATEGY.md#121-skills-via-sdk) e [STRATEGY §2.5](../STRATEGY.md#25-skills).

**Problema:** hoje não há descoberta nem invocação ergonômica de skills no REPL Hermes-like.

**Objetivo:** integrar skills ao `CommandRouter` existente ([PRD-004](PRD-004-slash-commands.md)), respeitando namespace e prioridade definidos em [ADR-013](../decisions/ADR-013-slash-commands-skills.md).

## 2. Objetivos

- Listar skills visíveis do workspace via comando `/skills`.
- Permitir invocação `/<skill-name>` injetando o conteúdo da skill no turno.
- Resolver input na ordem: built-in → skill → mensagem livre ([ADR-013](../decisions/ADR-013-slash-commands-skills.md)).
- Reutilizar descoberta via `setting_sources` + `.cursor/skills/` (padrão Cursor / agentskills.io).
- Evitar loader custom salvo gap comprovado após Fase 4.

## 3. Histórias de Usuário

- **Como** usuário do CLI, **quero** `/skills` para ver skills disponíveis no workspace, **para** saber o que posso invocar.
- **Como** usuário experiente, **quero** digitar `/<skill-name>` e ver o comportamento da skill no agente, **para** reutilizar playbooks sem copiar texto.
- **Como** desenvolvedor, **quero** que built-ins (`/help`, `/new`, etc.) tenham prioridade sobre nomes de skill, **para** evitar colisões de namespace.
- **Como** mantenedor, **quero** testes do router cobrindo denylist e resolução de skills, **para** regressões determinísticas.

## 4. Requisitos Funcionais

1. O comando `/skills` deve listar skills descobertas em `.cursor/skills/` do workspace ativo.
2. O input `/<skill-name>` deve injetar o conteúdo da skill correspondente no turno enviado ao agente.
3. O `CommandRouter` deve resolver na ordem ([ADR-013](../decisions/ADR-013-slash-commands-skills.md)):
   1. Comandos built-in (denylist reservada: `help`, `quit`, `new`, `reset`, `resume`, `stop`, `model`, `retry`, `usage`, `compress`, `skills`, `memory`, `personality`, `title`)
   2. Skills (`/<skill-name>` se existir)
   3. Mensagem livre → agente
4. Skills com nome na denylist **não** devem sobrescrever comandos built-in.
5. Skill inexistente após `/` deve cair em mensagem livre ou erro claro (decisão: mensagem livre com prefixo `/` preservado, salvo skill na denylist).
6. A descoberta deve usar mecanismos do SDK (`setting_sources`) — **sem** loader paralelo custom.
7. `/reset` permanece alias de `/new` ([ADR-013](../decisions/ADR-013-slash-commands-skills.md)); semântica Hermes “reset sem novo row” fora do MVP.

### Critérios de aceite (DoD)

- [ ] `/skills` lista `.cursor/skills/`
- [ ] `/<skill-name>` injeta conteúdo no turn
- [ ] Router: built-in antes de skills ([ADR-013](../decisions/ADR-013-slash-commands-skills.md))

## 5. Fora de Escopo (Non-Goals)

- Prefixo alternativo `/skill:name` — rejeitado em [ADR-013](../decisions/ADR-013-slash-commands-skills.md).
- Loader custom de skills independente do SDK.
- Skills globais fora do workspace (user-level) — depende do que `setting_sources` expõe; não duplicar lógica.
- Editor interativo de skills no CLI.
- Publicação ou marketplace de skills.

## 6. Considerações de Design

- `/skills` deve exibir nome, descrição curta (se disponível no frontmatter da skill) e caminho relativo.
- Lista ordenada alfabeticamente por nome de skill.
- Invocação `/<skill-name>` deve ser indistinguível de enviar o conteúdo da skill como mensagem do usuário (para o agente), exceto por metadado interno de logging.

## 7. Considerações Técnicas

- **Dependência:** [PRD-004](PRD-004-slash-commands.md) — `CommandRouter` e registry de slash commands.
- **Namespace:** [ADR-013](../decisions/ADR-013-slash-commands-skills.md) — denylist e ordem de resolução.
- **Descoberta:** [STRATEGY §2.5](../STRATEGY.md#25-skills) — `setting_sources: ["project", "user"]` + `.cursor/skills/`.
- **Facade:** injeção de conteúdo da skill ocorre antes do `send` ao SDK ([PRD-001](PRD-001-facade.md)).
- Skill não pode se chamar `help`, `new`, etc. — conflito evitado pela prioridade built-in.

## 8. Métricas de Sucesso

- `/skills` lista todas as skills do workspace em ambiente de demo.
- `/<skill>` altera comportamento do agente de forma visível (conteúdo da skill aplicado).
- 100% dos nomes na denylist resolvem como built-in, nunca como skill.
- Testes do router cobrem ordem de resolução e casos de colisão.

## 9. Questões em Aberto

- Skills em subpastas ou monorepo multi-root — qual workspace path prevalece?
- Exibir skills de `user` vs `project` com rótulo distinto em `/skills`?
- Logging: registrar skill invocada em NDJSON ([ADR-018](../decisions/ADR-018-observability-logs.md)) neste PRD ou PRD futuro?

## 10. Tarefas de implementação

### Definition of Done

- [ ] `/skills` lista `.cursor/skills/` do workspace
- [ ] `/<skill-name>` injeta conteúdo no turn
- [ ] Router: built-in antes de skills ([ADR-013](../decisions/ADR-013-slash-commands-skills.md))
- [ ] Testes do router sem `CURSOR_API_KEY`

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T1 | Discovery de skills (SDK / `.cursor/skills/`) | 3h | PRD-004 |
| T2 | Injeção de conteúdo da skill no turn | 3h | T1 |
| T3 | Comando `/skills` | 2h | T1 |
| T4 | Testes do router (built-in vs skill vs livre) | 3h | T2 |

### Demo

1. `cursor-agent` → `/skills` — lista skills disponíveis no workspace.
2. `/<skill-name>` — comportamento da skill visível no agente.

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR discovery | `tests/unit/test_skills_discovery.py` — lista `.cursor/skills/` | `pytest tests/unit/test_skills_discovery.py -v` |
| FR inject | `tests/unit/test_skills_injection.py` — conteúdo no turn | `pytest tests/unit/test_skills_injection.py -v` |
| FR router | `tests/unit/test_skills_router.py` — built-in antes de skill; colisão de nomes | `pytest tests/unit/test_skills_router.py -v` |
| FR `/skills` | `tests/unit/test_commands_skills.py` — listagem | `pytest tests/unit/test_commands_skills.py -v` |

Ordem sugerida: discovery → router/colisão → injeção → comando `/skills`.

### Retroalimentação

**Após concluir PRD-009:** revisar e atualizar [PRD-010](PRD-010-cron.md) (§7, §9, §11) antes do cron.

**Aprendizados a registrar:**

- [ ] API real do SDK para skills vs. leitura direta de disco
- [ ] Skills em monorepo / multi-root
- [ ] Logging de skill invocada (NDJSON)
- [ ] Namespace e denylist compartilhados com slash commands
- [ ] Impacto no tamanho do prompt (relevante para jobs cron)
