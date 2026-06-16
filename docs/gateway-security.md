---
id: gateway-security
title: Threat model — perfil messaging
status: accepted
date: 2026-06-12
implements:
  - ADR-001
  - ADR-014
tags: [security, messaging, gateway]
related:
  - path: decisions/ADR-001-messaging-security.md
    role: decided-by
  - path: STRATEGY.md
    section: "10"
  - path: prd/PRD-005-messaging-profile.md
    role: implements
---

# Gateway security — perfil `messaging`

> Threat model e matriz de capacidades para bots Telegram (e futuros gateways).  
> **Decisão:** [ADR-001](decisions/ADR-001-messaging-security.md)

---

## 1. Postura

| Contexto | Postura |
|----------|---------|
| CLI `coding` | Auto-approve SDK; desenvolvedor responsável |
| Gateway `messaging` | Allowlist + hooks deny + sandbox rede off + MCP vazio |
| Cron `cloud` | VM isolada; secrets via `env_vars` |

**Princípio:** messaging = **read-only sobre o workspace** — Q&A sobre código, sem mutação.

---

## 2. O que o bot messaging **pode** fazer

| Capacidade | Tool SDK | Permitido |
|------------|----------|-----------|
| Ler arquivos no `cwd` | `read` | ✅ |
| Buscar no repo | `grep`, `glob`, `ls`, `semSearch` | ✅ |
| Shell read-only | `shell` (allowlist) | ✅ `git status`, `ls`, `cat`, … |
| Responder em linguagem natural | assistant | ✅ |
| Subagent | `task` | ❌ (deny via `preToolUse`) |

---

## 3. O que o bot messaging **não pode** fazer

| Ameaça | Mitigação |
|--------|-----------|
| Escrever/editar arquivos | `preToolUse` deny `Write\|StrReplace\|Delete\|Task` |
| Shell destrutivo (`rm -rf`, `curl\|bash`) | `beforeShellExecution` denylist |
| MCP arbitrário | `mcp_servers: {}` + `beforeMCPExecution` deny |
| Ler secrets | `beforeReadFile` deny `.env`, `~/.ssh`, `*.pem` |
| Exfiltração rede | `sandbox_options.enabled: true` |
| Acesso sem allowlist | `gateway/auth.py` — Telegram `allowed_users` |

---

## 4. Hooks instalados

Origem: `~/.cursor-agent/hooks/messaging/` → copiados para `cwd` na subida do gateway.

```text
hooks/
├── hooks.json
├── pre-tool-deny-write.sh
├── shell-gate.sh
├── mcp-deny.sh
└── read-sensitive-deny.sh
```

Ver implementação na Fase 2b ([PRD-005](prd/PRD-005-messaging-profile.md)).

---

## 5. Limitações conhecidas

1. **Hooks são file-based** — não programáticos por run ([Cursor SDK](https://cursor.com/docs/sdk/python)).
2. **Sandbox não bloqueia file edit** — depende de `preToolUse`.
3. **Read de código** pode expor lógica de negócio — aceito para Q&A; deny paths sensíveis.
4. **Windows:** hooks podem ser flaky — testar em alvo primário Linux/macOS VPS.
5. **Classifier auto-review** do SDK é conveniência, não security boundary.

---

## 6. Teste de aceite (Fase 2b)

| # | Cenário | Resultado esperado |
|---|---------|-------------------|
| 1 | Pedir `rm -rf /` via CLI perfil messaging | Hook bloqueia |
| 2 | Pedir editar `README.md` | `preToolUse` deny |
| 3 | Pedir `git status` | Permite |
| 4 | Pedir ler `.env` | `beforeReadFile` deny |
| 5 | Gateway com `tool_profile: coding` | Processo recusa subir |

---

## 7. Referências

- [ADR-001](decisions/ADR-001-messaging-security.md)
- [ADR-014](decisions/ADR-014-tool-profiles-mvp.md)
- [STRATEGY.md §10](STRATEGY.md#10-fase-2b-perfil-messaging-gate-do-gateway)
- [Cursor Hooks](https://cursor.com/docs/hooks)
