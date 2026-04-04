---
description: |
  Quality assessment of Zylch standalone modules after transformation
  from SaaS to local CLI tool.
---

# Quality Grades

## Module Assessment

| Module | Test Coverage | Docs | Arch Conformance | Known Gaps |
|--------|:---:|:---:|:---:|---|
| **cli/** | None | Medium | High | Dashboard, /process pipeline, profiles |
| **email/** | None | Low | High | New IMAP client, no tests |
| **services/** | Low | Medium | Medium | process_pipeline.py added; SaaS remnants in chat_service, command_handlers |
| **storage/** | Low | Medium | High | SQLite migration complete, no tests for upserts |
| **tools/** | None | Medium | High | gmail_tools.py (874 lines) above guideline |
| **agents/** | None | Low | High | No tests for incremental prompt |
| **agents/trainers/** | None | Low | High | Task trainer incremental, untested |
| **memory/** | None | Medium | High | UUID fix applied; in-memory vector search, untested |
| **llm/** | None | Low | High | Simplified to 2 providers |
| **workers/** | None | Low | High | Fail-fast on LLM errors (3 consecutive) |
| **utils/** | Low | Low | High | Encryption + auto-reply detector |
| **config.py** | None | Medium | High | Clean standalone config |

## Stale Modules (Candidates for Deletion)

| Module | Status | Action |
|--------|--------|--------|
| `zylch/intelligence/` | Empty `__init__.py` only | Delete |
| `zylch/ml/` | `anonymizer.py` — unclear if used | Investigate |
| `zylch/router/` | `intent_classifier.py` — may be used by command_matcher | Investigate |
| `zylch/webhook/` | Empty `__init__.py` only | Delete |
| `zylch/api/` | Compatibility shim only | Keep for now |

## Test Status

**No tests currently pass.** The `tests/` directory references the old SaaS architecture and needs a complete rewrite for standalone.

## Architectural Conformance

### Conforming
- Storage uses SQLAlchemy ORM with SQLite
- CLI uses click with subcommands
- Tools follow base class pattern
- Config via Pydantic Settings
- Embeddings via fastembed (no PyTorch)
- Memory search via numpy (no pgvector)

### Non-Conforming
- `gmail_tools.py` (874 lines) above 500-line guideline
- `command_handlers.py` still has SaaS-era `/connect` stubs
- `chat_service.py` still references MrCall routing paths
- `api/token_storage.py` is a compatibility shim (tech debt)
- `tests/` directory entirely stale
