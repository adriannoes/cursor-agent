# Tarefas — PRD-004 Slash commands e display Rich

> **PRD:** [PRD-004-slash-commands.md](../../docs/prd/PRD-004-slash-commands.md)  
> **ADRs:** [ADR-011](../../docs/decisions/ADR-011-compress-flow.md) (`/compress` saga), [ADR-013](../../docs/decisions/ADR-013-slash-commands-skills.md) (command routing), [ADR-018](../../docs/decisions/ADR-018-observability-logs.md) (NDJSON logs), [ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md) (TDD + retro).  
> **Escopo deste documento:** Fase 2 — slash commands P0/P1/P2, Rich display, `/compress`, command observability, and handoff to PRD-005.  
> **Status:** Fase 2 completa — sub-tasks prontas para implementação.

## Relevant Files

- `pyproject.toml` — Declares `rich` as a direct runtime dependency for PRD-004 display work.
- `uv.lock` — Locks the explicit `rich` runtime dependency added for PRD-004 display work.
- `README.md` — Documents optional `.cursor/hooks.json` template and auto-approve risk required by PRD-004.
- `docs/prompts/compress.txt` — Versioned prompt consumed by the `/compress` saga.
- `docs/prd/PRD-005-messaging-profile.md` — Next PRD in the ADR-022 retrospective chain; must receive PRD-004 learnings before PRD-005 starts.
- `engineering/tasks/README.md` — Master task index status for PRD-004.
- `src/cursor_agent/cli/repl_session.py` — Existing REPL loop; replace only the inline slash branch with the router while preserving free-text sends.
- `src/cursor_agent/cli/app.py` — Production CLI startup wiring for Rich display callbacks.
- `src/cursor_agent/cli/startup.py` — Threads local SDK setting sources into the real facade.
- `src/cursor_agent/cli/command_router.py` — New `CommandRouter`, `CommandContext`, `ReplState`, registry, parsing, and deterministic resolution.
- `src/cursor_agent/cli/slash_commands.py` — Existing `/new` and `/resume` handlers; register them as built-ins and add related handlers where appropriate.
- `src/cursor_agent/cli/rich_display.py` — New Rich-backed renderer or adapter for assistant deltas and tool badges.
- `src/cursor_agent/cli/stream_renderer.py` — Existing stream callback builder; extend or wrap to feed Rich without breaking the two-sink contract.
- `src/cursor_agent/cli/compress.py` — New `/compress` saga implementation, including status updates and rollback.
- `src/cursor_agent/cli/error_display.py` — Reuse `format_error` from command handlers to avoid import cycles.
- `src/cursor_agent/cli/exit_codes.py` — Reuse existing `RunStatus` to process exit-code mapping; `/stop` should map to `CANCELLED`.
- `src/cursor_agent/sdk_facade.py` — Existing facade contracts for `cancel`, streaming callbacks, `RunResult`, `RunStatus`, and fake facade tests.
- `src/cursor_agent/pool.py` — Existing `SessionAgentPool.send(..., blocking=True)` path used by free-text, `/retry`, and cancellation behavior.
- `src/cursor_agent/sessions/store.py` — `SessionStore` persistence used by `/resume`, `/compress`, `/usage`, and metadata status updates.
- `src/cursor_agent/sessions/models.py` — `SessionRecord` and metadata shape consumed by command handlers.
- `src/cursor_agent/facade_logging.py` — Existing structured log support; add command-level NDJSON events here or through the established logging boundary.
- `tests/unit/cli_repl_helpers.py` — Reuse `drive_repl`, spy pools, seeded sessions, and line readers from PRD-003.
- `tests/unit/conftest.py` — Reuse shared `config` fixture and fake configuration patterns.
- `tests/unit/test_commands_router.py` — New router tests for registration, aliases, reserved names, and resolution order.
- `tests/unit/test_commands_handlers.py` — New handler tests for P0/P1/P2 commands through the REPL helpers.
- `tests/unit/test_commands_compress.py` — New `/compress` happy-path and rollback tests with `FakeSdkFacade`.
- `tests/unit/test_display_rich.py` — New Rich renderer tests with mocked console and badge lifecycle assertions.
- `tests/unit/test_cli_entry.py` — Production CLI entry wiring tests for Rich callback injection.
- `tests/unit/test_cli_bootstrap.py` — REPL bootstrap regression tests updated for implemented slash commands.
- `tests/unit/test_cli_repl.py` — REPL regression tests for router-backed core slash command behavior.
- `tests/unit/test_cli_streaming.py` — Existing two-sink regression tests; extend only if Rich changes callback behavior.
- `tests/unit/test_facade.py` — Facade tests for local `setting_sources` and logging helpers.
- `tests/unit/test_session_store.py` — Store tests for same-row `agent_id` replacement.
- `tests/unit/test_cli_exit_codes.py` — Existing exit-code tests; extend for cancellation if needed.

### Notes

- **TDD ([ADR-022](../../docs/decisions/ADR-022-tdd-prd-feedback-loop.md)):** Sub-tasks in Phase 2 must put the pytest `Verify` command before production changes for each functional requirement.
- PRD-004 builds on PRD-003. Do not rewrite the REPL loop: replace the inline slash-command branch and keep free-text turns in `run_repl`.
- Preserve the PRD-003 output contract: `writer` handles line-oriented status/errors/help, while `stream_writer` handles inline assistant deltas.
- Preserve the PRD-003 session invariant: every free-text or retry send must pass `session_id=active_session_id`.
- Reuse `SessionStore`, `SessionAgentPool`, `FakeSdkFacade`, and existing CLI test helpers from PRD-001 through PRD-003.
- Treat profile `messaging`, hooks, gateway runners, and security enforcement as PRD-005/006 handoff items, not PRD-004 implementation scope.
- Add command-level NDJSON events without logging prompt bodies, secrets, tool arguments, or other PII by default.
- Local no-API-key gate remains:

  ```bash
  ruff check src tests
  ruff format --check src tests
  mypy --strict src
  pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"
  ```

## Tasks

- [x] **1.0 Add Rich dependency and display boundary** — PRD T0 / FR-8

  **Trigger / entry point:** PRD-004 display work starts and needs Rich as an explicit project dependency before renderer code is introduced.  
  **Enables:** Rich streaming implementation, tool badges, and isolated renderer tests in Task 4.0.  
  **Depends on:** PRD-003 merged; current `stream_renderer.py` two-sink behavior.

  **Acceptance criteria:**
  - `rich` is declared as a direct runtime dependency in project metadata.
  - A project-owned display boundary exists so `repl_session.py` does not depend directly on Rich internals.
  - Existing streaming tests still prove assistant deltas do not go through the line-oriented writer.

  - [x] 1.1 Add a failing display-boundary test for assistant text and tool badges
    - **File**: `tests/unit/test_display_rich.py` (create new)
    - **What**: Add tests that instantiate the planned display boundary with a mocked or fake console, emit assistant text, emit tool start/end events, and assert the renderer records text separately from line-oriented status output.
    - **Why**: FR-8 needs a Rich-backed display that remains testable without a real terminal.
    - **Pattern**: Follow `tests/unit/test_cli_streaming.py` for sink separation and `StreamCallbacks` usage.
    - **Verify**: `pytest tests/unit/test_display_rich.py -v` must fail before `src/cursor_agent/cli/rich_display.py` exists, then pass after implementation.

  - [x] 1.2 Declare `rich` as a direct runtime dependency
    - **File**: `pyproject.toml` (modify existing)
    - **What**: Add `rich` to `[project].dependencies` using the project dependency workflow; do not rely on Typer's transitive dependency.
    - **Why**: PRD-004 renders Rich UI directly, so the project must own the dependency explicitly.
    - **Pattern**: Keep dependency declarations in `pyproject.toml` with the existing sorted/simple style.
    - **Verify**: `python -m pytest tests/test_pyproject_config.py -v` passes and project metadata includes `rich`.

  - [x] 1.3 Create a small Rich display adapter
    - **File**: `src/cursor_agent/cli/rich_display.py` (create new)
    - **What**: Define a typed, injectable adapter that accepts assistant deltas and tool lifecycle events while hiding Rich-specific objects from `repl_session.py`.
    - **Why**: Keeps the REPL loop focused on orchestration and makes display behavior independently testable.
    - **Pattern**: Follow the small-module style in `src/cursor_agent/cli/stream_renderer.py`; keep imports at module top.
    - **Verify**: `pytest tests/unit/test_display_rich.py -v` passes.

- [x] **2.0 Introduce CommandRouter, ReplState, and deterministic resolution** — PRD T1 / FR-1, FR-2

  **Trigger / entry point:** User input in `run_repl` starts with `/`, replacing the current inline slash branch.  
  **Enables:** P0/P1/P2 command handlers, skill namespace stubs, alias handling, and command observability.  
  **Depends on:** Existing PRD-003 REPL loop, `slash_commands.py`, `error_display.py`, and ADR-013.

  **Acceptance criteria:**
  - `CommandRouter` registers handlers by command name without the `/` prefix.
  - Resolution order is built-in reserved command, skills stub, then friendly unknown slash handling / free-message fallthrough as specified by ADR-013.
  - `/new`, `/resume`, and `/quit` behavior migrates from inline REPL logic without changing existing user-visible behavior.
  - `ReplState` stores active session id, last user message, last run status/result context, and any model override without hidden globals.

  - [x] 2.1 Add failing router tests for parsing, reserved names, aliases, and unknown slash input
    - **File**: `tests/unit/test_commands_router.py` (create new)
    - **What**: Cover `/name arg` parsing, registration by name without `/`, `/reset` alias resolution, ADR-013 reserved command names, built-in precedence, skills stub fallback, and unknown slash user feedback.
    - **Why**: FR-1 and FR-2 require deterministic command resolution before handlers are wired into the REPL.
    - **Pattern**: Use pure unit tests like `tests/unit/test_cli_exit_codes.py`; avoid SDK or store setup for router-only behavior.
    - **Verify**: `pytest tests/unit/test_commands_router.py -v` must fail before `command_router.py` exists, then pass.

  - [x] 2.2 Create command state and context dataclasses
    - **File**: `src/cursor_agent/cli/command_router.py` (create new)
    - **What**: Add typed `ReplState`, `CommandContext`, command result types, reserved command constants, and handler protocol/signature.
    - **Why**: Handlers need access to pool/store/config/facade/session state without hidden globals or import cycles.
    - **Pattern**: Follow PRD-004 §7 `ReplState` and the keyword-only style in `src/cursor_agent/cli/slash_commands.py`.
    - **Verify**: `pytest tests/unit/test_commands_router.py -k "state or context" -v` passes.

  - [x] 2.3 Implement `CommandRouter` parse/register/resolve behavior
    - **File**: `src/cursor_agent/cli/command_router.py` (modify existing)
    - **What**: Implement registration, alias support, `/` parsing, built-in resolution, skills stub returning no match, and friendly unknown-command results.
    - **Why**: Replaces the hardcoded slash branch with a single deterministic routing path.
    - **Pattern**: Follow ADR-013 resolution order and keep skill loading as an empty stub until PRD-009.
    - **Verify**: `pytest tests/unit/test_commands_router.py -v` passes.

  - [x] 2.4 Migrate existing `/new`, `/resume`, and `/quit` dispatch through the router
    - **File**: `src/cursor_agent/cli/repl_session.py` (modify existing)
    - **What**: Replace only the inline slash branch with router dispatch, preserving auto-resume, free-text `pool.send`, `stream_writer`, `writer`, in-loop error behavior, and final status return.
    - **Why**: PRD-004 builds on PRD-003 and should not rewrite working REPL behavior.
    - **Pattern**: Preserve the contracts documented in `docs/prd/PRD-004-slash-commands.md` §7 and existing tests in `test_cli_repl.py`.
    - **Verify**: `pytest tests/unit/test_cli_repl.py tests/unit/test_cli_bootstrap.py tests/unit/test_commands_router.py -v` passes.

- [x] **3.0 Implement P0/P1/P2 command handlers and command logs** — PRD T2 / FR-3, FR-4, FR-5, FR-9, FR-10

  **Trigger / entry point:** Router resolves a supported built-in command.  
  **Enables:** User-facing CLI control through `/help`, `/reset`, `/stop`, `/model`, `/retry`, `/usage`, and the `/compress` entry point.  
  **Depends on:** Task 2.0 router/context/state; existing facade, pool, store, and error-display contracts.

  **Acceptance criteria:**
  - P0 commands `/new`, `/reset`, `/resume [id]`, `/help`, and `/quit` are registered and covered by unit tests.
  - P1 commands `/stop` and `/model [id]` call the existing facade/pool/store boundaries and surface clear errors.
  - P2 commands `/retry` and `/usage` are implemented after last-turn state is captured; `/compress` remains reserved here and is wired to the saga in Task 5.6.
  - `/help` lists P0/P1/P2 commands and documents `/reset` as an alias of `/new`.
  - Command-level NDJSON events follow ADR-018 fields and avoid PII.
  - `setting_sources: ["project", "user"]` is configured through the facade path required by PRD-004.

  - [x] 3.1 Add failing handler tests for P0 commands
    - **File**: `tests/unit/test_commands_handlers.py` (create new)
    - **What**: Cover `/new`, `/reset`, `/resume [id]`, `/help`, and `/quit` via `drive_repl`, asserting writer output and active-session behavior.
    - **Why**: FR-3 is user-visible and should preserve PRD-003 behavior while adding alias/help coverage.
    - **Pattern**: Reuse `tests/unit/cli_repl_helpers.py`, `CreateAgentTrackingFacade`, and existing REPL assertions from `tests/unit/test_cli_repl.py`.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py -k "p0 or help or reset" -v` must fail before handlers are implemented, then pass.

  - [x] 3.2 Register and implement P0 handlers
    - **File**: `src/cursor_agent/cli/slash_commands.py` (modify existing)
    - **What**: Register existing `handle_new` and `handle_resume`, add `/reset` alias to `/new`, add `/help`, and make `/quit` return a router sentinel instead of exiting the process.
    - **Why**: P0 commands are the stable CLI control surface users already depend on.
    - **Pattern**: Keep handler dependencies injected through `CommandContext`; reuse `format_error` from `error_display.py`.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py -k "p0 or help or reset" -v` passes.

  - [x] 3.3 Persist last user message and last result context in `ReplState`
    - **File**: `src/cursor_agent/cli/repl_session.py` (modify existing)
    - **What**: Update `ReplState.last_user_message`, `last_status`, and last result/usage context after free-text turns, without writing assistant deltas to `writer`.
    - **Why**: `/retry`, `/usage`, and exit-code behavior depend on accurate latest-turn state.
    - **Pattern**: Keep the existing `RunStatus.ERROR` notice and return value semantics from PRD-003.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py tests/unit/test_cli_exit_codes.py -k "retry or usage or exit" -v` must fail before state capture is implemented, then pass.

  - [x] 3.4 Add failing handler tests for P1/P2 commands except `/compress` internals
    - **File**: `tests/unit/test_commands_handlers.py` (modify existing)
    - **What**: Cover `/stop`, `/model [id]`, `/retry`, and `/usage`; assert `/retry` does not send when no previous message exists and `/usage` reports no data clearly.
    - **Why**: FR-4 and FR-5 add operational controls that must remain deterministic with fakes.
    - **Pattern**: Reuse `SendSpyPool`, `FakeSdkFacade`, and `SessionStore` seeded sessions; keep `/compress` wiring and saga assertions in Task 5.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py -k "stop or model or retry or usage" -v` must fail first, then pass.

  - [x] 3.5 Implement `/stop`, `/model`, `/retry`, and `/usage`
    - **File**: `src/cursor_agent/cli/slash_commands.py` (modify existing)
    - **What**: Resolve active sessions through the store/pool, call `facade.cancel(agent_id)` for `/stop`, store in-memory model override on `ReplState`, resend `last_user_message` for `/retry`, and show last-run usage when available.
    - **Why**: Gives users operational control without introducing gateway or messaging behavior early.
    - **Pattern**: Use `pool.send(..., session_id=state.active_session_id, blocking=True)` for retry and clear user-facing messages for empty state.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py -v` passes.

  - [x] 3.6 Add failing command-level NDJSON logging tests
    - **File**: `tests/unit/test_commands_handlers.py` (modify existing)
    - **What**: Assert command start/end events include schema version, event name, command name, session id/key, outcome, and duration without prompt bodies or tool arguments.
    - **Why**: ADR-018 command events need test-first coverage before logging helpers are added.
    - **Pattern**: Follow existing facade logging assertions in `tests/unit/test_facade.py`.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py -k "command_log" -v` must fail before helpers/wiring exist, then pass.

  - [x] 3.7 Add command-level NDJSON logging helpers
    - **File**: `src/cursor_agent/facade_logging.py` (modify existing)
    - **What**: Add command start/end logging helpers with command name, session id/key, optional agent id, duration, and outcome, while redacting secrets and avoiding prompt bodies/tool args.
    - **Why**: ADR-018 requires queryable command events in addition to existing send lifecycle logs.
    - **Pattern**: Extend existing `emit_send_start` / `emit_send_end` style and JSON schema v1.
    - **Verify**: `pytest tests/unit/test_facade.py tests/unit/test_commands_handlers.py -k "log or command" -v` passes.

  - [x] 3.8 Wire command logging through router or handler execution
    - **File**: `src/cursor_agent/cli/command_router.py` (modify existing)
    - **What**: Emit command start/end events around built-in handler execution, including success, user-facing failure, and quit outcomes.
    - **Why**: Logging belongs at the command execution boundary, not inside each handler's business logic.
    - **Pattern**: Use `CommandContext` for session identifiers and keep message bodies out of logs.
    - **Verify**: `pytest tests/unit/test_commands_router.py tests/unit/test_commands_handlers.py -k "log or command" -v` passes.

  - [x] 3.9 Add failing tests for SDK local setting sources
    - **File**: `tests/unit/test_facade.py` (modify existing)
    - **What**: Assert `AsyncSdkFacade` create/resume local options receive `setting_sources=["project", "user"]` from `CursorAgentConfig` and do not use `"all"` or ambient defaults.
    - **Why**: FR-9 requires explicit project/user settings; Python SDK defaults to no local `setting_sources`.
    - **Pattern**: Follow existing facade option-shape tests and `tests/unit/test_config_loader.py`.
    - **Verify**: `pytest tests/unit/test_config_loader.py tests/unit/test_facade.py -k "setting_sources or local" -v` must fail before facade/startup wiring exists, then pass.

  - [x] 3.10 Pass SDK local setting sources through startup/create/resume paths
    - **File**: `src/cursor_agent/cli/startup.py`, `src/cursor_agent/sdk_facade.py` (modify existing)
    - **What**: Thread `config.runtime.local.setting_sources` into the SDK `LocalAgentOptions` used by create/resume for local runtime; keep cloud behavior unchanged because local setting sources do not apply to cloud agents.
    - **Why**: FR-9 requires project and user rules/MCP settings to load in the local CLI.
    - **Pattern**: Follow `LocalRuntimeConfig.setting_sources` in `src/cursor_agent/config/loader.py` and the Cursor SDK guidance that setting sources live under `local`.
    - **Verify**: `pytest tests/unit/test_config_loader.py tests/unit/test_facade.py -k "setting_sources or local" -v` passes.

- [x] **4.0 Render Rich streaming and tool badges** — PRD T3 / FR-8

  **Trigger / entry point:** A free-text turn or command-triggered agent run starts streaming SDK updates.  
  **Enables:** Hermes-like terminal feedback with assistant text and tool lifecycle badges.  
  **Depends on:** Task 1.0 display boundary; existing `StreamCallbacks.on_assistant_text`, `on_tool_start`, and `on_tool_end`.

  **Acceptance criteria:**
  - Assistant text streams in real time through the existing inline stream sink contract.
  - Tool badge rendering shows tool name and state without dumping full arguments by default.
  - Rich rendering is testable with a mocked console and does not require a real terminal.
  - Status lines, help output, and formatted errors continue to use the injected `writer`.

  - [x] 4.1 Add failing stream callback tests for tool badge lifecycle
    - **File**: `tests/unit/test_display_rich.py` (modify existing)
    - **What**: Assert that `on_tool_start` and `on_tool_end` update badge state using only tool names and state, not raw arguments.
    - **Why**: FR-8 requires tool visibility while avoiding accidental terminal leakage of sensitive arguments.
    - **Pattern**: Use `FakeSdkFacade(scripted_tool_events=...)` as in existing streaming tests.
    - **Verify**: `pytest tests/unit/test_display_rich.py -k "tool" -v` must fail before stream callbacks are wired, then pass.

  - [x] 4.2 Extend stream callback construction for Rich display events
    - **File**: `src/cursor_agent/cli/stream_renderer.py` (modify existing)
    - **What**: Add a way to build `StreamCallbacks` that forwards assistant deltas and tool lifecycle events to the display adapter while preserving the existing text-only writer path.
    - **Why**: Rich should enhance streaming without regressing PRD-003 two-sink behavior.
    - **Pattern**: Keep `build_stream_callbacks(writer)` compatible with current tests; add a new explicit builder if needed.
    - **Verify**: `pytest tests/unit/test_cli_streaming.py tests/unit/test_display_rich.py -v` passes.

  - [x] 4.3 Wire Rich display into production CLI startup
    - **File**: `src/cursor_agent/cli/app.py` (modify existing)
    - **What**: Use the Rich display boundary for production streaming while keeping `typer.echo` or equivalent line output for status/help/errors.
    - **Why**: Users should see richer streaming during normal `cursor-agent` runs, not only in tests.
    - **Pattern**: Preserve `_echo_delta` semantics or replace it through the adapter without changing `run_repl`'s public contract unnecessarily.
    - **Verify**: `pytest tests/unit/test_cli_entry.py tests/unit/test_cli_streaming.py tests/unit/test_display_rich.py -v` passes.

- [x] **5.0 Implement `/compress` saga with rollback** — PRD T4 / FR-6, FR-7

  **Trigger / entry point:** User enters `/compress` during a session with an active session id.  
  **Enables:** Long-running sessions to reduce context while preserving the logical `session id`; provides implementation learnings for PRD-005.  
  **Depends on:** Task 3.0 command entry point; `SessionStore.update_metadata`; versioned prompt in `docs/prompts/compress.txt`; ADR-011.

  **Acceptance criteria:**
  - `/compress` sets `metadata.status = "compressing"` before starting the saga and clears it on completion or failure.
  - Successful compression keeps the same session row/id, updates to the new `agent_id`, and sends the generated summary as the first message to the new agent.
  - Failure keeps the previous `agent_id`, clears `metadata.status`, and displays an actionable error through the injected writer.
  - Tests cover happy path, mid-flight failure, and rollback behavior with fakes and no `CURSOR_API_KEY`.

  - [x] 5.1 Add failing store tests for replacing `agent_id` on an existing session
    - **File**: `tests/unit/test_session_store.py` (modify existing)
    - **What**: Cover a new store method that updates the `agent_id` for an existing session id and returns the refreshed `SessionRecord`.
    - **Why**: ADR-011 requires `/compress` to keep the same SQLite row while switching to a new SDK agent id.
    - **Pattern**: Follow existing `update_title` and `update_metadata` tests and error-message style.
    - **Verify**: `pytest tests/unit/test_session_store.py -k "agent_id" -v` must fail before the store method exists, then pass.

  - [x] 5.2 Add a typed store method for `agent_id` replacement
    - **File**: `src/cursor_agent/sessions/store.py` (modify existing)
    - **What**: Implement `update_agent_id(session_id, agent_id)` or an equivalently specific method using parameterized SQL, validation, and refreshed row mapping.
    - **Why**: `/compress` must not create a second logical session row.
    - **Pattern**: Mirror `update_title` and include offending values in errors.
    - **Verify**: `pytest tests/unit/test_session_store.py -k "agent_id" -v` passes.

  - [x] 5.3 Add failing `/compress` saga tests for success and rollback
    - **File**: `tests/unit/test_commands_compress.py` (create new)
    - **What**: Cover active-session validation, `metadata.status = "compressing"`, summary generation, same session id with new agent id, summary sent to new agent, and rollback on mid-flight failure.
    - **Why**: FR-6 and FR-7 are stateful and must be validated before production implementation.
    - **Pattern**: Reuse `FakeSdkFacade`, seeded `SessionStore`, and PRD-003 REPL helpers where useful.
    - **Verify**: `pytest tests/unit/test_commands_compress.py -v` must fail before `cli/compress.py` exists, then pass.

  - [x] 5.4 Implement compress prompt loading
    - **File**: `src/cursor_agent/cli/compress.py` (create new)
    - **What**: Load the versioned prompt from `docs/prompts/compress.txt` or a packaged equivalent through a stable project-owned function.
    - **Why**: ADR-011 requires the prompt to be versioned and testable outside the handler.
    - **Pattern**: Keep file/path handling deterministic and avoid user-controlled paths.
    - **Verify**: `pytest tests/unit/test_commands_compress.py -k "prompt" -v` passes.

  - [x] 5.5 Implement `/compress` saga orchestration and rollback
    - **File**: `src/cursor_agent/cli/compress.py` (modify existing)
    - **What**: Resolve current session, set compressing metadata, send prompt to old agent, create/resume new agent as needed, update same row to new `agent_id`, send summary to the new agent, clear status, and restore prior state on failure.
    - **Why**: Enables context compression without losing the logical session identity.
    - **Pattern**: Follow ADR-011 exactly; avoid logging prompt/summary bodies; use `format_error` at the handler boundary.
    - **Verify**: `pytest tests/unit/test_commands_compress.py -v` passes.

  - [x] 5.6 Wire `/compress` handler to saga result
    - **File**: `src/cursor_agent/cli/slash_commands.py` (modify existing)
    - **What**: Register and connect the `/compress` command to the saga, update `ReplState.active_session_id`/last status context if needed, and print concise success or failure messages through `writer`.
    - **Why**: Keeps command routing separate from stateful saga implementation.
    - **Pattern**: Keep handler code short and delegate stateful work to `cli/compress.py`.
    - **Verify**: `pytest tests/unit/test_commands_handlers.py tests/unit/test_commands_compress.py -v` passes.

- [x] **6.0 Validate tests, documentation, and PRD-005 handoff** — PRD T5 / ADR-022

  **Trigger / entry point:** Feature behavior is implemented and ready for local quality gates and handoff.  
  **Enables:** Closing PRD-004 and starting PRD-005 with updated evidence about command behavior, `/stop`, `/usage`, and logging.  
  **Depends on:** Tasks 1.0 through 5.0 completed.

  **Acceptance criteria:**
  - Router, handler, Rich display, and `/compress` tests pass without `CURSOR_API_KEY`.
  - The canonical local gate passes: `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest --cov ... -m "not integration"`.
  - README documents the optional `.cursor/hooks.json` template and auto-approve risk without implementing PRD-005 hooks.
  - `docs/prd/PRD-005-messaging-profile.md` §7, §9, and §11 are updated with PRD-004 learnings before PRD-005 starts.
  - PRD-004 Definition of Done is fully mapped to completed tasks.

  - [x] 6.1 Add or update README guidance for optional dev hooks and auto-approve risk
    - **File**: `README.md` (modify existing)
    - **What**: Document the optional `.cursor/hooks.json` template and explain that coding-profile auto-approve is a developer convenience, not the messaging security posture.
    - **Why**: FR-10 requires documentation while PRD-005 owns real messaging hooks.
    - **Pattern**: Link to PRD-005/gateway security rather than duplicating the full security model.
    - **Verify**: `python -m pytest tests/test_package_metadata.py -v` passes and README contains the documented risk note.

  - [x] 6.2 Run focused unit test groups for PRD-004
    - **File**: — (verification only)
    - **What**: Run router, handler, Rich display, compress, streaming, session store, and exit-code tests together.
    - **Why**: Confirms feature behavior before the full local gate.
    - **Pattern**: Use no-API-key unit tests only.
    - **Verify**: `pytest tests/unit/test_commands_router.py tests/unit/test_commands_handlers.py tests/unit/test_commands_compress.py tests/unit/test_display_rich.py tests/unit/test_cli_streaming.py tests/unit/test_session_store.py tests/unit/test_cli_exit_codes.py -v` passes.

  - [x] 6.3 Run the canonical local quality gate
    - **File**: — (verification only)
    - **What**: Run the local lint, format, type, and unit coverage gates.
    - **Why**: PRD-004 must remain merge-ready without `CURSOR_API_KEY`.
    - **Pattern**: Follow ADR-026 and the task template.
    - **Verify**: `ruff check src tests && ruff format --check src tests && mypy --strict src && pytest --cov=cursor_agent --cov-report=term-missing --cov-fail-under=85 -m "not integration"` passes.

  - [x] 6.4 Update PRD-005 retrospective sections with PRD-004 learnings
    - **File**: `docs/prd/PRD-005-messaging-profile.md` (modify existing)
    - **What**: Update §7, §9, and §11 with observed `/stop` behavior, `/usage` shape, command events, Rich/tool badge privacy decisions, and any settings-source limitations.
    - **Why**: ADR-022 blocks starting PRD-005 until the next PRD has current implementation learnings.
    - **Pattern**: Use the "Learnings" style already present in PRD-004 §11.
    - **Verify**: `rg "PRD-004|/stop|/usage|command" docs/prd/PRD-005-messaging-profile.md` shows concrete carry-over notes.

  - [x] 6.5 Run `/code-review` gate before closing PRD-004
    - **File**: — (review workflow)
    - **What**: Execute the repository code review workflow and resolve any blocking issues.
    - **Why**: AGENTS.md requires review approval before closing a PRD.
    - **Pattern**: Follow `.cursor/commands/code-review.md` and `.cursor/rules/code-review.mdc`.
    - **Verify**: Review verdict is "Aprovado" or "Aprovado com ressalvas" with no open blocker.

---

## Mapeamento PRD §10 → tarefas

| PRD-004 item | Parent task neste documento |
|--------------|-----------------------------|
| T0 `uv add rich` + display interface | 1.0 |
| T1 `CommandRouter` + `ReplState` + `CommandContext` | 2.0 |
| T2 P0/P1/P2 commands | 3.0 |
| T3 Rich display | 4.0 |
| T4 `/compress` saga + rollback | 5.0 |
| T5 command tests + NDJSON events | 3.0, 6.0 |
| ADR-022 retroalimentação para PRD-005 | 6.0 |

## Sequência segura de desenvolvimento

1. Implement Task 1.0 first because Rich must be explicit before renderer tests.
2. Implement Task 2.0 next because command handlers depend on router/context/state.
3. Implement Task 3.0 P0 handlers first, then last-turn state, then P1/P2 handlers; `/retry` and `/usage` must not be implemented before Task 3.3.
4. Implement Task 4.0 after the display boundary exists; it can run in parallel with later Task 3.0 work only after Task 2.4 is merged and no one else is changing `run_repl` streaming contracts.
5. Implement Task 5.0 after router and handler contracts exist; `/compress` is fully registered only in Task 5.6 after the saga interface exists.
6. Run Task 6.0 last, including README updates, full gates, `/code-review`, and PRD-005 retrospective updates before closing PRD-004.

## Double check — desenvolvimento seguro

- **No rewrite risk:** Task 2.4 explicitly replaces only the inline slash branch in `run_repl`; free-text sending and auto-resume stay in place.
- **State before behavior:** `ReplState` lands before `/retry`, `/usage`, `/model`, and `/stop`, preventing ad hoc locals or hidden globals.
- **Store capability before saga:** Task 5.1–5.2 add the missing same-row `agent_id` replacement before `/compress` orchestration.
- **Cooperative cancel only:** `/stop` is scoped to `facade.cancel(agent_id)`; SIGINT handling, gateway busy behavior, and shutdown cancellation stay deferred to PRD-006.
- **Privacy before display/logging:** Tool badges are name/state only, and command logs avoid prompt bodies, tool args, secrets, and PII.
- **Handoff boundary:** Messaging hooks, gateway enforcement, and destructive-command policy stay out of PRD-004 and feed PRD-005 through Task 6.4.
