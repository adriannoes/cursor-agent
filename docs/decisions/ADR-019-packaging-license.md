---
id: ADR-019
title: Packaging MIT PyPI e semver 0.x
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [packaging, license, release]
related:
  - path: ../../README.md
    role: implements
  - path: ../STRATEGY.md
    section: "2.8"
---

# ADR-019: Packaging MIT, PyPI e semver `0.x`

## Contexto

README: License TBD. Distribuição e API pública não definidas.

## Decisão

1. **License:** MIT (licença permissiva padrão open source).
2. **Distribuição:** PyPI package `cursor-agent`; entry point `cursor-agent` CLI.
3. **Instalação:** `pip install cursor-agent` ou `pipx install cursor-agent`.
4. **Versioning:** semver; `0.x` até conclusão Fase 4 (MVP).
5. **API Python pública:** fora de escopo — sem `__all__` estável em `cursor_agent` ([STRATEGY §2.8](../STRATEGY.md#28-escopo-de-api-pública)).

## Opções consideradas

### MIT + PyPI + 0.x (escolhida)

| Prós | Contras |
|------|---------|
| Padrão open source | Nome pode colidir no PyPI |

### Só git install (rejeitada)

| Prós | Contras |
|------|---------|
| Sem release overhead | UX pior |

### API library estável (rejeitada)

| Prós | Contras |
|------|---------|
| Integradores terceiros | Escopo Fase 0–4 explícito contra |

## Consequências

### Positivas

- Instalação one-liner documentada.
- Expectativa clara: CLI produto, lib interna.

### Negativas

- Manutenção de releases PyPI.

## Referências

- [README.md](../../README.md)
