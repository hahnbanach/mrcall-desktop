---
description: |
  Current state of Zylch development as of 2026-04-01. QA-driven improvements
  to standalone sales assistant. Next step: split standalone from MrCall configurator.
---

# Active Context

## What Is Built and Working

### Core Infrastructure
- PostgreSQL storage layer with 29+ SQLAlchemy ORM models + error_logs table
- Alembic migration system (4 migrations: initial, business_id, error_logs, seed providers)
- FastAPI HTTP API at `api.zylchai.com` (Railway) and localhost:8001 (Docker standalone)
- Firebase Auth for multi-tenant authentication
- Scaleway Kubernetes deployment (ARM64) for MrCall configurator
- Railway deployment for standalone (auto-deploy from GitHub main)
- GitLab CI/CD with self-hosted ARM runner (Scaleway)
- Docker compose with configurable ports (standalone on 8001/5433 to avoid conflicts)

### Email Intelligence
- Gmail sync (OAuth 2.0, incremental via history_id)
- Microsoft Outlook sync (Graph API)
- Email archive with full-text search (PostgreSQL FTS via `fts_document` TSVECTOR)
- `/email search` restored as direct FTS query with ILIKE fallback for person names
- Email triage (AI-powered categorization)
- Auto-reply detection
- Email read tracking (SendGrid webhooks + custom pixel)
- Draft management (create, edit, send)
- Auto-sync on first message if last sync >24h ago

### Task System
- Task detection from emails and calendar events
- Person-centric task aggregation
- 4-level urgency: CRITICAL, HIGH, MEDIUM, LOW (with explicit criteria)
- Incremental task prompt generation (auto-generated after sync, no manual training)
- Task prompt reconsolidation: first sync = full generation, subsequent = incremental update
- `user_email` derived from oauth_tokens at runtime (not MY_EMAILS env var)

### Memory System
- Entity-centric blob storage with vector embeddings (fastembed, 384-dim)
- Hybrid search (pgvector + FTS)
- Memory reconsolidation via LLM
- Prioritizes PERSON and COMPANY extraction over TEMPLATEs
- fastembed replaces sentence-transformers+PyTorch (Docker image: 1.66GB → 371MB)

### Integrations
- Google Calendar (events, Meet link generation)
- Pipedrive CRM (contacts, deals)
- StarChat/MrCall (contacts, telephony config)
- SendGrid (email campaigns)
- Vonage SMS
- Web search (contact enrichment)
- Integration providers seeded via Alembic migration 0004

### MrCall Configuration
- MrCall agent with live variable loading (no stale trained prompts)
- Anthropic API called directly for native web search + PDF/image support
- SSE streaming, retry with backoff, Haiku error humanizer
- Error logging with error_logs table
- Feature-level variable management via StarChat API

### Notifications
- Deduplication: identical unread notifications not re-created
- Error message normalization (strips job UUIDs for consistent dedup)
- Post-sync guidance: informs user when task processing is skipped (no API key)

### User Interfaces
- CLI at `~/hb/zylch-cli` (Python/Textual, thin client)
- MrCall Dashboard at `~/hb/mrcall-dashboard` (Vue 3/PrimeVue)
- FastAPI REST API (primary backend)

## Completed (Session 2026-03-31 / 2026-04-01)

### QA Round 1 — End-to-End Standalone Test (`3d57696`)
- Connected to Railway production DB with support@mrcall.ai
- Tested all major commands against real email data (500 emails, 11 tasks)
- Cross-referenced task output with IMAP ground truth (148 real emails)
- Task detection accuracy: 11/11 correct, 0 false positives
- Fixed: seed integration_providers in Alembic, remove /gaps, fix OAuth redirect_uri,
  add CRITICAL urgency, memory PERSON priority, auto-sync, fix migration duplicate
- Docker compose ports configurable via env vars for standalone mode

### QA Round 2 — Follow-up Fixes (`4f19325`)
- Restored `/email search` as PostgreSQL FTS (was deprecated with no alternative)
- Notification dedup: check existing before insert, normalize error messages
- Post-sync guidance: actionable messages when task processing skipped

### QA Round 3 — Incremental Task Prompt (`6d32b37`)
- Task prompt auto-generated after every sync (no manual `/agent task train email`)
- Reconsolidation pattern: first time = full generation, subsequent = incremental update
- Removed get_my_emails() env var dependency, use oauth_tokens email
- Deprecated `/agent task train email` (now manual override only)

### fastembed Swap (`707c4d5`)
- Replaced sentence-transformers+PyTorch with fastembed
- Same model (all-MiniLM-L6-v2), same 384 dimensions, identical vectors
- Docker image from 1.66GB to 371MB
- Removed explicit torch install from Dockerfile

## Deployed State

- **GitHub (origin/main)**: all 4 commits pushed
- **GitLab (gitlab/main)**: all 4 commits pushed
- **Railway**: auto-deploys from GitHub main (pending build)
- **Local Docker**: running on localhost:8001, connected to Railway DB

## What Is In Progress

Nothing actively in progress — all items completed this session.
See `docs/plans/project-split-plan.md` for the next major initiative.

## Immediate Next Steps

1. **Verify Railway deploy** with fastembed (no PyTorch in production)
2. **Test incremental task prompt end-to-end** — requires `/connect anthropic` with API key

## Known Issues and Tech Debt

- `config_tools.py:109-125` `category_map` has wrong variable names (pre-rename)
- `config_tools.py:149` modifiable logic bug (`and` should not require `advanced`)
- `SupabaseStorage` class name is misleading (pure SQLAlchemy, legacy name)
- `tools/factory.py` is 2000+ lines (exceeds 500-line rule)
- MrCall agent hardcoded to Anthropic — cannot use other providers
- ONNX import warning in container (`cannot import name 'ONNX_WEIGHTS_NAME'`)
- Memory processing still needs LLM API key — no way to process without BYOK configured
- No end-to-end test of incremental task prompt (needs API key in test env)
