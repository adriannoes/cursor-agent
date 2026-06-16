---
id: async-sdk-facade-contract
title: Contrato AsyncSdkFacade
status: accepted
date: 2026-06-12
implements:
  - ADR-002
tags: [architecture, facade, api]
related:
  - path: ../decisions/ADR-002-async-sdk-facade.md
    role: decided-by
  - path: ../decisions/ADR-024-error-taxonomy-retry.md
    role: see-also
  - path: ../decisions/ADR-008-agent-busy-gateway.md
    role: see-also
  - path: ../STRATEGY.md
    section: "3.2"
  - path: ../prd/PRD-001-facade.md
    role: implements
---

# Contrato `AsyncSdkFacade`

> Especificação técnica da facade — único módulo que importa `cursor_sdk`.  
> **Decisão:** [ADR-002](../decisions/ADR-002-async-sdk-facade.md)

---

## 1. Tipos

```python
from typing import Protocol, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum
import logging

class RunStatus(str, Enum):
    FINISHED = "finished"
    ERROR = "error"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: RunStatus
    text: str | None
    usage: dict | None  # tokens se disponível

@dataclass(frozen=True)
class StreamCallbacks:
    on_assistant_text: Callable[[str], Awaitable[None]] | None = None
    on_tool_start: Callable[[str, dict], Awaitable[None]] | None = None
    on_tool_end: Callable[[str, dict], Awaitable[None]] | None = None

class AgentBusyError(Exception):
    """Run ativo no mesmo agent; ver SessionAgentPool — não levantado pela facade."""

class SdkFacade(Protocol):
    async def create_agent(
        self,
        *,
        workspace: str,
        model: str = "composer-2.5",
        tool_profile: str = "coding",
        runtime_mode: str = "local",
    ) -> str: ...  # returns agent_id

    async def resume_agent(
        self,
        agent_id: str,
        *,
        workspace: str,
        model: str | None = None,
        tool_profile: str | None = None,
    ) -> str: ...  # returns handle key internal

    async def send(
        self,
        agent_id: str,
        message: str,
        *,
        callbacks: StreamCallbacks | None = None,
    ) -> RunResult: ...

    async def cancel(self, agent_id: str) -> None: ...

    async def close(self) -> None: ...
```

---

## 2. Construtor e lifecycle

### 2.1 Assinatura do construtor

```python
class AsyncSdkFacade:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        bridge_options: dict | None = None,
        logger: logging.Logger | None = None,
    ) -> None: ...
```

| Parâmetro | Origem | Comportamento |
|-----------|--------|---------------|
| `api_key` | Argumento ou `os.environ["CURSOR_API_KEY"]` | Obrigatório antes do primeiro `create_agent`; nunca logado ([ADR-025](../decisions/ADR-025-secrets-policy.md)) |
| `bridge_options` | Argumento opcional | Repassado a `AsyncClient.launch_bridge` no `__aenter__` (ex.: `runtime_mode`, timeouts, log level do SDK) |
| `logger` | Argumento ou logger padrão do módulo | Injeção para testes; emite eventos NDJSON em `send` ([ADR-018](../decisions/ADR-018-observability-logs.md)) |

O construtor é puro (sem I/O); o `AsyncClient` e a bridge sobem no `__aenter__` (ver §2.2).

### 2.2 Lifecycle

| Regra | Detalhe |
|-------|---------|
| Um `AsyncClient` por processo | `async with AsyncSdkFacade(...)` no CLI/gateway |
| Bridge | `AsyncClient.launch_bridge`; criado no `__aenter__` |
| Dispose | `close()` no SIGTERM ([ADR-021](../decisions/ADR-021-graceful-shutdown.md)) |
| MCP no resume | Re-injetar `mcp_servers` do perfil atual — inline não persiste no SDK |

---

## 3. Erros e exit codes

| Situação | Exceção / status | Exit CLI |
|----------|------------------|----------|
| Auth, config, rede (run não iniciou) | `CursorAgentError` | 1 |
| Run iniciou e falhou | `RunResult.status == ERROR` | 2 |
| Sucesso | `FINISHED` | 0 |
| Cancelado | `CANCELLED` | 0 |

**Retry:** só se `CursorAgentError.is_retryable`; honrar `retry_after` antes de backoff exponencial (max 3 tentativas) — [ADR-024](../decisions/ADR-024-error-taxonomy-retry.md).

---

## 4. Cancelamento

| Cenário | Comportamento |
|---------|---------------|
| `cancel(agent_id)` durante `send` ativo | Propaga cancel ao SDK; `send` retorna `RunResult` com `status=CANCELLED` |
| `cancel` sem run ativo | No-op ou log `debug`; não levanta |
| Race: `send` completa vs `cancel` | Primeiro a completar vence; se cancel ganhar, status `CANCELLED` |
| Callbacks após cancel | `on_assistant_text` / tool callbacks **não** são invocados após cancel confirmado |
| Mapeamento CLI | Exit code **0** para `CANCELLED` (usuário ou `/stop`); timeout do chamador também resolve em `CANCELLED` |

A facade **não** levanta `AgentBusyError` em nenhum cenário ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md)).

---

## 5. Streaming (`StreamCallbacks`)

| Regra | Detalhe |
|-------|---------|
| `on_assistant_text` | Recebe **delta** (chunk novo), não texto acumulado — caller concatena se precisar do total |
| Ordem | Deltas na ordem do SDK; `on_tool_start` antes de `on_tool_end` para a mesma tool call |
| Erro em callback | Exceção do callback aborta `send` e propaga; run pode ficar `ERROR` no SDK |
| Sem callbacks | `RunResult.text` contém o texto completo (concatenação ordenada dos deltas) ao fim do run |

---

## 6. Resume

Ao chamar `resume_agent(agent_id, *, workspace, model=..., tool_profile=...)`:

1. **`workspace`** deve coincidir com o runtime esperado ([ADR-003](../decisions/ADR-003-cross-runtime-resume.md)); divergência é responsabilidade do chamador.
2. **`model`** e **`tool_profile`** opcionais — quando informados, aplicam-se ao agente retomado; quando `None`, mantêm os valores originais.
3. **`mcp_servers`** do perfil atual são **re-injetados** inline no resume (config MCP não persiste no checkpoint SDK); trocar `tool_profile` re-injeta os servers do novo perfil.
4. Falha de `agent_id` inválido → `InvalidAgentError` ([ADR-024](../decisions/ADR-024-error-taxonomy-retry.md)); camada CLI sugere `/new`.

---

## 7. `agent_id` inválido

`resume_agent` falha → propagar erro; SessionStore sugere `/new` na camada CLI/gateway.

---

## 8. `FakeSdkFacade` (testes)

Implementação in-memory:

- Mapa `agent_id → messages[]`
- `send` append user msg, retorna texto fixo ou scripted
- Gancho de run em andamento: ex. `asyncio.Event` setado no início de `send` e liberado no fim — permite ao `SessionAgentPool` detectar lock ocupado e levantar `AgentBusyError` via `try_acquire` em testes
- **A facade fake nunca levanta `AgentBusyError`** — quem levanta é o `SessionAgentPool` ([ADR-008](../decisions/ADR-008-agent-busy-gateway.md))
- Sem bridge real

Ver [ADR-005](../decisions/ADR-005-testing-strategy.md) e [PRD-001 FR-8](../prd/PRD-001-facade.md).

---

## 9. Logging

Emitir eventos conforme [ADR-018](../decisions/ADR-018-observability-logs.md) em `send` start/end. Redaction de secrets conforme [ADR-025](../decisions/ADR-025-secrets-policy.md).

---

## 10. Referências

- [ADR-002](../decisions/ADR-002-async-sdk-facade.md)
- [ADR-024](../decisions/ADR-024-error-taxonomy-retry.md)
- [Cursor Python SDK](https://cursor.com/docs/sdk/python)
- [prd/PRD-001-facade.md](../prd/PRD-001-facade.md)
