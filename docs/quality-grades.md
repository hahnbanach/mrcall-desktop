---
description: |
  Quality assessment of each major Zylch module: test coverage, documentation,
  architectural conformance, and known gaps.
---

# Quality Grades

## Module Assessment

| Module | Test Coverage | Docs | Arch Conformance | Known Gaps |
|--------|:---:|:---:|:---:|---|
| **api/routes/** | Medium | Low | High | Missing API docs for most endpoints |
| **services/** | Medium | Low | High | chat_service is the largest, could split |
| **storage/** | Low | Medium | High | supabase_client.py name is misleading |
| **tools/** | Medium | Medium | High | factory.py is 2000+ lines (exceeds 500 limit) |
| **agents/** | Low | High | High | No tests for conversation memory or config memory |
| **agents/trainers/** | Low | Low | High | No tests for trainers; simplified after live-values refactor |
| **memory/** | Medium | High | High | Good entity-memory docs exist |
| **llm/** | Low | Low | High | No tests for LLM client |
| **skills/** | None | Low | Medium | Unclear if actively used |
| **sharing/** | Low | Low | Medium | Feature marked "coming soon" |
| **workers/** | Low | Low | Medium | - |
| **config.py** | None | Medium | High | Well-structured Pydantic Settings |

## Test Coverage Detail

### Files with Tests
- `tests/test_command_handlers.py` - Command routing
- `tests/test_hybrid_search.py` - Memory hybrid search
- `tests/test_agent.py` - Agent base functionality
- `tests/test_sharing.py` - Sharing authorization
- `tests/test_tool_factory.py` - Tool registration
- `tests/test_auto_reply_detector.py` - Email auto-reply detection
- `tests/test_webhooks.py` - Webhook processing
- `tests/test_api_routes.py` - API route tests
- `tests/test_llm_merge.py` - Memory reconsolidation
- `tests/test_mrcall_oauth.py` - MrCall OAuth flow
- `tests/test_sandbox_service.py` - Sandbox execution
- `tests/test_mrcall_integration.py` - MrCall integration
- `tests/test_email_archive_backend.py` - Email archive
- `tests/test_text_processing.py` - Text utilities
- `tests/workers/test_memory_worker.py` - Memory worker

### Modules with No Tests
- `llm/client.py`, `llm/providers.py`
- `skills/*`
- `integrations/*`
- `router/*`
- Most individual tools (gmail.py, gcalendar.py, etc.)
- Agent trainers

## Documentation Completeness

### Well-Documented
- Entity Memory System (`docs/features/entity-memory-system.md`)
- Email Archive (`docs/features/email-archive.md`)
- Multi-Tenant Architecture (`docs/features/multi-tenant-architecture.md`)
- MrCall Integration (`docs/features/mrcall-integration.md`)
- Architecture overview (`docs/ARCHITECTURE.md`)
- Deployment (`docs/guides/DEPLOYMENT.md`)
- Gmail OAuth (`docs/guides/gmail-oauth.md`)

### Partially Documented
- Calendar Integration (`docs/features/calendar-integration.md`)
- Relationship Intelligence (`docs/features/relationship-intelligence.md`)
- Triggers & Automation (doc exists, feature "coming soon")

### Missing Documentation
- API endpoint reference (no OpenAPI export or manual docs)
- CLI command reference (marked "coming soon")
- Agent training system
- LLM client configuration
- Skills system
- Background job system

## Architectural Conformance

### Conforming
- Storage layer consistently uses SQLAlchemy ORM
- All models have owner_id for multi-tenant isolation
- API routes use FastAPI routers with Firebase auth
- Tools follow base class pattern
- Config via Pydantic Settings

### Non-Conforming
- `tools/factory.py` exceeds 500-line limit significantly
- `SupabaseStorage` class name doesn't match implementation (SQLAlchemy)
- Some docs reference files/paths that don't exist in code
- `frontend/` dormant code still in repo
