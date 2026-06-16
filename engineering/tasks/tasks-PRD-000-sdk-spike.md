# Tarefas — PRD-000 SDK spike (Fase 0)

> **PRD:** [PRD-000-sdk-spike.md](../../docs/prd/PRD-000-sdk-spike.md)  
> **ADRs:** [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) (pirâmide de testes e CI), [ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md) (pin exato `cursor-sdk`), [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) (TDD + retroalimentação), [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md) (gate ruff format + mypy + cov 85%)  
> **Escopo deste documento:** Fase 0 — spike de validação do SDK; sem facade, SessionStore ou CLI.  
> **Status:** Implementação concluída — code review aprovado com ressalvas.

## Relevant Files

- `pyproject.toml` — dependências pinadas (`cursor-sdk==X.Y.Z`), dev deps (`pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`), `[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.mypy]`, `[tool.coverage.run]` (FR-1, T1).
- `.github/workflows/ci.yml` — workflow mínimo com gate canônico [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md) (T1 / DoD).
- `src/cursor_agent/__init__.py` — scaffold mínimo do pacote para o gate ADR-026; sem facade, CLI ou SessionStore (DoD / T5.1).
- `tests/test_pyproject_config.py` — teste TDD de markers `integration` e `asyncio_mode` (FR-1).
- `tests/test_package_metadata.py` — teste TDD do scaffold mínimo `cursor_agent.__version__` para cobertura do pacote (DoD / T5.1).
- `uv.lock` — lockfile gerado por `uv` para reprodutibilidade do ambiente.
- `.env.example` — documenta `CURSOR_API_KEY` e variáveis opcionais; referência para exemplos e testes de integração.
- `examples/__init__.py` — (opcional) torna `examples/` um pacote importável; omitir se os scripts forem executados diretamente.
- `examples/async_repl.py` — exemplo executável com `AsyncClient.launch_bridge`, Composer 2.5, cold start documentado e segundo turn com contexto (FR-2, FR-3, FR-7, T2).
- `examples/tools_list.py` — script de introspecção das tools expostas pelo SDK; gera o snapshot (FR-4, T3).
- `docs/sdk-tools-snapshot.txt` — inventário versionado das tools da conta, baseline para fases seguintes (FR-4, US-3, T5).
- `docs/prd/PRD-001-facade.md` — retroalimentação do PRD-000 com versão SDK, latência, quirks de stream/tools e impactos para a facade (T5.6).
- `tests/__init__.py` — pacote raiz de testes (criar se ausente).
- `tests/integration/__init__.py` — pacote de testes de integração.
- `tests/integration/test_sdk_smoke.py` — smoke test com `@pytest.mark.integration`, skip sem `CURSOR_API_KEY`, validação de bridge + turn com tool nativa (FR-5, FR-6, T4).
- `tests/integration/conftest.py` — (opcional) fixture compartilhada para skip/bridge; criar apenas se reduzir duplicação entre testes.

### Notes

- **TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)):** Ordem sugerida: FR-1 (`test_pyproject_config.py`) → esqueleto smoke falhando (Tarefa 4.1–4.2) **antes** do REPL completo (Tarefa 2.0) → `async_repl` → smoke verde → `tools_list` + snapshot.
- **Gate de PR ([ADR-026](../../docs/decisions/ADR-026-quality-tooling.md)):**

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

- Testes de integração ficam em `tests/integration/`, espelhando a estrutura prevista em [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md).
- PRs locais sem API key (suíte estrutural / unitária):

  ```bash
  pytest -m "not integration" -v
  ```

  Deve passar sem `CURSOR_API_KEY` definida.

- Com API key (smoke de integração):

  ```bash
  export CURSOR_API_KEY="sua-chave"
  pytest tests/integration/test_sdk_smoke.py -m integration -v
  ```

- Exemplo manual do REPL async:

  ```bash
  export CURSOR_API_KEY="sua-chave"
  python examples/async_repl.py
  ```

- Regenerar snapshot de tools:

  ```bash
  export CURSOR_API_KEY="sua-chave"
  python examples/tools_list.py
  ```

- Pin do SDK: consultar [ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md) e [documentação oficial do Cursor Python SDK](https://cursor.com/docs/sdk/python) para a versão estável atual.
- Padrão async: `AsyncClient.launch_bridge` + `composer-2.5` + runtime **local-first** conforme [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike). Contrato futuro da facade em [async-sdk-facade.md](../../docs/contracts/async-sdk-facade.md) — somente leitura nesta fase.
- **Sem código copiado de referências** — pode estudar docs e codebases (Hermes, OpenClaw, etc.) para padrões; reimplementar em `cursor_agent` ([STRATEGY.md §1.4](../../docs/STRATEGY.md#14-relação-com-outros-projetos)).

## Tasks

- [x] **1.0 Configurar projeto e dependências (`pyproject.toml`)** — PRD T1 (T1.1–T1.3)

  **Trigger / entry point:** Início do spike; nenhuma dependência prévia no repositório.  
  **Enables:** Instalação via `uv`, execução de exemplos (Tarefa 2.0, 3.0) e testes (Tarefa 4.0).  
  **Depends on:** Nenhuma.

  **Acceptance criteria:**
  - `pyproject.toml` declara `cursor-sdk==X.Y.Z` com pin exato conforme ADR-017.
  - Dev dependencies incluem `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff` e `mypy`.
  - `[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.mypy]` e `[tool.coverage.run]` configurados conforme [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
  - `uv sync` (ou equivalente documentado) conclui sem erro.
  - `pytest -m "not integration" -v` executa sem falha estrutural (mesmo que zero testes coletados inicialmente).

  - [x] 1.1 Fixar `cursor-sdk` com pin exato no `pyproject.toml`
    - **File**: `pyproject.toml` (create new)
    - **What**: Adicionar dependência de runtime `cursor-sdk==X.Y.Z` (substituir `X.Y.Z` pela versão estável publicada no PyPI no momento da implementação). Incluir `requires-python = ">=3.11"` e metadados mínimos do projeto (`name`, `version`, `description`).
    - **Why**: FR-1 e [ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md) exigem builds reprodutíveis; upgrades futuros passam por PR Dependabot com gate de integração.
    - **Pattern**: Política de pin em [ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md); stack Python 3.11+ em [STRATEGY.md §5](../../docs/STRATEGY.md#5-stack-e-estrutura-do-repo).
    - **Verify**: `uv sync` instala `cursor-sdk` na versão pinada; `uv pip show cursor-sdk` exibe a mesma versão do pin.

  - [x] 1.2 Adicionar dependências de desenvolvimento (`pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`)
    - **File**: `pyproject.toml` (modify existing)
    - **What**: Declarar grupo `[dependency-groups]` ou `[project.optional-dependencies] dev` com `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff` e `mypy` em versões compatíveis com Python 3.11+.
    - **Why**: FR-1, [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) e [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md) definem stack de testes, lint, format e tipos para PRs determinísticos.
    - **Pattern**: Stack em [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: `uv sync --group dev` conclui sem erro; `ruff --version`, `pytest --version` e `mypy --version` respondem no venv.

  - [x] 1.3 Configurar `[tool.pytest.ini_options]` com marker `integration` e `asyncio_mode`
    - **File**: `pyproject.toml` (modify existing)
    - **What**: Adicionar bloco conforme ADR-005:

      ```toml
      [tool.pytest.ini_options]
      markers = ["integration: requires CURSOR_API_KEY"]
      asyncio_mode = "auto"
      testpaths = ["tests"]
      ```

    - **Why**: FR-1 e T1.3 permitem separar testes de integração (nightly / com secret) dos testes rápidos de PR.
    - **Pattern**: Snippet exato em [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md#decisão).
    - **Verify**: `pytest --markers` lista `integration`; `pytest --collect-only` não emite aviso de marker desconhecido.

  - [x] 1.4 Gerar lockfile e validar ambiente com `uv sync`
    - **File**: `uv.lock` (create new)
    - **What**: Executar `uv sync` (com grupo dev) para materializar `uv.lock` versionado no repositório.
    - **Why**: Reprodutibilidade do spike entre máquinas e CI futuro; baseline antes dos exemplos.
    - **Pattern**: Gerenciamento de deps via `uv` conforme regras do repositório e [STRATEGY.md §5](../../docs/STRATEGY.md#5-stack-e-estrutura-do-repo).
    - **Verify**: `uv sync` idempotente (segunda execução sem mudanças); `python -c "import cursor_sdk"` no venv não falha.

  - [x] 1.5 Validar coleta pytest sem integração
    - **File**: `tests/__init__.py` (create new, se ausente)
    - **What**: Garantir pacote `tests/` importável; criar `tests/__init__.py` vazio se necessário.
    - **Why**: Evita falhas estruturais de coleta antes da Tarefa 4.0; valida configuração da Tarefa 1.3.
    - **Pattern**: Layout `tests/integration/` previsto em [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md).
    - **Verify**: `pytest -m "not integration" -v` termina com exit code 0 (zero testes coletados é aceitável neste ponto).

  - [x] 1.6 Configurar `[tool.ruff]`, `[tool.mypy]` e `[tool.coverage.run]` no `pyproject.toml`
    - **File**: `pyproject.toml` (modify existing)
    - **What**: Adicionar seções conforme [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md): `line-length = 88`, `target-version = "py311"`, `mypy` strict em `cursor_agent`, `fail_under = 85` em coverage.
    - **Why**: FR-1 e gate de CI único e reproduzível.
    - **Pattern**: Snippets em [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md#3-pyprojecttoml-seções-obrigatórias).
    - **Verify**: `ruff check --help` e `mypy --help` reconhecem config do projeto após `src/` existir.

  - [x] 1.7 Teste TDD `tests/test_pyproject_config.py` (markers + `asyncio_mode`)
    - **File**: `tests/test_pyproject_config.py` (create new)
    - **What**: Teste que lê `pyproject.toml` (ou `import tomllib`) e asserta presença de marker `integration` e `asyncio_mode = "auto"` em `[tool.pytest.ini_options]`.
    - **Why**: FR-1 / PRD §11 — TDD red→green da config antes dos exemplos.
    - **Pattern**: Tabela TDD em [PRD-000 §11](../../docs/prd/PRD-000-sdk-spike.md#11-desenvolvimento--tdd-e-retroalimentação).
    - **Verify**: `pytest tests/test_pyproject_config.py -v` passa após Tarefa 1.3.

  - [x] 1.8 Adicionar workflow CI mínimo `.github/workflows/ci.yml`
    - **File**: `.github/workflows/ci.yml` (create new)
    - **What**: Job em `ubuntu-latest` com `uv sync`, então o gate canônico:

      ```bash
      ruff check src tests
      ruff format --check src tests
      mypy --strict src
      pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
      ```

    - **Why**: [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) assume CI; PRD-000 DoD inclui workflow.
    - **Pattern**: Gate em [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: Workflow válido (schema Actions); localmente os mesmos comandos passam após scaffold.

- [x] **2.0 Implementar exemplo async REPL (`examples/async_repl.py`)** — PRD T2 (T2.1–T2.3)

  **Trigger / entry point:** Desenvolvedor executa `python examples/async_repl.py` com `CURSOR_API_KEY` definida.  
  **Enables:** Demonstração manual do caminho async (US-1, US-4); validação manual após smoke verde.  
  **Depends on:** Tarefa 1.0; Tarefa 4.1 (esqueleto smoke coletável — TDD antes do REPL completo).

  **Acceptance criteria:**
  - Script usa `AsyncClient.launch_bridge` e modelo Composer 2.5.
  - Comentário inline documenta cold start medido (latência observada na primeira resposta).
  - Pelo menos dois turns na mesma sessão; o segundo turn referencia conteúdo do primeiro (FR-3).
  - Comentário registra decisão **local-first** para CLI/gateway (FR-7).
  - Execução com API key válida completa sem exceção e imprime respostas legíveis no terminal.

  - [x] 2.1 Criar esqueleto do exemplo com `AsyncClient.launch_bridge`
    - **File**: `examples/async_repl.py` (create new)
    - **What**: Script async com `asyncio.run(main())`, context manager `async with AsyncClient.launch_bridge(...) as client`, criação de agente no workspace local (`.`) e primeiro `send` com prompt simples. Imprimir texto da resposta no stdout.
    - **Why**: T2.1 / FR-2 validam que o bridge async inicializa e responde neste repositório antes de qualquer facade.
    - **Pattern**: `AsyncClient.launch_bridge` e runtime local conforme [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike) e [Cursor Python SDK](https://cursor.com/docs/sdk/python); contrato futuro em [async-sdk-facade.md](../../docs/contracts/async-sdk-facade.md) (`runtime_mode: "local"`, `model: "composer-2.5"`).
    - **Verify**: Com `CURSOR_API_KEY` válida, `python examples/async_repl.py` completa o primeiro turn sem exceção.
    - **Integration**: Padrão reutilizado pelo smoke test (Tarefa 4.0) e, na Fase 1, pela `AsyncSdkFacade` ([PRD-001](../../docs/prd/PRD-001-facade.md)).

  - [x] 2.2 Fixar modelo Composer 2.5 e documentar cold start medido
    - **File**: `examples/async_repl.py` (modify existing)
    - **What**: Passar `model="composer-2.5"` (ou equivalente na API Python) na criação do agente. Medir com `time.perf_counter()` o intervalo entre o primeiro `send` e a primeira resposta; registrar em comentário no topo do arquivo (ex.: `# Cold start medido: ~Xs em <data/host>`).
    - **Why**: T2.2 / US-4 calibram expectativas de latência do REPL antes da Fase 1.
    - **Pattern**: Modelo padrão `composer-2.5` em [STRATEGY.md](../../docs/STRATEGY.md) e [async-sdk-facade.md](../../docs/contracts/async-sdk-facade.md).
    - **Verify**: Comentário de cold start presente com valor numérico; modelo Composer 2.5 explícito no código.

  - [x] 2.3 Implementar segundo turn com contexto preservado
    - **File**: `examples/async_repl.py` (modify existing)
    - **What**: Na mesma sessão/agente, enviar segundo prompt que exige memória do primeiro (ex.: primeiro turn define um código secreto ou palavra; segundo turn pede para repetir). Validar que a resposta referencia o conteúdo do primeiro turn.
    - **Why**: T2.3 / FR-3 prova que o histórico persiste no agente SDK — pré-requisito para `/resume` na Fase 1.
    - **Pattern**: Multi-turn na mesma instância de agente conforme [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike) (“segundo turn mantém contexto”).
    - **Verify**: Execução manual mostra que o segundo turn responde com base no primeiro; sem criar novo agente entre os turns.
    - **Integration**: Comportamento esperado replicado no smoke test (Tarefa 4.4) e validado nas métricas de sucesso do PRD §8.

  - [x] 2.4 Registrar decisão local-first em comentário inline
    - **File**: `examples/async_repl.py` (modify existing)
    - **What**: Adicionar comentário explicando que CLI e gateway usarão runtime **local** (`launch_bridge` / workspace local); cloud reservado para jobs batch — alinhado a FR-7.
    - **Why**: FR-7 e [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike) registram a decisão de deploy antes da Fase 1.
    - **Pattern**: Decisão “local-first para CLI/gateway; cloud para batch” em [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike).
    - **Verify**: Comentário visível no arquivo; runtime usado no código é local (não cloud).

  - [x] 2.5 Validar pré-condição `CURSOR_API_KEY` com mensagem acionável
    - **File**: `examples/async_repl.py` (modify existing)
    - **What**: No início de `main()`, verificar `os.environ.get("CURSOR_API_KEY")`; se ausente, imprimir mensagem com link para `.env.example` / dashboard Cursor e sair com código ≠ 0.
    - **Why**: DX do spike — falha rápida e clara sem stack trace de autenticação do SDK.
    - **Pattern**: Variável documentada em `.env.example` e PRD §7.
    - **Verify**: Sem key, script sai com mensagem clara; com key, fluxo normal continua.

- [x] **3.0 Implementar inventário de tools e gerar snapshot** — PRD T3 + T5

  **Trigger / entry point:** Desenvolvedor ou CI (nightly) executa `python examples/tools_list.py` com `CURSOR_API_KEY`.  
  **Enables:** Baseline `docs/sdk-tools-snapshot.txt` para planejamento de perfis e hooks (US-3, PRD-001).  
  **Depends on:** Tarefa 1.0 (dependências instaladas).

  **Acceptance criteria:**
  - `examples/tools_list.py` introspeciona e lista as tools expostas pelo SDK.
  - Output é persistido em `docs/sdk-tools-snapshot.txt` (versionado no repositório).
  - Arquivo snapshot existe, é legível e contém nomes/descrições das tools da conta.
  - Script documenta como regenerar o snapshot quando a conta ou versão do SDK mudar.

  - [x] 3.1 Descobrir e documentar a API de introspecção de tools do SDK
    - **File**: `examples/tools_list.py` (create new)
    - **What**: Investigar **qual** mecanismo o SDK expõe para enumerar as tools da conta (candidatos: `SDKSystemMessage.tools`, atributo do client/agent, ou mensagem de sistema no stream) e **documentar no docstring do módulo** a API efetivamente encontrada. Implementar o script sobre essa API, imprimindo nome e descrição de cada tool em formato legível (texto ou JSON lines).
    - **Why**: T3 / FR-4 — descobrir a superfície de introspecção é o **objetivo do spike** (não um pré-requisito assumido); gera o baseline de tools para perfis MVP ([ADR-014](../../docs/decisions/ADR-014-tool-profiles-mvp.md)) na Fase 2.
    - **Pattern**: Pista em [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike) (`SDKSystemMessage.tools`) **a confirmar** contra o [Cursor Python SDK](https://cursor.com/docs/sdk/python); sem código Hermes.
    - **Verify**: Com `CURSOR_API_KEY`, `python examples/tools_list.py` imprime lista não vazia de tools; docstring registra a API de introspecção usada.
    - **Integration**: Output alimenta a Tarefa 3.2 (`docs/sdk-tools-snapshot.txt`); arquitetos usam o snapshot ao planejar [PRD-001](../../docs/prd/PRD-001-facade.md).

  - [x] 3.2 Persistir inventário em `docs/sdk-tools-snapshot.txt`
    - **File**: `docs/sdk-tools-snapshot.txt` (create new)
    - **What**: Executar `tools_list.py` e gravar o output em `docs/sdk-tools-snapshot.txt` (via redirecionamento shell ou escrita direta no script). Incluir cabeçalho com data, versão pinada do `cursor-sdk` e nota de que o arquivo é gerado.
    - **Why**: T5 / FR-4 / US-3 — artefato versionado como baseline da conta para diffs em upgrades do SDK ([ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md)).
    - **Pattern**: Caminho e propósito em [PRD-000 §4 FR-4](../../docs/prd/PRD-000-sdk-spike.md#4-requisitos-funcionais).
    - **Verify**: Arquivo existe no repositório, é legível e lista nomes/descrições das tools observadas na conta.
    - **Integration**: Referenciado em métricas de sucesso (PRD §8) e Definition of Done (PRD §10).

  - [x] 3.3 Documentar procedimento de regeneração do snapshot
    - **File**: `examples/tools_list.py` (modify existing)
    - **What**: Adicionar docstring no módulo (ou comentário no topo) com comando para regenerar: `CURSOR_API_KEY=... python examples/tools_list.py > docs/sdk-tools-snapshot.txt` (ajustar se o script gravar diretamente).
    - **Why**: Operadores precisam atualizar o baseline após upgrade do SDK ou mudança de conta sem reler o PRD.
    - **Pattern**: Notas de operação em [ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md) (upgrades conscientes).
    - **Verify**: Docstring/comentário contém comando reproduzível; reexecução atualiza o snapshot sem editar manualmente o conteúdo das tools.

- [x] **4.0 Implementar smoke test de integração (`tests/integration/test_sdk_smoke.py`)** — PRD T4 (T4.1–T4.2) + FR-6

  **Trigger / entry point:** `pytest tests/integration/test_sdk_smoke.py -m integration` (local ou nightly com secret).  
  **Enables:** Validação automatizada de bridge + API key (US-2); gate para upgrades do SDK (ADR-017).  
  **Depends on:** Tarefa 1.0 (markers e deps); esqueleto Tarefa 4.1 antes do REPL completo (Tarefa 2.0).

  **Acceptance criteria:**
  - Testes marcados com `@pytest.mark.integration`.
  - Sem `CURSOR_API_KEY`, a suíte faz **skip** automático (não falha).
  - Com API key válida: `AsyncClient.launch_bridge` inicializa sem erro.
  - Pelo menos um turn aciona tool nativa (ex.: `grep` ou leitura de arquivo) — FR-6.
  - `pytest -m "not integration" -v` continua passando sem API key.
  - `pytest tests/integration/test_sdk_smoke.py -m integration -v` passa com API key válida.

  - [x] 4.1 Criar pacote `tests/integration/` e arquivo de smoke test
    - **File**: `tests/integration/__init__.py` (create new), `tests/integration/test_sdk_smoke.py` (create new)
    - **What**: Criar pacote de integração e módulo de teste com pelo menos uma função `async def test_...` usando `pytest-asyncio`.
    - **Why**: Estrutura exigida por [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) antes de implementar skips e cenários.
    - **Pattern**: Diretório `tests/integration/` em [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md#decisão).
    - **Verify**: `pytest tests/integration/ --collect-only` coleta testes sem erro de import.

  - [x] 4.2 Aplicar marker `@pytest.mark.integration` em todos os testes do módulo
    - **File**: `tests/integration/test_sdk_smoke.py` (modify existing)
    - **What**: Decorar testes (ou usar `pytestmark = pytest.mark.integration` no módulo) para que só rodem com `-m integration`.
    - **Why**: T4.1 / FR-5 — separação PR rápido vs. nightly conforme [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md).
    - **Pattern**: Marker registrado na Tarefa 1.3; CI futuro: `pytest -m integration` com secret.
    - **Verify**: `pytest -m "not integration" -v` não executa testes deste arquivo; `pytest -m integration --collect-only` os inclui.

  - [x] 4.3 Implementar skip automático quando `CURSOR_API_KEY` estiver ausente
    - **File**: `tests/integration/test_sdk_smoke.py` (modify existing)
    - **What**: Usar `pytest.importorskip`, `pytest.mark.skipif(not os.getenv("CURSOR_API_KEY"), ...)` ou fixture em `conftest.py` que faz skip com razão explícita (“requires CURSOR_API_KEY”).
    - **Why**: T4.2 / FR-5 / US-2 — forks e PRs sem secret não falham.
    - **Pattern**: Skip sem key em [ADR-005](../../docs/decisions/ADR-005-testing-strategy.md) e [PRD-000 T4.2](../../docs/prd/PRD-000-sdk-spike.md#t4--smoke-test).
    - **Verify**: Sem `CURSOR_API_KEY`, `pytest tests/integration/test_sdk_smoke.py -m integration -v` reporta `SKIPPED`, exit code 0.

  - [x] 4.4 Testar inicialização do bridge e turn básico async
    - **File**: `tests/integration/test_sdk_smoke.py` (modify existing)
    - **What**: Teste que abre `AsyncClient.launch_bridge`, cria agente com `composer-2.5`, envia prompt mínimo e asserta resposta não vazia / status de sucesso.
    - **Why**: Valida autenticação + bridge (métrica “Autenticação” e “Bridge async” do PRD §8).
    - **Pattern**: Mesmo fluxo validado manualmente em `examples/async_repl.py` (Tarefa 2.1).
    - **Verify**: Com key válida, teste passa; falha clara se bridge não inicializar.
    - **Integration**: Gate para upgrades Dependabot ([ADR-017](../../docs/decisions/ADR-017-sdk-version-pin.md)).

  - [x] 4.5 Testar turn que aciona tool nativa (grep ou leitura de arquivo)
    - **File**: `tests/integration/test_sdk_smoke.py` (modify existing)
    - **What**: Prompt que force uso de tool nativa do SDK (ex.: “use grep to find the string cursor-agent in README.md” ou “read README.md and quote the first heading”). Assertar que o run completa e a resposta contém evidência do conteúdo do arquivo.
    - **Why**: FR-6 / [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike) — prova que tools nativas funcionam no workspace.
    - **Pattern**: Cenário “turn com tool (grep / read file)” em [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike).
    - **Verify**: Com key, teste passa e resposta referencia conteúdo real do repositório (`README.md` ou arquivo estável).
    - **Integration**: Confirma que o inventário do snapshot (Tarefa 3.0) corresponde a tools efetivamente invocáveis.

- [x] **5.0 Validar Definition of Done e handoff para Fase 1**

  **Trigger / entry point:** Revisão final do spike antes de iniciar [PRD-001](../../docs/prd/PRD-001-facade.md).  
  **Enables:** Repositório pronto para construir facade async; evidência documentada para arquitetos.  
  **Depends on:** Tarefas 1.0–4.0 concluídas.

  **Acceptance criteria:**
  - Definition of Done do PRD-000 atendida: API key + bridge OK; snapshot versionado; caminho async documentado nos exemplos.
  - Métricas de sucesso (PRD §8) verificáveis: autenticação, bridge async, contexto multi-turn, inventário, CI local sem key, integração com key.
  - Demo reproduzível: (1) `pytest tests/integration/test_sdk_smoke.py -m integration`, (2) `python examples/async_repl.py`.
  - Nenhum artefato de Fase 1 introduzido (sem `AsyncSdkFacade`, `SessionStore`, CLI instalável).
  - **Retroalimentação:** [PRD-001](../../docs/prd/PRD-001-facade.md) §7, §9 e §11 atualizados com aprendizados do spike antes de iniciar Fase 1 ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)).

  - [x] 5.1 Executar gate de qualidade local (sem integração)
    - **File**: — (verificação manual / CI local)
    - **What**: Rodar o gate canônico [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md):

      ```bash
      ruff check src tests
      ruff format --check src tests
      mypy --strict src
      pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
      ```

    - **Why**: Métrica “CI local” do PRD §8 — PRs sem API key não quebram.
    - **Pattern**: Pipeline PR em [ADR-026](../../docs/decisions/ADR-026-quality-tooling.md).
    - **Verify**: Todos os comandos terminam com exit code 0 sem `CURSOR_API_KEY`.

  - [x] 5.2 Executar **`/code-review`** antes do handoff
    - **File**: — (protocolo em [.cursor/commands/code-review.md](../../.cursor/commands/code-review.md))
    - **What**: Executar `/code-review` com gates em [.cursor/rules/code-review.mdc](../../.cursor/rules/code-review.mdc); veredito **Aprovado** ou **Aprovado com ressalvas** ([ADR-023](../../docs/decisions/ADR-023-long-running-agent-harness.md)).
    - **Why**: Gate obrigatório ADR-022/023 antes de encerrar PRD-000.
    - **Pattern**: Fluxo em [engineering/tasks/README.md](../README.md#fluxo-para-agentes-de-longa-duração).
    - **Verify**: Relatório de review arquivado ou citado no handoff; bloqueadores resolvidos.

  - [x] 5.3 Executar smoke de integração com API key válida
    - **File**: — (verificação manual / nightly)
    - **What**: Com `CURSOR_API_KEY` exportada, rodar `pytest tests/integration/test_sdk_smoke.py -m integration -v`.
    - **Why**: Métrica “Integração” do PRD §8 e gate de aceite do spike.
    - **Pattern**: Demo (1) em [PRD-000 §10](../../docs/prd/PRD-000-sdk-spike.md#demo).
    - **Verify**: Todos os testes de integração passam (não skipped).

  - [x] 5.4 Validar Definition of Done e métricas do PRD §8
    - **File**: `docs/sdk-tools-snapshot.txt`, `examples/async_repl.py`, `examples/tools_list.py` (review)
    - **What**: Checklist manual contra PRD §10 Definition of Done e tabela §8: (a) API key + bridge OK, (b) snapshot versionado, (c) cold start e multi-turn documentados em `async_repl.py`, (d) local-first comentado.
    - **Why**: Confirma que o spike cumpre o objetivo antes de investir na facade (Fase 1).
    - **Pattern**: Aceite em [STRATEGY.md §7](../../docs/STRATEGY.md#7-fase-0-spike) e DoD em [PRD-000 §10](../../docs/prd/PRD-000-sdk-spike.md#definition-of-done).
    - **Verify**: Todos os itens do DoD marcáveis como concluídos; demo (2) `python examples/async_repl.py` reproduzível.

  - [x] 5.5 Confirmar ausência de artefatos da Fase 1 e preparar handoff
    - **File**: — (review do repositório)
    - **What**: Verificar que **não** existem ainda: `AsyncSdkFacade`, `SessionStore`, `SessionAgentPool`, entry point `cursor-agent`, pacote instalável além do spike. Registrar em comentário no PR ou nota de handoff que [PRD-001](../../docs/prd/PRD-001-facade.md) pode iniciar.
    - **Why**: PRD-000 §5 (não-objetivos) — spike isolado sem antecipar Fase 1.
    - **Pattern**: Escopo Fase 0 vs. Fase 1 em [STRATEGY.md §6–§8](../../docs/STRATEGY.md#6-roadmap-e-dependências-entre-fases).
    - **Verify**: `rg "AsyncSdkFacade|SessionStore|SessionAgentPool" --glob '!docs/**'` não retorna implementações em `src/` ou `cursor_agent/`; apenas referências em documentação.
    - **Integration**: Desbloqueia kickoff de [PRD-001](../../docs/prd/PRD-001-facade.md) e tarefas em `engineering/tasks/tasks-PRD-001-facade.md` (quando existir).

  - [x] 5.6 Revisar PRD-001 com aprendizados do spike (retroalimentação)
    - **File**: [PRD-001-facade.md](../../docs/prd/PRD-001-facade.md) (modify existing)
    - **What**: Atualizar §7 (considerações técnicas), §9 (perguntas em aberto) e §11 (aprendizados) com evidência do spike: versão pinada real do SDK, cold start medido, conteúdo de `sdk-tools-snapshot.txt`, quirks de `launch_bridge`, timings e riscos para `AsyncSdkFacade`.
    - **Why**: Gate obrigatório [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) — PRD-001 não inicia sem retro do PRD-000.
    - **Pattern**: Checklist em [PRD-000 §11](../../docs/prd/PRD-000-sdk-spike.md#11-desenvolvimento--tdd-e-retroalimentação).
    - **Verify**: Bullets de aprendizado em PRD-001 §11 preenchidos ou explicitamente N/A com justificativa; estimativas de T2 ajustadas se cold start divergiu do previsto.
    - **Integration**: Desbloqueia implementação de [PRD-001](../../docs/prd/PRD-001-facade.md) após Tarefa 5.5 concluída.

---

## Mapeamento PRD §10 → tarefas

| PRD | Sub-tarefa neste documento |
|-----|---------------------------|
| T1.1 | 1.1 |
| T1.2 | 1.2 |
| T1.3 | 1.3 |
| T1 (tooling) | 1.6 |
| FR-1 (TDD config) | 1.7 |
| CI / DoD | 1.8 |
| T2.1 | 2.1 |
| T2.2 | 2.2 |
| T2.3 | 2.3 |
| FR-7 (local-first) | 2.4 |
| T2 (API key DX) | 2.5 |
| T3 | 3.1 |
| T4.1 | 4.2 |
| T4.2 | 4.3 |
| T4 (pacote integration) | 4.1 |
| T4 (bridge turn) | 4.4 |
| T5 | 3.2 |
| FR-6 (tool nativa) | 4.5 |
| Lockfile | 1.4 |
| Pacote tests | 1.5 |
| Gate qualidade | 5.1 |
| `/code-review` | 5.2 |
| Smoke integração | 5.3 |
| DoD review | 5.4 |
| Escopo Fase 1 | 5.5 |
| Retro PRD-001 | 5.6 |
