# Code Review — cursor-agent

Protocolo **executável** de revisão antes de considerar um PRD (ou PR) concluído. Destinado a agentes de longa duração e revisores humanos.

**Regra condensada (gates obrigatórios):** [.cursor/rules/code-review.mdc](../rules/code-review.mdc) — aplicar junto com este comando; não substitui as fases abaixo.

---

## Invocação

- Slash command: **`/code-review`**
- Ou instrução explícita: *"execute o comando code-review"*

**Ao invocar:** ler este arquivo **por completo** e executar todas as fases em ordem. Não pular fases nem substituir gates automatizados por inspeção visual.

---

## Quando executar

| Momento | Ação se reprovado |
|---------|-------------------|
| DoD (§10) do PRD ativo atingido | Não marcar PRD encerrado; não iniciar PRD seguinte |
| Antes de merge de PR para `main` | Não abrir/mergear PR |
| Após retro no PRD-(N+1) ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)) | Completar retro antes de declarar aprovado |

---

## Entradas obrigatórias (coletar antes da Fase 1)

O agente deve reunir e citar no relatório final:

| Entrada | Como obter |
|---------|------------|
| **PRD ativo** | Frontmatter + §4 (FR) + §10 (DoD) — ex.: [docs/prd/PRD-000-sdk-spike.md](../../docs/prd/PRD-000-sdk-spike.md) |
| **Arquivo de tasks** | `engineering/tasks/tasks-PRD-{NNN}-{slug}.md` correspondente |
| **Arquivos alterados** | `git status` + `git diff` (ou `git diff main...HEAD` em branch) |
| **ADRs do PRD** | Lista `adrs:` no frontmatter do PRD — ler cada ADR referenciado |
| **PRD seguinte** (retro) | Próximo na cadeia [docs/prd/README.md](../../docs/prd/README.md) — só se DoD completo |

---

## Fase 1 — Gates automatizados

Executar **na raiz do repositório** e registrar comando + resultado no relatório.

Gate canônico de qualidade ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)) — obrigatório sempre que existir `src/` ou `tests/`:

```bash
# Lint
ruff check src tests

# Formatação (sem reescrever; só verificar)
ruff format --check src tests

# Tipagem estrita do código de produção
mypy --strict src

# Testes sem integração + cobertura mínima
pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"

# Integração — somente se o PRD exigir (ex.: PRD-000 smoke @integration)
# Requer CURSOR_API_KEY no ambiente; sem key deve dar SKIP, não FAIL
pytest -m integration -v
```

| Gate | Critério de falha |
|------|-------------------|
| `ruff check` | Qualquer erro ou warning não suprimido com justificativa no PRD |
| `ruff format --check` | Qualquer arquivo fora do formato (`ruff format` resolve) |
| `mypy --strict src` | Qualquer erro de tipo no código de produção |
| `pytest --cov ... --cov-fail-under=85` | Qualquer teste falhando ou cobertura < 85% |
| `pytest -m integration` | Falha com key presente; ou FAIL (não SKIP) sem key quando marker exige skip |

**Nota:** se `src/` ou `tests/` ainda não existirem (Fase 0 pré-scaffold), documentar no relatório e pular apenas os comandos impossíveis — isso é **ressalva**, não aprovação automática, salvo se o PRD for exclusivamente documentação.

---

## Fase 2 — Revisão específica da stack

Checklist manual com evidência (`rg`, leitura de diff, grep). Marcar cada item no relatório.

### Arquitetura SDK ([ADR-002](../../docs/decisions/ADR-002-async-sdk-facade.md), [contrato](../../docs/contracts/async-sdk-facade.md))

- [ ] `cursor_sdk` importado **apenas** em `sdk_facade.py` (ou módulo equivalente documentado no PRD):

  ```bash
  rg "cursor_sdk|from cursor_sdk|import cursor_sdk" src/
  ```

  Resultado esperado: um único arquivo (facade). Exceção: PRD-000 spike pode importar em `examples/` — verificar escopo do PRD.

- [ ] `AsyncSdkFacade` segue o `Protocol` / contrato em [docs/contracts/async-sdk-facade.md](../../docs/contracts/async-sdk-facade.md).
- [ ] Testes usam `FakeSdkFacade` (ou fake equivalente) — sem bridge real na suíte `not integration`.
- [ ] Exit codes CLI conforme contrato §3: **0** sucesso/cancelado, **1** erro pré-run (`CursorAgentError`), **2** run iniciou e falhou (`RunResult.status == ERROR`).

### Sessões e runtime ([ADR-003](../../docs/decisions/ADR-003-cross-runtime-resume.md), [ADR-004](../../docs/decisions/ADR-004-session-key-workspace.md))

- [ ] `session_key` inclui `workspace_hash` quando aplicável (`cli:{profile}:{workspace_hash}`, `telegram:{chat_id}:{workspace_hash}`).
- [ ] Resume cross-runtime **proibido** — runtime armazenado deve ser validado no resume.
- [ ] Lock por `session_key` no pool quando PRD tocar concorrência.

### Convenções do projeto

- [ ] Variáveis de ambiente com prefixo `CURSOR_AGENT__*`; secrets em env, documentados em [.env.example](../../.env.example).
- [ ] Paths de config/dados em `~/.cursor-agent` (não hardcodar home alternativo).
- [ ] `cursor-sdk` com pin exato `==X.Y.Z` em `pyproject.toml` ([ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md)).
- [ ] Marker `@pytest.mark.integration` em testes que exigem `CURSOR_API_KEY`; skip automático sem key ([ADR-005](../../docs/decisions/ADR-005-testing-strategy.md)).
- [ ] **Sem** código copiado do [Hermes Agent](https://github.com/NousResearch/hermes-agent) — apenas referência comportamental.

### Qualidade de código

- [ ] Funções e módulos dentro dos limites de [agent-clean-code.mdc](../rules/agent-clean-code.mdc).
- [ ] Tipos explícitos em APIs públicas ([python-best-practices.mdc](../rules/python-best-practices.mdc)).
- [ ] TDD por FR ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)): teste falhando → implementação → verde.
- [ ] Sem segredos no diff (`CURSOR_API_KEY`, tokens, `.env` real).

### PR (quando aplicável)

- [ ] Título Conventional Commits: `type(scope): description`.
- [ ] Descrição lista mudanças e comando de teste.
- [ ] Diff revisável (< 300 linhas ou PR focado).

---

## Fase 3 — Rastreabilidade PRD / FR

Para **cada** requisito funcional (FR-N) listado em §4 do PRD ativo, preencher:

| FR | Implementação (arquivo) | Teste(s) | Status |
|----|-------------------------|----------|--------|
| FR-1 | `src/...` | `tests/...` | ok / gap |

- Todo FR do escopo do PRD deve ter linha **ok** ou virar **bloqueador**.
- Escopo extra não solicitado no PRD → **ressalva** (remover ou documentar alinhamento).
- Se o PRD tiver tabela §9 (mapeamento FR → teste), validar consistência com o código.

---

## Fase 4 — Arquivo de tasks

Arquivo: `engineering/tasks/tasks-PRD-{NNN}-{slug}.md`

- [ ] Todas as sub-tasks do escopo deste PRD marcadas `[x]`.
- [ ] Parent tasks marcadas `[x]` quando todos os filhos estão `[x]`.
- [ ] Seção **Relevant Files** atualizada — cada arquivo criado/alterado com descrição de uma linha.
- [ ] [engineering/tasks/README.md](../../engineering/tasks/README.md) — status do PRD na tabela de índice reflete realidade (ex.: *implementado*, *em progresso*).

---

## Fase 5 — Gate de retroalimentação (ADR-022)

**Somente se** DoD (§10) do PRD ativo estiver completo **e** Fases 1–4 sem bloqueadores:

- [ ] §7 (riscos/aprendizados), §9 (mapeamento testes) e §11 (notas para implementação) do **PRD-(N+1)** atualizados com evidência desta entrega.
- [ ] Aprendizados refletem código real (não genéricos).

Se o PRD seguinte ainda não existir ou for o último da cadeia, documentar *"N/A — fim da cadeia"* no relatório.

---

## Veredito e saída obrigatória

Produzir **um** resumo em markdown com esta estrutura (preencher todos os campos):

```markdown
## Code review — PRD-NNN

**PRD:** docs/prd/PRD-NNN-....md
**Tasks:** engineering/tasks/tasks-PRD-NNN-....md
**Diff:** N arquivos alterados (resumo: …)

**Veredito:** Aprovado | Aprovado com ressalvas | Reprovado

### Bloqueadores
- (lista ou "nenhum")

### Ressalvas
- (lista ou "nenhuma")

### Fase 1 — Gates automatizados
- ruff check src tests: (comando + exit code + resumo)
- ruff format --check src tests: (comando + exit code + resumo)
- mypy --strict src: (comando + exit code + resumo)
- pytest --cov ... --cov-fail-under=85 -m "not integration": (comando + exit code + N passed + % cobertura)
- pytest -m integration -v: (executado / N/A / SKIP sem key)

### Fase 2 — Stack
- cursor_sdk isolado: (resultado do rg)
- FakeSdkFacade / exit codes / session_key / ADRs: (ok ou gap)

### Fase 3 — FR
| FR | Arquivo | Teste | Status |
|----|---------|-------|--------|
| FR-1 | … | … | ok |

### Fase 4 — Tasks
- Sub-tasks [x]: (sim/não)
- Relevant Files: (atualizado/sim/não)

### Fase 5 — Retro
- PRD-(N+1) §7/§9/§11: (atualizado / N/A / pendente)

### Verificado
- ADRs do frontmatter: (lista + conformidade)
- Hermes copy: (ausente / encontrado)
```

### Regras do veredito

| Veredito | Condição | Próximo passo |
|----------|----------|----------------|
| **Reprovado** | Qualquer bloqueador (gate vermelho, FR sem cobertura, tasks incompletas, violação arquitetural) | Corrigir; **não** marcar PRD done; **não** iniciar PRD seguinte |
| **Aprovado com ressalvas** | Gates verdes; gaps menores documentados com plano | Pode fechar PRD se ressalvas forem aceitáveis no escopo; registrar débito |
| **Aprovado** | Todas as fases OK; retro completa se aplicável | Atualizar índice; iniciar PRD seguinte conforme [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) |

---

## Referências

| Documento | Uso |
|-----------|-----|
| [ADR-005 — Pirâmide de testes](../../docs/decisions/ADR-005-testing-strategy.md) | markers, integração, FakeSdkFacade |
| [ADR-026 — Ferramentas de qualidade](../../docs/decisions/ADR-026-quality-tooling.md) | gate canônico: ruff format, mypy --strict, cobertura ≥ 85% |
| [ADR-022 — TDD e retro](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) | TDD, gate §7/§9/§11 |
| [ADR-023 — Long-running harness](../../docs/decisions/ADR-023-long-running-agent-harness.md) | checkpoints, quando executar review |
| [async-sdk-facade.md](../../docs/contracts/async-sdk-facade.md) | Protocol, exit codes, lifecycle |
| [agent-clean-code.mdc](../rules/agent-clean-code.mdc) | limites de tamanho, grep, testes |
| [python-best-practices.mdc](../rules/python-best-practices.mdc) | tipos, pytest, ruff, uv |
| [code-review.mdc](../rules/code-review.mdc) | gates condensados (não pular) |
| [development.md](./development.md) | execução de tasks e checkpoints |
