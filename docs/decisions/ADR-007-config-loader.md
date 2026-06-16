---
id: ADR-007
title: Config loader com pydantic-settings
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [config, phase-1]
related:
  - path: ../STRATEGY.md
    section: "8"
  - path: ../prd/PRD-002-session-store.md
    role: see-also
---

# ADR-007: Config loader com pydantic-settings

## Contexto

Config em YAML + env sem precedência documentada. Secrets como `${TELEGRAM_BOT_TOKEN}` precisam de resolução explícita.

## Decisão

1. **pydantic-settings v2** com modelos tipados (`CursorAgentConfig`, `GatewayConfig`, …).
2. **Precedência** (maior → menor):

```text
CLI flags > env (CURSOR_AGENT__*) > ~/.cursor-agent/config.yaml > defaults
```

3. **Expansão `${VAR}`** — `os.path.expandvars` após merge de fontes (padrão 12-factor).
4. Env prefix: `CURSOR_AGENT__` (nested com `__`).

> **Nota (2026-06-13):** O projeto foi renomeado de `cursor-hermes` para `cursor-agent`. O prefixo de env passou de `CURSOR_HERMES__` para `CURSOR_AGENT__` e o diretório de dados de `~/.cursor-hermes/` para `~/.cursor-agent/`. A decisão de precedência e mecanismo permanece inalterada.

## Opções consideradas

### Opção A — pydantic-settings (escolhida)

| Prós | Contras |
|------|---------|
| Tipado, validação, padrão 12-factor | Dependência extra |
| `settings_customise_sources` para ordem | |

### Opção B — PyYAML manual + os.environ

| Prós | Contras |
|------|---------|
| Leve | Sem validação; bugs silenciosos |
| Sem deps | Precedência ad hoc |

### Opção C — Env > YAML (convenção Unix clássica invertida)

| Prós | Contras |
|------|---------|
| Arquivo como base, env override em deploy | Surpreende quem espera CLI > env > file |

## Consequências

### Positivas

- Erros de config na subida, não em runtime.
- Gateway e CLI compartilham loader.

### Negativas

- Modelos Pydantic precisam evoluir com novas fases.

## Referências

- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [STRATEGY.md §8](../STRATEGY.md#8-fase-1-cli-sessões)
