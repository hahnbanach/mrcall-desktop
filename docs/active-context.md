---
description: |
  Current state of Zylch development as of 2026-03-27. What works, what's in progress,
  immediate next steps, and known issues.
---

# Active Context

## What Is Built and Working

### Core Infrastructure
- PostgreSQL storage layer with 29+ SQLAlchemy ORM models + error_logs table
- Alembic migration system (2 migrations: initial + error_logs)
- FastAPI HTTP API at `api.zylchai.com`
- Firebase Auth for multi-tenant authentication
- Scaleway Kubernetes deployment (ARM64)
- GitLab CI/CD with self-hosted ARM runner
- Daily Docker cleanup cron on runner (`0 3 * * * docker system prune -af && docker builder prune -af`)

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
- **Always uses `app_settings.anthropic_model`** — independent of `SYSTEM_LLM_PROVIDER` (production uses OpenAI for chat but Anthropic for MrCall)
- **Native web search** via `web_search_20250305` (Brave Search backend, replaces DuckDuckGo scraping)
- **Business identity injection** — agent knows business name, language, ID
- **respond_text rules** — agent gives concrete answers based on actual config, never says "I don't have visibility"
- **get_current_config removed** — raw variable dumps not exposed to end users
- **SSE streaming** (`/api/chat/message/stream`) — incremental text delivery, `reactive()` in Vue, `text_replace` for clean final text
- **Retry with backoff** — 3 attempts with exponential backoff (2s, 4s, 8s) for transient Anthropic errors (429, 500, 529)
- **Haiku error humanizer** — user-friendly error messages via Claude Haiku
- **Error logging** — `error_logs` table with business_id, session_id, request_id, Haiku-generated message
- **Fallback message** — after 3 retries, shows support@mrcall.ai with session ID
- **File attachments** support (images, PDFs, text — Anthropic native format)
- Feature-level variable management via StarChat API
- Conversation memory across `/agent mrcall run` calls within a session
- Config memory: decisions persisted as entity blobs
- Fixed templates per feature (no LLM-generated meta-prompts)
- Dry-run mode for dashboard with Save/Discard workflow
- SSL verify bypass for StarChat self-signed certs on test environment

### User Interfaces
- CLI at `~/hb/zylch-cli` (Python/Textual, thin client)
- MrCall Dashboard at `~/hb/mrcall-dashboard` (Vue 3/PrimeVue)
  - v1.52 merged into test-env, beta-env, production-env
  - Textarea input (replacing single-line InputText)
  - File upload button with preview
  - Training requirement removed from ConfigureAI flow
  - Streaming with `reactive()` for proper Vue reactivity
  - `text_replace` callback for clean final text after streaming
  - Typing indicator hidden during active streaming
- FastAPI REST API (primary backend)

### Documentation Harness
- `CLAUDE.md` structured as concise index with pointers to all docs
- `docs/ARCHITECTURE.md` based on code ground truth
- `docs/active-context.md` tracks current project state

## Completed (Session 2026-03-27)

### MrCall Agent — Streaming + Error Resilience

1. **Incremental streaming** (`5519367`): `run_stream()` intercepts `input_json_delta` events for `respond_text` tool, decoding JSON escapes on the fly
2. **text_replace** (`74224b0`): At `content_block_stop`, parses complete JSON and emits properly decoded text to replace streaming artifacts
3. **Retry + error handling** (`5d8af65`): 3 retries with exponential backoff, Haiku humanizer, error_logs table, fallback message
4. **Model fix** (`a8adf18`): Always use `app_settings.anthropic_model`, not `self.llm.model` which could be `gpt-4.1` when `SYSTEM_LLM_PROVIDER=openai`

### Dashboard (mrcall-dashboard)
- `reactive()` for assistant message — fixes streaming messages disappearing
- `onTextReplace` callback for clean final text
- Typing indicator hidden during active streaming (`v-if="!messages.some(m => m.streaming)"`)
- Merge conflicts resolved on beta-env (ZylchChat.vue, Zylch.js)

### Infrastructure
- `error_logs` table via Alembic migration 0002
- Railway deploy confirmed to run `alembic upgrade head` automatically
- Planning principles hook in global `~/.claude/settings.json` (UserPromptSubmit, filtered by keyword)

## Deployed State

- **Local Docker**: all changes, migration run, tested with preview
- **Production/Test**: pending push by user (7 commits ahead on main)
- Test user: `mario.alemi+19mar2026@gmail.com` / `mlWH0BnYVHSz0qwDY0xFliUkJIl2`
- Test business: `738535bd-6a76-3ad1-b0d8-606c02a3df95` (Tiscali Store Cagliari)

## What Is In Progress

Nothing actively in progress — all items completed this session.

## Immediate Next Steps

1. **Push to dev + production** — user doing this manually
2. **Verify streaming end-to-end on deployed environments** — especially web search + streaming interaction
3. **Config memory for conversation intent** — currently only saves executed changes, not proposed configurations (edge case: user proposes booking hours, page reload loses context)
4. Fix `category_map` in `zylch/tools/mrcall/config_tools.py` with correct post-rename variable names
5. Fix modifiable logic bug on `config_tools.py:149`

## Known Issues and Tech Debt

- `config_tools.py:109-125` `category_map` has wrong variable names (pre-rename)
- `config_tools.py:149` modifiable logic bug (`and` should not require `advanced`)
- `SupabaseStorage` class name is misleading (pure SQLAlchemy, legacy name)
- `tools/factory.py` is 2000+ lines (exceeds 500-line rule)
- MrCall agent hardcoded to Anthropic — cannot use other providers due to web_search_20250305 dependency
- Git branch topology: main, dev, production slightly diverged — need alignment
- `.env.development` in mrcall-dashboard was changed to point to test-env-0 (was angelo.ngrok.io)
- No external telemetry or monitoring (pre-alpha)
