# ADR-007: Config loader with pydantic-settings

**Status:** Accepted

## Context

Configuration spans YAML files, environment variables, and CLI flags. Without documented precedence, operators get silent misconfiguration. Secrets such as `${TELEGRAM_BOT_TOKEN}` need explicit resolution after merge.

## Decision

1. Use **pydantic-settings v2** with typed models (`CursorAgentConfig`, `GatewayConfig`, …).
2. Apply precedence (highest wins):

```text
CLI flags > env (CURSOR_AGENT__*) > ~/.cursor-agent/config.yaml > defaults
```

3. Expand `${VAR}` with `os.path.expandvars` after merging sources (12-factor pattern).
4. Environment prefix: `CURSOR_AGENT__` (nested keys use `__`).

Gateway and CLI share the same loader module.

## Consequences

**Positive**

- Validation errors surface at startup, not mid-run.
- Typed models document allowed fields and defaults.
- Consistent override story for deploy (env) vs local dev (YAML).

**Negative**

- Pydantic models must evolve as new phases add config surface.
- Additional dependency beyond raw YAML parsing.

## See also

- [.env.example](../../.env.example) — environment variable reference
- [architecture.md](../architecture.md) — configuration section
