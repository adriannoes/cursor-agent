# Development — execução de iniciativas (PRD + task plan)

Protocolo para implementar uma **iniciativa completa** (um PRD e seu task plan) com planejamento de alto esforço, execução paralela via sub-agents e entrega única ao final (review → commits → PR).

Índice mestre: [engineering/tasks/README.md](../../engineering/tasks/README.md). Harness: [ADR-023](../../docs/decisions/ADR-023-long-running-agent-harness.md). Paralelismo: [dispatching-parallel-agents](../skills/dispatching-parallel-agents/SKILL.md).

---

## Invocação

- Slash command: **`/development`**
- Ou instrução explícita: *"execute o comando development para o PRD-XXX"*

**Sempre** carregar o **PRD ativo** e o **task plan** correspondente antes de qualquer código. Exemplo:

| Artefato | Caminho |
|----------|---------|
| PRD | [docs/prd/PRD-000-sdk-spike.md](../../docs/prd/PRD-000-sdk-spike.md) |
| Task plan | [engineering/tasks/tasks-PRD-000-sdk-spike.md](../../engineering/tasks/tasks-PRD-000-sdk-spike.md) |

Convenção: `tasks-PRD-{NNN}-{slug}.md` ↔ `PRD-{NNN}-{slug}.md`.

---

## Papéis e modelos

| Papel | Modelo | Esforço | Responsabilidade |
|-------|--------|---------|------------------|
| **Orquestrador** (esta sessão) | **Claude Opus 4.8** ou **GPT 5.5** | **High / Extra-high** | Ler PRD + task plan completo, montar grafo de dependências, planejar ondas de paralelismo, despachar sub-agents, integrar resultados, revisão final, commits e PR |
| **Sub-agents** (implementação) | **Composer 2.5** | Padrão | Executar sub-tasks isoladas com TDD; retornar resumo + arquivos alterados |

**Regra:** o orquestrador **não** implementa sub-tasks inline quando existem ondas paralelizáveis — delega via ferramenta `Task` com `model: "composer-2.5"` (ou `composer-2.5-fast` para exploração read-only).

---

## Visão geral do fluxo

```text
Fase 0  Bootstrap     → carregar PRD, ADRs, task plan inteiro
Fase A  Planejamento   → grafo de deps + ondas paralelas → LGTM
Fase B  Execução       → sub-agents Composer 2.5 em paralelo (por onda)
Fase C  Revisão final  → integrar, gate de qualidade, /code-review
Fase D  Entrega        → commits atômicos + abrir PR
Fase E  Próxima        → retro no PRD-(N+1); só então próximo PRD/tasks
```

**Política de commits:** **não** commitar durante a Fase B. Commits e PR ocorrem **somente** após Fase C aprovada.

---

## Fase 0 — Bootstrap (obrigatória)

Antes de planejar ou codar:

1. Ler [AGENTS.md](../../AGENTS.md) (se primeira sessão no repo).
2. Ler o **PRD ativo** por completo — especialmente §4 (FR), §10 (DoD) e frontmatter `adrs:`.
3. Ler **cada ADR** listado no PRD.
4. Ler o **task plan inteiro** (`engineering/tasks/tasks-PRD-*.md`) — todas as parent tasks, sub-tasks, **Depends on**, **Enables**, **Acceptance criteria**, **Verify** e **Relevant Files**.
5. Se o task plan não existir ou estiver só na fase 1 (parent tasks sem sub-tasks), executar **`/generate-tasks`** e **parar** até LGTM + fase 2 completa.

**Saída esperada:** resumo de escopo, DoD, sub-tasks pendentes (`[ ]`) e riscos.

---

## Fase A — Planejamento (orquestrador: Opus 4.8 / GPT 5.5, high)

O orquestrador deve **carregar o task plan completo** e produzir um **plano de paralelismo** antes de despachar sub-agents.

### A.1 Construir grafo de dependências

Para cada parent task e sub-task, extrair:

- **Depends on** / **Enables** (campos do task plan)
- **File** (evitar dois agents no mesmo arquivo na mesma onda)
- Ordem TDD sugerida em **Notes** (ex.: smoke falhando antes do REPL completo)

Agrupar sub-tasks em **ondas** (waves):

- **Onda N:** sub-tasks cujas dependências estão `[x]` e que **não** compartilham arquivos de escrita.
- **Onda N+1:** sub-tasks bloqueadas até a onda anterior terminar.

Maximizar sub-agents por onda respeitando:

| Pode paralelizar | Não paralelizar |
|------------------|-----------------|
| Sub-tasks em arquivos/disjunções diferentes | Mesmo arquivo alvo |
| Domínios independentes (ex.: `tests/unit/` vs `examples/`) | Cadeia Depends on não satisfeita |
| Exploração read-only (`readonly: true`) | Escrita concorrente em `pyproject.toml`, `src/cursor_agent/` compartilhado |

### A.2 Plano de ondas (formato obrigatório)

```markdown
## Plano de execução — PRD-XXX

**PRD:** … | **Tasks:** engineering/tasks/tasks-PRD-XXX-….md
**Sub-tasks pendentes:** N
**Ondas planejadas:** W

### Onda 1 (paralelo: K agents)
| Agent | Sub-task | Arquivos | subagent_type | Verify |
|-------|----------|----------|---------------|--------|
| A1 | 1.1 | pyproject.toml | generalPurpose | uv sync … |

### Onda 2 …
…

**Riscos / serialização forçada:** …
**Gate pós-onda:** ruff + format + mypy + pytest (ADR-026)
```

### A.3 Gate LGTM

Apresentar o plano e **aguardar LGTM** explícito do usuário antes da Fase B.

Exceção: usuário já disse *"LGTM — executar autonomamente"* ou invocou `/development` com PRD e task plan explícitos pedindo execução completa.

---

## Fase B — Execução paralela (sub-agents: Composer 2.5)

Após LGTM, o orquestrador executa **onda por onda**.

### B.1 Despacho de sub-agents

Para cada onda, lançar **o máximo de sub-agents em paralelo** numa **única mensagem** (múltiplas chamadas `Task`):

```text
Task(
  subagent_type="generalPurpose",
  model="composer-2.5",
  description="PRD-000 task 1.1 pyproject pin",
  prompt="…"  # auto-contido: paths, ADRs, sub-task, Verify, constraints
)
```

**Prompt do sub-agent** (obrigatório — ver [dispatching-parallel-agents](../skills/dispatching-parallel-agents/SKILL.md)):

1. Sub-task exata (copiar **What**, **Why**, **Pattern**, **Verify** do task plan)
2. Caminhos de arquivo e ADRs relevantes
3. TDD: teste falhando → implementar → verde ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md))
4. Restrições: não tocar arquivos fora do escopo; não commitar
5. Saída: resumo + lista de arquivos alterados + resultado do **Verify**

`subagent_type` sugerido:

| Tipo | Quando |
|------|--------|
| `generalPurpose` | Implementação TDD de sub-task |
| `explore` | Leitura ampla, `readonly: true` |
| `shell` | Comandos `uv`, `pytest`, gates |

### B.2 Integração por onda

Quando os sub-agents retornarem:

1. Ler cada resumo; resolver conflitos (`git diff` em paths sobrepostos).
2. Rodar o **gate canônico** ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)) se `src/` ou `tests/` existirem:

```bash
ruff check src tests
ruff format --check src tests
mypy --strict src
pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
```

3. Marcar sub-tasks `[x]` no task plan; marcar parent `[x]` quando todos os filhos estiverem `[x]`.
4. Atualizar seção **Relevant Files** no task plan.
5. Se a onda falhou: corrigir inline ou re-despachar agent focado — **não** avançar para a próxima onda com dependências quebradas.

Repetir ondas até **todas** as sub-tasks do PRD estarem `[x]` e o DoD (PRD §10) estiver atendido.

### B.3 Checkpoints (reportar, não bloquear)

Após cada onda, reportar ao usuário:

```markdown
## Checkpoint — PRD-XXX / Onda N

**Concluído:** 1.1, 1.2, 1.3 [x]
**Gate:** ruff ✓ | format ✓ | mypy ✓ | pytest ✓
**Próxima onda:** …
**Blockers:** nenhum
```

---

## Fase C — Revisão final (antes de commits)

Somente quando o task plan está 100% `[x]` e o DoD do PRD foi verificado:

1. **Integração global** — `git status` / `git diff`; garantir ausência de conflitos e slop de IA ([slop.md](./slop.md) se necessário).
2. **Gate de qualidade final** — repetir comandos ADR-026; evidência obrigatória ([verification-before-completion](../skills/verification-before-completion/SKILL.md)).
3. **`/code-review`** — executar [code-review.md](./code-review.md) + gates em [code-review.mdc](../rules/code-review.mdc).
4. Corrigir **todos** os blockers; re-rodar gates até veredito **Aprovado**.

**Não** abrir PR nem commitar antes do veredito **Aprovado**.

---

## Fase D — Entrega (commits + PR)

Após revisão aprovada:

1. **Branch** — uma branch por iniciativa, ex.: `feat/prd-000-sdk-spike`.
2. **Commits** — atômicos, Conventional Commits em inglês; um change lógico por commit.
3. **Push** + **`gh pr create`** — corpo com Summary + Test plan.
4. Aguardar CI verde (quando workflow existir) antes de merge.

Commits **não** devem incluir co-autores de bots; seguir política de secrets ([ADR-025](../../docs/decisions/ADR-025-secrets-policy.md)).

---

## Fase E — Próxima iniciativa

**Só após** PR aberta (ou merge, conforme política do usuário):

1. **Retro** [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) — atualizar §7, §9 e §11 do **PRD-(N+1)** com aprendizados do código entregue.
2. Identificar próximo PRD em [docs/prd/README.md](../../docs/prd/README.md).
3. Se faltar task plan: **`/generate-tasks`** (fase 1 → LGTM → fase 2).
4. Atualizar índice em [engineering/tasks/README.md](../../engineering/tasks/README.md).
5. Iniciar nova sessão **`/development`** para o próximo PRD — **não** misturar escopo de dois PRDs na mesma branch/PR.

---

## Manutenção do task plan

Durante Fase B e C, o orquestrador deve:

1. Marcar cada sub-task concluída como `[x]`; marcar parent quando todos os filhos estiverem `[x]`.
2. Manter **Relevant Files** atualizado (arquivo + descrição de uma linha).
3. Adicionar sub-tasks descobertas em execução, com LGTM se mudarem escopo do PRD.

---

## Instruções para o agente orquestrador

1. **Sempre** iniciar pela Fase 0 — nunca codar sem ler PRD + task plan completo.
2. **Planejar** (Fase A) com Opus 4.8 ou GPT 5.5 em esforço high; produzir ondas de paralelismo explícitas.
3. **Delegar** implementação a sub-agents **Composer 2.5** via `Task`; maximizar paralelismo por onda.
4. **Não commitar** durante Fase B; working tree acumula até Fase D.
5. **Não** declarar PRD concluído sem `/code-review` **Aprovado** e DoD verificado com evidência.
6. **Não** iniciar o próximo PRD sem concluir Fase D + retro (Fase E).
7. Respeitar TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)) e ordem em **Notes** do task plan (ex.: [tasks-PRD-000](../../engineering/tasks/tasks-PRD-000-sdk-spike.md) — smoke falhando antes do REPL).
8. Em dúvida sobre paralelismo: serializar — preferir correção a corrida em arquivo compartilhado.

---

## Exemplo — PRD-000 (referência)

| Artefato | Link |
|----------|------|
| PRD | [PRD-000-sdk-spike.md](../../docs/prd/PRD-000-sdk-spike.md) |
| Task plan | [tasks-PRD-000-sdk-spike.md](../../engineering/tasks/tasks-PRD-000-sdk-spike.md) |

**Ondas ilustrativas** (o orquestrador deve recalcular a partir do estado `[ ]` / `[x]` atual):

```text
Onda 1 (serial — fundação):     1.1 → 1.2 → 1.3 → 1.4 → 1.5 → 1.6 → 1.7 → 1.8
Onda 2 (serial — TDD smoke):    4.1 → 4.2  (esqueleto falhando; habilita 2.0)
Onda 3 (paralelo possível):     2.1–2.3 (async_repl) | 3.1–3.2 (tools_list) — se arquivos disjuntos e deps OK
Onda 4 (integração):            4.3+ smoke verde, snapshot, DoD
```

A ordem exata vive no task plan; o orquestrador **não** copia esta tabela cegamente — recalcula dependências a cada sessão.

---

## Referências

- [ADR-023 — Harness long-running](../../docs/decisions/ADR-023-long-running-agent-harness.md)
- [ADR-022 — TDD + retro](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)
- [ADR-026 — Gate de qualidade](../../docs/decisions/ADR-026-quality-tooling.md)
- [generate-tasks.md](./generate-tasks.md) — criar task plan
- [code-review.md](./code-review.md) — revisão antes da entrega
- [clarify-task.md](./clarify-task.md) — desambiguar escopo antes de codar
- [dispatching-parallel-agents](../skills/dispatching-parallel-agents/SKILL.md)
- [test-driven-development](../skills/test-driven-development/SKILL.md)
- [verification-before-completion](../skills/verification-before-completion/SKILL.md)
- [finishing-a-development-branch](../skills/finishing-a-development-branch/SKILL.md)
