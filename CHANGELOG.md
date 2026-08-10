# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.1] — 2026-08-05

CLI thinking indicator (PRD-018) — shipped on `main` @ tag **`v1.3.1`** ([#82](https://github.com/adriannoes/cursor-agent/pull/82)).

### Added

- CLI thinking indicator (PRD-018): TTY-only `Thinking… · Ns` during free-text, skill, and `/retry` streaming sends; suppressed in CI and non-TTY pipes.

## [1.3.0] — 2026-08-01

Operator CLI hygiene (PRD-017) — shipped on `main` @ tag **`v1.3.0`** ([#80](https://github.com/adriannoes/cursor-agent/pull/80)).

### Added

- Operator commands: `auth status`, `doctor`, `gateway check`, `sessions show|delete|prune`, live `models`.
- Module-level ephemeral SDK helpers `probe_api_key` and `list_models` (boolean / DTO surfaces only).
- `messaging_hooks_status` reporting for doctor (also re-exported from `messaging_hooks` for import compatibility).

### Changed

- Sessions CLI resolves rows via `SessionStore.resolve(session_key, session_id)`; store bootstrap is shared across list/show/delete/prune.
- Usage-OAuth local inspection uses a single loader for status + token (no dual `auth.json` read).

### Removed

- **`SessionStore.get`** — identity alias of `resolve(session_key, session_id)`. Callers must use `resolve` with an explicit `session_id`. The CLI never depended on `get`; this is an intentional library-surface trim for v1.3.0.
- Orphan narrow protocols `ApiKeyProber` / `ModelCatalogReader` and FakeSdkFacade probe/catalog instance methods (production used free functions only).

## [1.2.1]

- Skills discovery harden + package-smoke isolation after the v1.2.0 review follow-up.

## [1.2.0]

- Product skills pack (`skills/`, `skills path|list|seed`, BYO paste).

## [1.1.0]

- `full` tool profile; Grok 4.5 as default first-party model.

## [1.0.0]

- First-run banner and setup index.

[Unreleased]: https://github.com/adriannoes/cursor-agent/compare/v1.3.1...HEAD
[1.3.1]: https://github.com/adriannoes/cursor-agent/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/adriannoes/cursor-agent/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/adriannoes/cursor-agent/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/adriannoes/cursor-agent/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/adriannoes/cursor-agent/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/adriannoes/cursor-agent/releases/tag/v1.0.0
