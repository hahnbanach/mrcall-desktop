# Harness Backlog

Enforcement gaps, missing tooling, and documentation debt identified during development.

- [x] `tools/factory.py` exceeds 500-line limit (2000+ lines) — needs splitting
  Discovered: 2026-03-17 doc-migration session
  Resolved: 2026-04-01 — split into 6 modules (session_state, gmail_tools, email_sync_tools, contact_tools, crm_tools, factory)

- [ ] `docs/agents/README.md` references non-existent files (`memory_agent.py`) and wrong class names (`Storage` as Supabase)
  Discovered: 2026-03-17 doc-migration session
  Impact: Misleads developers about agent architecture; new contributors would look for wrong files

- [ ] No linter or CI check enforcing the 500-line file limit
  Discovered: 2026-03-17 doc-migration session
  Impact: Large files accumulate silently (factory.py is 4x the limit)

- [ ] No OpenAPI/Swagger export or API endpoint documentation
  Discovered: 2026-03-17 doc-migration session
  Impact: API consumers (CLI, Dashboard) have no reference; FastAPI auto-generates /docs but it's not exported/versioned

- [ ] No tests for agent trainers (`zylch/agents/trainers/`)
  Discovered: 2026-03-17 doc-migration session
  Impact: Training logic changes could break silently; trainers are critical for MrCall configuration quality

- [ ] `ScheduledJob` and `ThreadAnalysis` ORM models appear unused — candidate for cleanup
  Discovered: 2026-03-17 doc-migration session
  Impact: Dead code in models.py adds confusion; corresponding DB tables waste schema space

- [ ] `config_tools.py` `category_map` uses wrong/outdated variable names and is missing welcome variables
  Discovered: 2026-03-19 variable rename session
  Impact: `get_assistant_catalog` with `filter_category="welcome"` returns no results or wrong variables

- [ ] `config_tools.py:149` modifiable logic requires both `modifiable` AND `advanced` — most variables incorrectly show as read-only
  Discovered: 2026-03-19 variable rename session
  Impact: Users cannot modify variables through the catalog tool even when they should be modifiable

- [ ] No integration test for MrCall agent conversation memory (multi-turn run() calls)
  Discovered: 2026-03-26 live-values refactor session
  Impact: Regressions in conversation continuity would go undetected; this was the root cause of the "sì grazie" context loss bug

- [ ] No test for config memory blob persistence (mrcall_memory.py)
  Discovered: 2026-03-26 live-values refactor session
  Impact: Config decisions could fail to persist silently, causing the agent to "forget" across sessions

- [ ] No end-to-end test for incremental task prompt generation
  Discovered: 2026-04-01 QA session
  Impact: Prompt reconsolidation logic (NO_CHANGES_NEEDED vs update) untested; could silently break task detection

- [ ] No test for notification dedup in storage.create_notification()
  Discovered: 2026-04-01 QA session
  Impact: Duplicate banners could return if dedup logic regresses

- [ ] No test for auto-sync trigger in chat_service.py
  Discovered: 2026-04-01 QA session
  Impact: Auto-sync could fail silently or trigger on every message instead of once per session

- [ ] `integration_providers` SQL migrations in `zylch/integrations/migrations/` are redundant with Alembic 0004
  Discovered: 2026-04-01 QA session
  Impact: Two sources of truth for provider seed data; could diverge over time

- [ ] ONNX_WEIGHTS_NAME import error in container (optimum package)
  Discovered: 2026-04-01 QA session
  Impact: Warning in logs on `/tasks` command; may affect embedding generation in edge cases
