---
id: ADR-012
title: Chunking Telegram 4096 e typing indicator
status: accepted
date: 2026-06-12
deciders: [cursor-agent team]
superseded_by: []
supersedes: []
tags: [gateway, telegram, ux, phase-3]
related:
  - path: ../STRATEGY.md
    section: "11"
  - path: ../prd/PRD-007-telegram-adapter.md
    role: implements
  - path: ADR-006-telegram-library.md
    role: see-also
---

# ADR-012: Chunking Telegram 4096 e typing indicator

## Contexto

Respostas do agente podem exceder 4096 caracteres (limite Telegram). Streaming do SDK precisa mapear para entrega no chat.

## Decisão

1. **`send_chat_action(typing)`** durante run ativo (refresh a cada ~5s).
2. **Buffer** texto do assistant durante stream.
3. **Ao final** (ou buffer > 3800 chars): split em chunks ≤ 4096, preferindo quebras em `\n\n` ou `\n`.
4. **`parse_mode=HTML`** com escape de conteúdo do modelo.
5. Não usar `edit_message_text` para streaming (rate limits; limite 4096).

## Opções consideradas

### Opção A — Buffer + split + typing (escolhida)

| Prós | Contras |
|------|---------|
| Simples; sem deps extras | Texto parcial não visível durante run |
| Respeita limite API | Markdown pode quebrar no meio |

### Opção B — edit_message_text streaming

| Prós | Contras |
|------|---------|
| Sensação de digitação ao vivo | Rate limit; >4096 impossível |
| | Alto custo de API |

### Opção C — Só typing + mensagem única no final

| Prós | Contras |
|------|---------|
| Mínimo | Falha se >4096 sem split |

## Consequências

### Positivas

- Entrega confiável de respostas longas.
- Feedback visual durante runs lentos.

### Negativas

- Usuário não vê tokens chegando em tempo real no Telegram.

## Referências

- [Telegram Bot API — sendMessage](https://core.telegram.org/bots/api#sendmessage)
- [prd/PRD-007-telegram-adapter.md](../prd/PRD-007-telegram-adapter.md)
