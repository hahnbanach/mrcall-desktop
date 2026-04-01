# Harness Backlog

Enforcement gaps, missing tooling, and documentation debt.

## Resolved

- [x] `tools/factory.py` exceeds 500-line limit → split into 6 modules (2026-04-01)
- [x] `SupabaseStorage` misleading name → renamed to `Storage` (2026-04-01)
- [x] `ScheduledJob` and `ThreadAnalysis` unused models → removed in SQLite migration (2026-04-01)
- [x] `integration_providers` SQL migrations redundant → removed with Alembic (2026-04-01)
- [x] ONNX_WEIGHTS_NAME import error → resolved by switching to fastembed (2026-04-01)

## Open

- [ ] No linter or CI check enforcing the 500-line file limit
  Discovered: 2026-03-17
  Impact: Large files accumulate silently (gmail_tools.py is 874 lines)

- [ ] `tests/` directory entirely stale — references old SaaS architecture
  Discovered: 2026-04-01 standalone transformation
  Impact: No test coverage at all; regressions undetectable

- [ ] No end-to-end test for `zylch init` → `zylch sync` → `zylch tasks`
  Discovered: 2026-04-01 standalone transformation
  Impact: Full flow untested with real IMAP + LLM

- [ ] No test for incremental task prompt generation
  Discovered: 2026-04-01 QA session
  Impact: Prompt reconsolidation logic untested

- [ ] No test for notification dedup in storage.create_notification()
  Discovered: 2026-04-01 QA session
  Impact: Duplicate banners could return if dedup logic regresses

- [ ] No test for auto-sync trigger in chat_service.py
  Discovered: 2026-04-01 QA session
  Impact: Auto-sync could fail silently or trigger every message

- [ ] Stale modules: `zylch/intelligence/`, `zylch/ml/`, `zylch/router/`, `zylch/webhook/`
  Discovered: 2026-04-01 standalone transformation
  Impact: Dead code, confusing for new contributors

- [ ] `command_handlers.py` still has SaaS-era `/connect` stubs
  Discovered: 2026-04-01 standalone transformation
  Impact: User sees broken UI for provider connections

- [ ] `chat_service.py` still references MrCall routing paths
  Discovered: 2026-04-01 standalone transformation
  Impact: Dead code paths, potential runtime errors

- [ ] `docs/` has many stale files referencing old SaaS architecture
  Discovered: 2026-04-01 standalone transformation
  Impact: Misleading documentation for new contributors
