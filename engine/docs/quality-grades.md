---
description: |
  Quality assessment of Zylch standalone modules.
  Updated 2026-04-11 after 14 task detection + execution fixes (0.1.20).
---

# Quality Grades

## Module Assessment

| Module | Lines | Test Coverage | Docs | Arch Conformance | Known Gaps |
|--------|------:|:---:|:---:|:---:|---|
| **cli/** | 172+636+146+235+49 | None | Medium | High | Profile-aware, rclone wizard |
| **email/** | ~400 | None | Low | High | IMAP client, no tests |
| **whatsapp/** | 307+401 | None | Low | High | neonize sync, contacts from messages |
| **telegram/** | ~300 | None | Low | High | Bot interface, untested |
| **services/command_handlers.py** | **5137** | None | Low | **LOW** | Massively oversized, SaaS stubs |
| **services/process_pipeline.py** | 483 | None | Low | High | Sync default 60d, auto-train |
| **services/** (other) | ~1500 | Low | Medium | Medium | sync_service, chat_service |
| **storage/** | 496+~600+~300 | Low | Medium | High | 19 models, SQLite |
| **tools/gmail_tools.py** | **988** | None | Medium | **LOW** | Oversized |
| **tools/** (other) | ~2000 | None | Medium | High | Factory, starchat, whatsapp_tools |
| **agents/** | ~500 | None | Low | High | Base + emailer + task orchestrator |
| **agents/trainers/** | ~800 | None | Low | High | Incremental prompt, untested |
| **memory/** | ~700 | None | Medium | High | fastembed, hybrid search |
| **llm/** | 492+~120 | None | Low | High | Direct SDK (aisuite dropped) |
| **workers/task_creation.py** | **1170+** | **10 tests** | Low | **LOW** | 14 fixes applied, needs splitting |
| **config.py** | 197 | None | Medium | High | Clean standalone config |

## Oversized Files (> 500 lines)

| File | Lines | Action |
|------|------:|--------|
| `services/command_handlers.py` | 5137 | Split urgently — 10x over limit |
| `tools/gmail_tools.py` | 988 | Split into search/draft/send modules |
| `tools/starchat.py` | ~850 | Consider splitting |
| `services/sync_service.py` | 770 | Acceptable if MrCall sync moves out |
| `cli/setup.py` | 636 | Slightly over, acceptable for wizard |
| `workers/task_creation.py` | 1170+ | Split: rules, analysis, storage |

## Stale Modules (Candidates for Deletion)

| Module | Status | Action |
|--------|--------|--------|
| `zylch/intelligence/` | Empty `__init__.py` only | Delete |
| `zylch/ml/` | `anonymizer.py` — unclear if used | Investigate |
| `zylch/router/` | `intent_classifier.py` — may be used by command_matcher | Investigate |
| `zylch/webhook/` | Empty `__init__.py` only | Delete |
| `zylch/api/` | Compatibility shim only | Keep for now |
| `zylch/assistant/` | Core/models/prompts — check usage | Investigate |

## Test Status

Curated live set as of 2026-05-12 (after whatsapp-pipeline-parity Phase 2 landing):
- `tests/workers/test_person_identifiers.py` — 47 cases (parser / normaliser / storage helpers / FK CASCADE / identifier-first match / cluster builder / 4 end-to-end `reconsolidate_now` scenarios with mocked LLM). Phase 1 a/b/c of whatsapp-pipeline-parity.
- `tests/storage/test_whatsapp_blobs.py` — 9 cases (Phase 2a: idempotent add / get helpers, CASCADE on both sides, `migrate_blob_references` carries WA links onto keeper).
- `tests/workers/test_memory_whatsapp.py` — 14 cases (Phase 2c: end-to-end happy path, cross-channel merge into pre-existing email-derived blob, LID→phone resolution via `whatsapp_contacts`, parser hardening `_normalise_phone` @-rejection and `_parse_identifiers_block` LID-in-Phone reroute, envelope shape, short-text / empty-extractor / group-filter paths, watermark roundtrip).
- `tests/agents/test_memory_message_trainer.py` — 9 cases (Phase 2b: class/alias backward-compat, meta-prompt content asserts).
- `tests/services/test_email_search.py` — 24 cases (Gmail-style operator parser+matcher).
- `tests/llm/test_proxy_client.py` — 8 cases (MrCallProxyClient SSE + 401 + 402 + auth header + body forwarding + streaming reconstruction).
- `tests/whatsapp/test_sync.py` — 5 cases (`_store_message_from_event` JID extraction, real `Neonize_pb2.Message` events).
- `tests/workers/test_task_phase2_ordering.py` — 5 cases (F5 phase-2 sort key).
- `tests/workers/test_task_worker_bugs.py` — 14 cases at HEAD; **broken** since 2026-05-04 transport refactor + 2026-05-06 Fase 1.1 plural `get_tasks_by_contact`. Tracked in `harness-backlog.md`. Do not count.
- `tests/services/test_reanalyze_sweep.py` — 6 cases, **5 green** (1 pre-existing fail `test_sweep_skips_when_no_candidates_old_enough`, AsyncMock un-awaited; tracked).
- `tests/storage/test_data_backfills.py` — 1 of 2 green (`test_apply_data_backfills_calls_every_step` passes; `test_init_db_invokes_channel_backfill_when_thread_id_backfill_is_noop` fails at setup with `NOT NULL constraint failed: task_items.pinned` — pre-existing on HEAD before whatsapp-pipeline-parity Phase 2 work; tracked in `harness-backlog.md`).

Total green: ~131 across 9 active files. The rest of `tests/` references the old SaaS architecture and needs a rewrite.

## Lint Status

- 63 files need Black reformatting
- 114 Ruff errors (91 auto-fixable)
