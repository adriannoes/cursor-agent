---
id: ADR-018
title: Logs JSON schema v1
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
supersedes: []
superseded_by: []
tags: [observability, logging, phase-1]
related:
  - path: ../STRATEGY.md
    section: "14.2"
  - path: ../prd/PRD-001-facade.md
    role: see-also
---

# ADR-018: Logs JSON schema v1

## Contexto

STRATEGY §14.2 lista campos sem formato. Logs precisam ser queryáveis em `~/.cursor-agent/logs/`.

## Decisão

**Formato:** uma linha JSON por evento (NDJSON), rotação diária `cursor-agent-YYYY-MM-DD.log`.

**Schema v1 (campos obrigatórios):**

```json
{
  "v": 1,
  "ts": "2026-06-12T14:30:00.000Z",
  "level": "info",
  "event": "run_finished",
  "session_id": "uuid",
  "session_key": "cli:default:abc12345",
  "agent_id": "agent-...",
  "run_id": "run-...",
  "request_id": "optional",
  "duration_ms": 1234,
  "status": "finished",
  "message": "optional human text"
}
```

**Implementação:** `structlog` com processor JSON ou `logging` + formatter custom. Sem PII no `message` por padrão.

**Redaction de secrets:** segredos (`CURSOR_API_KEY`, `TELEGRAM_BOT_TOKEN`) nunca são logados; aplicar redaction antes de serializar cada evento — política em [ADR-025](ADR-025-secrets-policy.md).

## Opções consideradas

### NDJSON schema versionado (escolhida)

| Prós | Contras |
|------|---------|
| Queryável; Loki/Datadog-ready | Schema evolui → bump `v` |

### Texto livre (rejeitada)

| Prós | Contras |
|------|---------|
| Simples | Não agregável |

### OpenTelemetry only (rejeitada para MVP)

| Prós | Contras |
|------|---------|
| Padrão industry | Overhead Fase 0–4 |

## Consequências

### Positivas

- Debug de runs e gateway com grep/jq.
- Campos alinhados a STRATEGY §14.2.

### Negativas

- Disco em logs verbosos — rotação necessária.

## Referências

- [STRATEGY.md §14.2](../STRATEGY.md#142-observabilidade)
