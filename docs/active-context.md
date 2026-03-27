---
description: |
  Current state of Zylch development as of 2026-03-26 evening. What works, what's in progress,
  immediate next steps, and known issues.
---

# Active Context

## What Is Built and Working

### Core Infrastructure
- PostgreSQL storage layer with 29+ SQLAlchemy ORM models
- Alembic migration system
- FastAPI HTTP API at `api.zylchai.com`
- Firebase Auth for multi-tenant authentication
- Scaleway Kubernetes deployment (ARM64)
- GitLab CI/CD with self-hosted ARM runner
- Daily Docker cleanup cron on runner (prevents disk-full build failures)

### Email Intelligence
- Gmail sync (OAuth 2.0, incremental via history_id)
- Microsoft Outlook sync (Graph API)
- Email archive with full-text search (PostgreSQL FTS)
- Email triage (AI-powered categorization)
- Auto-reply detection
- Email read tracking (SendGrid webhooks + custom pixel)
- Draft management (create, edit, send)

### Task System
- Task detection from emails and calendar events
- Person-centric task aggregation
- Priority scoring (urgency 1-10)
- Task orchestrator agent

### Memory System
- Entity-centric blob storage with vector embeddings
- Hybrid search (pgvector + FTS)
- Memory reconsolidation via LLM
- Pattern detection and storage

### Integrations
- Google Calendar (events, Meet link generation)
- Pipedrive CRM (contacts, deals)
- StarChat/MrCall (contacts, telephony config)
- SendGrid (email campaigns)
- Vonage SMS
- Web search (contact enrichment)

### MrCall Configuration
- MrCall agent with **live variable loading** (no more stale trained prompts)
- **Anthropic API called directly** (not via aisuite) for native web search + PDF/image support
- **Native web search** via `web_search_20250305` (Brave Search backend, replaces DuckDuckGo scraping)
- **Business identity injection** — agent knows business name, language, ID
- **respond_text rules** — agent gives concrete answers based on actual config, never says "I don't have visibility"
- **get_current_config removed** — raw variable dumps not exposed to end users
- Feature-level variable management via StarChat API
- **Conversation memory** across `/agent mrcall run` calls within a session
- **Config memory**: configuration decisions persisted as entity blobs (namespace `{owner_id}:mrcall:{business_id}`)
- **Fixed templates** per feature (no LLM-generated meta-prompts for structure)
- Dry-run mode for dashboard with Save/Discard workflow
- **File attachments** support (images, PDFs, text — Anthropic native format)
- **SSE streaming endpoint** (`/api/chat/message/stream`) — backend ready, dashboard integration in progress
- SSL verify bypass for StarChat self-signed certs on test environment

### User Interfaces
- CLI at `~/hb/zylch-cli` (Python/Textual, thin client)
- MrCall Dashboard at `~/hb/mrcall-dashboard` (Vue 3/PrimeVue)
  - v1.52 merged into test-env and production-env
  - Textarea input (replacing single-line InputText)
  - File upload button with preview
  - Training requirement removed from ConfigureAI flow
- FastAPI REST API (primary backend)
- `frontend/` directory is dormant (Vue 3 prototype, not active)

### Documentation Harness
- `CLAUDE.md` structured as concise index (~50 lines) with pointers to all docs
- `docs/ARCHITECTURE.md` based on code ground truth
- `docs/active-context.md` tracks current project state

## Completed (Session 2026-03-26 evening)

### MrCall Agent — Direct Anthropic API + Web Search + Streaming

1. **SSL fix** (`6eb5ff2`): Fixed 3 `httpx.AsyncClient` instances missing `verify=settings.starchat_verify_ssl`
2. **Business identity injection** (`1e8221f`): Template now includes `{business_name}`, `{business_id}`, `{business_language}`. Added RESPOND_TEXT RULES section.
3. **get_current_config removed** (`5d1df4e`): Tool count 11→10. Users should not see raw variable dumps.
4. **File attachments + web search** (`9e25450`): Dashboard can upload files, backend passes them as Anthropic content blocks. Initial DuckDuckGo web search (later replaced).
5. **Anthropic native web search** (`b7d96fc`, `ae2b410`): Replaced DuckDuckGo scraping with `web_search_20250305` server tool. Calls Anthropic SDK directly, not via aisuite. Removed ~140 lines of manual HTML scraping/multi-turn.
6. **SSE streaming** (`2a27c0d`, `d8ed1c8`): Added `run_stream()` to MrCallAgent and `/api/chat/message/stream` SSE endpoint. Uses `client.messages.stream()`.

### Dashboard (mrcall-dashboard)
- Textarea replacing single-line input in ZylchChat.vue
- File upload with preview/remove
- Training step removed from ConfigureAI.vue
- v1.52 merged into test-env (conflicts resolved: `.claude/commands/doc-*.md`)

### Infrastructure
- Daily Docker cleanup cron on GitLab runner
- Cron on runner: `0 3 * * * docker system prune -af && docker builder prune -af`

## Deployed State

- **Production** (`production` branch): deployed with all changes through `d8ed1c8`
- **Test** (`dev` branch): deployed with all changes through `d8ed1c8`
- Test user: `mario.alemi+19mar2026@gmail.com` / `mlWH0BnYVHSz0qwDY0xFliUkJIl2`
- Test business: `738535bd-6a76-3ad1-b0d8-606c02a3df95` (Tiscali Store Cagliari)

## What Is In Progress

### SSE Streaming — Dashboard Integration
Backend streaming works but dashboard needs to consume SSE stream:
- `ZylchChat.vue` needs `EventSource` or fetch-with-reader for `/api/chat/message/stream`
- Handle progressive text rendering, streaming state, error mid-stream
- Web search streaming partially broken: text starts showing ("Cer...") but stream dies — likely Anthropic web_search_tool_result blocks not handled in stream event processing

### Known Streaming Issue
When web search is used + streaming, the stream appears to break after initial text. Probable cause: `run_stream()` iterates `stream.text_stream` which may not yield text during the web search server-side phase, or the stream format includes non-text events that need special handling.

## Immediate Next Steps

1. **Fix streaming + web search interaction** — test locally with `docker compose up`
2. **Dashboard SSE integration** — consume stream in ZylchChat.vue
3. **Test end-to-end**: web search → knowledge base configuration → streaming response
4. **Push to production** only after local validation
5. Fix `category_map` in `zylch/tools/mrcall/config_tools.py` with correct post-rename variable names
6. Fix modifiable logic bug on `config_tools.py:149`

## Known Issues and Tech Debt

- `config_tools.py:109-125` `category_map` has wrong variable names (pre-rename names, missing variables)
- `config_tools.py:149` modifiable logic is wrong: requires both `modifiable` and `advanced` flags true
- `SupabaseStorage` class name is misleading (pure SQLAlchemy, legacy name)
- `docs/agents/README.md` lists agents that don't match actual source files
- `frontend/` Vue 3 prototype is dormant but still in repo
- `tools/factory.py` is 2000+ lines (exceeds 500-line rule)
- No external telemetry or monitoring (pre-alpha)
- Single replica deployment (no HA)
- Test + production share same PostgreSQL instance (different namespaces)
- Git branch topology is messy: main, dev, production all slightly diverged — need alignment
