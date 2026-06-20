# SDK spikes (historical)

Early investigation scripts from PRD-000 spikes. They import `cursor_sdk` directly and are **not** the recommended product API.

| Script | Purpose |
|--------|---------|
| [async_repl.py](async_repl.py) | Cold-start and multi-turn context measurement |
| [tools_list.py](tools_list.py) | Observed native tool inventory via `run.messages()` |

For public usage, start at [examples/README.md](../../../examples/README.md) and [docs/setup.md](../../setup.md).

Requires `CURSOR_API_KEY` and `cursor-sdk-bridge` on PATH. Do not commit secrets.
