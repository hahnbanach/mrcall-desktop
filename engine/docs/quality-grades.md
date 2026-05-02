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

20 tests pass across the curated live set:
- `tests/workers/test_task_worker_bugs.py` — 14 cases (task detection regressions, RealStep / cafe124 fixes F1–F4, including 3 Cc-fallback tests fixed 2026-05-02 by re-patching `get_session` lazily and aligning fixture user_email)
- `tests/services/test_reanalyze_sweep.py` — 6 cases (bounded reanalyze sweep)

The rest of `tests/` references the old SaaS architecture and needs a rewrite.

## Lint Status

- 63 files need Black reformatting
- 114 Ruff errors (91 auto-fixable)
