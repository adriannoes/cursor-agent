---
id: PRD-008
title: Memória v1
status: draft
phase: 4
depends_on: [PRD-004]
adrs:
  - ADR-002
  - ADR-010
  - ADR-016
  - ADR-022
related:
  - path: ../STRATEGY.md
    section: "12.2"
  - path: ../decisions/ADR-016-honcho-memory-path.md
    role: see-also
---

# PRD-008 — Memória v1

## 1. Introdução/Visão Geral

O cursor-agent precisa lembrar preferências e fatos do usuário entre sessões novas, sem depender do contexto efêmero do agente. A memória v1 persiste informação em arquivos locais (`MEMORY.md` e `USER.md`) e injeta um resumo no primeiro turn após `/new` ou `/resume`, conforme [ADR-010](../decisions/ADR-010-memory-v1.md).

**Problema:** cada `/new` começa sem histórico de preferências ou fatos já acumulados.

**Objetivo:** entregar memória determinística, com cap de tokens e flag de injeção, alinhada à [Fase 4 — §12.2](../STRATEGY.md#122-memória-v1) da estratégia.

## 2. Objetivos

- Ler e servir conteúdo de `~/.cursor-agent/MEMORY.md` e `USER.md` via módulo dedicado.
- Injetar até **8 KB** no primeiro turn após `/new` ou `/resume`, respeitando prioridade USER → MEMORY ([ADR-010](../decisions/ADR-010-memory-v1.md)).
- Persistir flag `memory_injected` no SQLite para evitar re-injeção no mesmo turno/sessão.
- Expor `/memory show` para inspeção do conteúdo carregado.
- Garantir que `/new` reseta a flag e `/compress` não re-injeta memória.

## 3. Histórias de Usuário

- **Como** usuário do CLI, **quero** que o agente cite minhas preferências em `USER.md` após `/new`, **para** não repetir instruções em toda sessão.
- **Como** usuário recorrente, **quero** retomar uma sessão com `/resume` e receber memória no primeiro turn, **para** continuar com contexto de fatos já registrados.
- **Como** operador, **quero** `/memory show` para ver o que será injetado, **para** depurar conteúdo sem abrir arquivos manualmente.
- **Como** desenvolvedor, **quero** comportamento testável e documentado (ordem de truncamento, cap, flag), **para** evitar regressões de tokens.

## 4. Requisitos Funcionais

1. O sistema deve implementar `memory/store.py` para ler `MEMORY.md` e `USER.md` do diretório `~/.cursor-agent/`.
2. O sistema deve aplicar cap total de **8 KB** na injeção, com até **4 KB** para `USER.md` e o restante para `MEMORY.md` ([ADR-010](../decisions/ADR-010-memory-v1.md)).
3. O sistema deve truncar do **fim** do arquivo quando uma seção exceder sua quota.
4. O sistema deve injetar memória **apenas** no primeiro turn após `/new` ou `/resume` quando `metadata.memory_injected != true`.
5. Após injeção bem-sucedida, o sistema deve setar `metadata.memory_injected = true` no SQLite.
6. O comando `/new` deve resetar `memory_injected` para permitir nova injeção.
7. O comando `/compress` **não** deve re-injetar memória (contexto já carregado via resumo do agente).
8. A injeção deve ocorrer no fluxo de `send` da facade (dependência [PRD-001](PRD-001-facade.md)), antes do turno ao SDK.
9. O comando `/memory show` deve exibir o conteúdo efetivo que seria injetado (respeitando cap e ordem de prioridade).
10. Arquivos ausentes devem ser tratados como vazios, sem erro fatal.

### Critérios de aceite (DoD)

- [ ] `memory/store.py` lê `MEMORY.md` + `USER.md`
- [ ] Injeção 8 KB no primeiro turn ([ADR-010](../decisions/ADR-010-memory-v1.md))
- [ ] `/memory show` operacional
- [ ] Flag `memory_injected` persistida e resetada conforme ADR

## 5. Fora de Escopo (Non-Goals)

- Memória semântica, FTS ou busca vetorial — ver [BACKLOG-PHASE5.md](../BACKLOG-PHASE5.md).
- Backend Honcho MCP — caminho futuro em [ADR-016](../decisions/ADR-016-honcho-memory-path.md); v1 permanece files-only.
- Atualização automática de `MEMORY.md` mid-session (mudanças no disco só aparecem após `/new`).
- Comando `/memory update` com template — backlog; fora deste PRD.
- Sincronização multi-dispositivo ou cloud dos arquivos de memória.

## 6. Considerações de Design

- `/memory show` deve usar o mesmo formatter Rich do CLI ([PRD-004](PRD-004-slash-commands.md)) para consistência visual.
- Saída deve indicar quotas aplicadas (ex.: bytes de USER vs MEMORY) quando truncamento ocorrer.
- Não expor paths absolutos sensíveis além de `~/.cursor-agent/` na mensagem ao usuário.

## 7. Considerações Técnicas

- **Dependências:** [PRD-004](PRD-004-slash-commands.md) (framework de slash commands + Rich da Fase 2 — `/memory show` e a interação com `/compress` da FR-7 exigem essa base), [PRD-001](PRD-001-facade.md) (ponto de injeção no `send`). PRD-004 já cobre transitivamente PRD-002 (store) e PRD-003 (REPL).
- **Decisão de injeção:** [ADR-010](../decisions/ADR-010-memory-v1.md) — ordem USER → MEMORY, flag `memory_injected`, sem re-injeção em `/compress`.
- **Evolução:** [ADR-016](../decisions/ADR-016-honcho-memory-path.md) define coexistência futura `files | honcho | both`; este PRD não implementa Honcho.
- **Session store:** flag `memory_injected` vive em metadata da sessão ([PRD-002](PRD-002-session-store.md)).
- **Estrutura alvo:** módulo `memory/` conforme [STRATEGY §5.2](../STRATEGY.md#52-estrutura-alvo-fase-4).

## 8. Métricas de Sucesso

- Após `/new`, o agente cita conteúdo de `USER.md` no primeiro turn (demo reproduzível).
- Injeção respeita cap 8 KB em 100% dos casos de teste com arquivos grandes.
- Flag `memory_injected` impede segunda injeção no mesmo ciclo de sessão.
- `/memory show` reflete exatamente o payload que seria enviado ao SDK.
- Testes unitários cobrem loader, cap, truncamento e integração com facade.

## 9. Questões em Aberto

- Formato exato do prefixo de injeção na mensagem (marcador visível vs. bloco silencioso)?
- `/memory show` deve ler do disco em tempo real ou do cache da última injeção?

> **Resolvido:** quota USER 4 KB + MEMORY restante (8 KB total) e truncamento do fim — [ADR-010](../decisions/ADR-010-memory-v1.md).

## 10. Tarefas de implementação

### Definition of Done

- [ ] `memory/store.py` lê `MEMORY.md` + `USER.md`
- [ ] Injeção 8 KB no primeiro turn ([ADR-010](../decisions/ADR-010-memory-v1.md))
- [ ] `/memory show` operacional
- [ ] Flag `memory_injected` persistida e resetada conforme ADR

### Tabela de tarefas

| ID | Task | Est. | Dep |
|----|------|------|-----|
| T1 | Loader + cap 8 KB (USER 4 KB + MEMORY restante) | 4h | PRD-004 |
| T2 | Injeção no facade `send` + flag `memory_injected` | 4h | PRD-001 |
| T3 | Comando `/memory show` | 2h | T1 |
| T4 | Testes (loader, cap, flag, integração facade) | 3h | T2 |

### Demo

1. `cursor-agent` → `/new` — agente cita conteúdo de `USER.md` no primeiro turn.
2. `/memory show` — exibe o mesmo payload que seria injetado (respeitando cap 8 KB).

## 11. Desenvolvimento — TDD e retroalimentação

> Processo obrigatório: [ADR-022](../decisions/ADR-022-tdd-prd-feedback-loop.md)

### TDD — testes primeiro (por FR)

| FR | Teste primeiro | Comando Verify |
|----|----------------|----------------|
| FR loader | `tests/unit/test_memory_loader.py` — cap 8 KB, USER 4 KB + MEMORY restante | `pytest tests/unit/test_memory_loader.py -v` |
| FR inject | `tests/unit/test_memory_injection.py` — primeiro turn, flag `memory_injected` | `pytest tests/unit/test_memory_injection.py -v` |
| FR command | `tests/unit/test_commands_memory.py` — `/memory show` | `pytest tests/unit/test_commands_memory.py -v` |

Ordem sugerida: loader/cap → injeção no send (fake facade) → comando `/memory show`.

### Retroalimentação

**Após concluir PRD-008:** revisar e atualizar [PRD-009](PRD-009-skills.md) (§7, §9, §11) antes de skills.

**Aprendizados a registrar:**

- [ ] Formato de prefixo de injeção escolhido
- [ ] Truncamento do fim — impacto na qualidade das respostas
- [ ] Interação com `/compress` e reset de `memory_injected`
- [ ] Caminho Honcho futuro ([ADR-016](../decisions/ADR-016-honcho-memory-path.md))
- [ ] Conflitos com skills injetadas no mesmo turn
