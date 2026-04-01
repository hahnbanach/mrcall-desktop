---
description: |
  Current state of Zylch development as of 2026-04-01. End-to-end QA completed,
  tech debt resolved, project split planned. Ready for separation.
---

# Active Context

## What Is Built and Working

### Core Infrastructure
- PostgreSQL storage layer with 29+ SQLAlchemy ORM models
- Alembic migration system (4 migrations: initial, business_id, error_logs, seed providers)
- FastAPI HTTP API at `api.zylchai.com` (Railway) and localhost:8001 (Docker standalone)
- Firebase Auth for multi-tenant authentication
- Docker compose with configurable ports via env vars (standalone: 8001/5433)
- `Storage` class (renamed from SupabaseStorage, pure SQLAlchemy)

### Email Intelligence
- Gmail sync (OAuth 2.0, incremental via history_id)
- Microsoft Outlook sync (Graph API)
- Email archive with full-text search (PostgreSQL FTS via `fts_document` TSVECTOR)
- `/email search` restored: direct FTS query with ILIKE fallback for person names
- Auto-sync on first message if last sync >24h ago
- Email triage, auto-reply detection, read tracking, draft management

### Task System
- Task detection from emails and calendar events
- Person-centric task aggregation
- 4-level urgency: CRITICAL, HIGH, MEDIUM, LOW (with explicit criteria)
- Incremental task prompt: auto-generated after sync, no manual training step
- Prompt reconsolidation: first sync = full generation, subsequent = incremental
- `user_email` derived from oauth_tokens at runtime (not MY_EMAILS env var)

### Memory System
- Entity-centric blob storage with vector embeddings
- fastembed (ONNX-only, no PyTorch) — Docker image from 1.66GB to 371MB
- Hybrid search (pgvector cosine + PostgreSQL FTS)
- Memory reconsolidation via LLM
- Prioritizes PERSON and COMPANY extraction over TEMPLATEs

### Tools (split from monolithic factory.py)
- `session_state.py` (113 lines) — SessionState runtime context
- `factory.py` (589 lines) — ToolFactory, imports from modules
- `gmail_tools.py` (874 lines) — 7 Gmail/draft tools
- `email_sync_tools.py` (344 lines) — 4 sync tools
- `contact_tools.py` (617 lines) — 4 contact/task/memory tools
- `crm_tools.py` (414 lines) — 3 Pipedrive + compose tools

### Notifications
- Deduplication: identical unread notifications not re-created
- Error message normalization (strips job UUIDs)
- Post-sync guidance when task processing is skipped

### Integrations
- Google Calendar, Pipedrive CRM, StarChat/MrCall, SendGrid, Vonage SMS
- Integration providers seeded via Alembic migration 0004

## Completed This Session (2026-03-31 / 2026-04-01)

### QA — 3 Rounds (commits `3d57696`, `4f19325`, `6d32b37`)
- End-to-end test with support@mrcall.ai against real email data (500 emails)
- Cross-referenced IMAP ground truth (148 non-notification emails, 30 days)
- Task detection accuracy: 11/11 correct, 0 false positives
- QA report: `docs/qa/standalone-qa-report.md`
- 10 issues found and fixed across 3 rounds

### fastembed Swap (`707c4d5`)
- sentence-transformers+PyTorch → fastembed (ONNX-only)
- Same model (all-MiniLM-L6-v2), same 384 dim, identical vectors

### Tech Debt Cleanup (`f85183f`, `2c1ea8c`)
- `SupabaseStorage` → `Storage`: 39 Python files + 20 doc files, shim deleted
- `tools/factory.py` split: 2232 lines → 6 focused modules

### Project Split Plan (`9ad4cdc`)
- Plan at `docs/plans/project-split-plan.md`
- mrcall-agent (SaaS) and zylch-standalone (local CLI) to become separate repos

## Deployed State

- **GitHub (origin/main)** and **GitLab (gitlab/main)**: all commits pushed
- **Railway**: auto-deploys from GitHub main
- **Local Docker**: running on localhost:8001, connected to Railway DB

## What Is In Progress

Nothing actively in progress — all items completed.

## Immediate Next Steps

1. **Validate split plan** with mrcall-agent session
2. **Execute split**: remove MrCall code from this repo, replace PostgreSQL with SQLite
3. **Verify Railway deploy** with fastembed (no PyTorch in production)
4. **Test incremental task prompt** end-to-end (requires API key)

## Known Issues and Tech Debt

- `config_tools.py:109-125` `category_map` has wrong variable names (pre-rename)
- `config_tools.py:149` modifiable logic bug (`and` should not require `advanced`)
- MrCall agent hardcoded to Anthropic — cannot use other providers
- ONNX import warning in container (`cannot import name 'ONNX_WEIGHTS_NAME'`)
- Memory processing needs LLM API key — no processing without BYOK configured
- No end-to-end test of incremental task prompt (needs API key)
- `gmail_tools.py` (874 lines) and `contact_tools.py` (617 lines) above 500-line guideline
