---
description: |
  Quality assessment of Zylch standalone modules.
  Updated 2026-04-04 after WhatsApp, Telegram, profile CLI, aisuite removal.
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
| **services/process_pipeline.py** | 430 | None | Low | High | New, auto-train logic |
| **services/** (other) | ~1500 | Low | Medium | Medium | sync_service, chat_service |
| **storage/** | 496+~600+~300 | Low | Medium | High | 19 models, SQLite |
| **tools/gmail_tools.py** | **988** | None | Medium | **LOW** | Oversized |
| **tools/** (other) | ~2000 | None | Medium | High | Factory, starchat, whatsapp_tools |
| **agents/** | ~500 | None | Low | High | Base + emailer + task orchestrator |
| **agents/trainers/** | ~800 | None | Low | High | Incremental prompt, untested |
| **memory/** | ~700 | None | Medium | High | fastembed, hybrid search |
| **llm/** | 492+~120 | None | Low | High | Direct SDK (aisuite dropped) |
| **workers/** | ~600 | None | Low | High | Fail-fast on LLM errors |
| **config.py** | 197 | None | Medium | High | Clean standalone config |

## Oversized Files (> 500 lines)

| File | Lines | Action |
|------|------:|--------|
| `services/command_handlers.py` | 5137 | Split urgently — 10x over limit |
| `tools/gmail_tools.py` | 988 | Split into search/draft/send modules |
| `tools/starchat.py` | ~850 | Consider splitting |
| `services/sync_service.py` | 770 | Acceptable if MrCall sync moves out |
| `cli/setup.py` | 636 | Slightly over, acceptable for wizard |

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

**No tests currently pass.** The `tests/` directory references the old SaaS architecture and needs a complete rewrite.

## Lint Status

- 63 files need Black reformatting
- 114 Ruff errors (91 auto-fixable)
