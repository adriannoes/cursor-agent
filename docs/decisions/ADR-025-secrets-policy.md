---
id: ADR-025
title: Política de secrets e credenciais
status: accepted
date: 2026-06-15
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [security, secrets, logging, phase-0]
related:
  - path: ADR-018-observability-logs.md
    role: see-also
  - path: ../gateway-security.md
    role: see-also
  - path: ../DECISIONS.md
    role: index
  - path: ../../.env.example
    role: spec
  - path: ../prd/PRD-006-gateway-core.md
    role: implements
---

# ADR-025: Política de secrets e credenciais

## Contexto

O cursor-agent manipula `CURSOR_API_KEY`, `TELEGRAM_BOT_TOKEN` e expansão `${VAR}` em YAML. Logs estruturados ([ADR-018](ADR-018-observability-logs.md)) e mensagens de erro não podem vazar credenciais em disco ou terminal.

## Decisão

### 1. Origem dos secrets

| Secret | Fonte permitida | Proibido |
|--------|-----------------|----------|
| `CURSOR_API_KEY` | Variável de ambiente ou `.env` local (gitignored) | Hardcode em código, PR, snapshot |
| `TELEGRAM_BOT_TOKEN` | Env ou `${TELEGRAM_BOT_TOKEN}` em `gateway.yaml` | Commit em repositório |
| Outros tokens MCP | Env com prefixo documentado em `.env.example` | Valores reais em docs ou testes |

### 2. `.env.example`

- Contém **apenas placeholders** sem valores reais (valor vazio `CURSOR_API_KEY=` ou explícito `TELEGRAM_BOT_TOKEN=your-bot-token-here`).
- `TELEGRAM_BOT_TOKEN` entra em `.env.example` junto do gateway ([PRD-006](../prd/PRD-006-gateway-core.md)); hoje só `CURSOR_API_KEY` está documentado.
- Comentário apontando para dashboard Cursor e Telegram BotFather.
- Nunca incluir valores reais ou parcialmente mascarados de produção.

### 3. Logging e stderr

- **Nunca** logar valor completo de API keys ou bot tokens.
- Redaction obrigatória em processadores de log ([ADR-018](ADR-018-observability-logs.md)): padrões `sk-…`, `bot…`, `Bearer …` substituídos por `[REDACTED]`.
- Mensagens de erro de auth: texto genérico (“invalid or missing CURSOR_API_KEY”) sem ecoar o valor recebido.

### 4. Config e subprocess

- `pydantic-settings` e loader YAML resolvem `${VAR}` após merge; secrets não persistem em SQLite.
- Subprocess e shell hooks não recebem secrets via argv — apenas env do processo pai.

## Opções consideradas

### Opção A — Env-only + redaction (escolhida)

| Prós | Contras |
|------|---------|
| Alinha 12-factor e gateway-security | Exige disciplina em testes de integração |

### Opção B — Secrets em `~/.cursor-agent/secrets.yaml` criptografado

| Prós | Contras |
|------|---------|
| UX para múltiplos tokens | Complexidade Fase 0–4 desnecessária |

## Consequências

### Positivas

- Threat model do gateway reforçado; CI/forks seguros com skip sem key.
- ADR-018 ganha linha explícita de redaction.

### Negativas

- Debug de auth falha exige verificar env fora dos logs.

## Referências

- [ADR-018 — Observabilidade](ADR-018-observability-logs.md)
- [gateway-security.md](../gateway-security.md)
- [.env.example](../../.env.example)
