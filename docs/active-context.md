---
description: |
  Current state of Zylch development as of 2026-03-27. What works, what's in progress,
  immediate next steps, and known issues.
---

# Active Context

## What Is Built and Working

### Core Infrastructure
- PostgreSQL storage layer with 29+ SQLAlchemy ORM models + `error_logs` table
- Alembic migration system (2 migrations: initial schema + error_logs)
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
- **SSE streaming** (`/api/chat/message/stream`) — incremental text delivery with `text_replace` for clean final output
- **Always uses `app_settings.anthropic_model`** — independent of `SYSTEM_LLM_PROVIDER` (production uses OpenAI for chat but Anthropic for MrCall)
- **Retry with backoff** — 3 attempts with exponential backoff (2s, 4s, 8s) for transient Anthropic errors (429, 500, 529)
- **Haiku error humanizer** — user-friendly error messages via Claude Haiku on failure
- **Error logging** — `error_logs` table with business_id, session_id, request_id, Haiku message
- **Fallback message** — after 3 retries exhausted, shows support@mrcall.ai with session ID
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
- `frontend/` directory is dormant (Vue 3 prototype, not active)

### Documentation Harness
- `CLAUDE.md` structured as concise index (~50 lines) with pointers to all docs
- `docs/ARCHITECTURE.md` based on code ground truth
- `docs/active-context.md` tracks current project state

## Completed (Session 2026-03-24/25 — Railway Standalone Deploy + aisuite Migration)

### Railway Standalone Deployment (api.zylchai.com)
1. **PostgreSQL on Railway** (Postgres-FmCF): 30 tables via Alembic, pgvector enabled
2. **litellm → aisuite migration**: litellm quarantined on PyPI (malware in 1.82.7-1.82.8). Replaced with aisuite (Andrew Ng's multi-provider lib). New `zylch/llm/exceptions.py` for provider-agnostic exceptions.
3. **torch → ONNX**: `sentence-transformers[onnx]>=3.0.0` replaces `torch>=2.0.0`. ONNX backend in `embeddings.py`. App RSS ~240MB (was ~650MB).
4. **entrypoint.sh**: Alembic migrations + uvicorn startup. `railway.json` uses `sh -c` for `$PORT` expansion.
5. **Fixes deployed**: `supabase_storage` NameError, `tsv`/`fts_document` GENERATED ALWAYS in upsert, aisuite MCP bug bypass, tool_choice format (native for Anthropic, OpenAI for others), `openai_tools` undefined, `suggested_action` required in task_decision tool, `::vector` → `CAST AS vector` in hybrid search, `Computed` columns for tsv/fts_document in ORM models
6. **Email sync working**: 164 messages synced, auto-reply detection, ONNX embeddings
7. **Task training**: 9 FAQ patterns extracted automatically (service reactivation, pricing, dashboard access, etc.)
8. **Memory training + run**: PERSON/COMPANY/TEMPLATE extraction working. Templates include response patterns for FAQ detection.
9. **Force login**: `?force=true` param on OAuth page signs out existing session to show account picker
10. **System LLM key fallback**: All agent domains (not just mrcall) fall back to system Anthropic key when user has no BYOK

### Railway Config
- `API_SERVER_URL=https://api.zylchai.com`
- `FIREBASE_PROJECT_ID=zylch-test-9a895` (standalone Firebase app)
- `DATABASE_URL` → Railway Postgres-FmCF
- `SYSTEM_LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY` set
- GitHub auto-deploy from `malemi/zylch` main branch (HTTPS token)
- Test account: `support@mrcall.ai` / `REDACTED-FIREBASE-UID`

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

## Completed (Session 2026-03-27 — Streaming + Error Resilience)

### MrCall Agent — Streaming + Error Handling

1. **Incremental streaming** (`5519367`): `run_stream()` intercepts `input_json_delta` events for `respond_text` tool, decoding JSON string escapes on the fly
2. **text_replace** (`74224b0`): At `content_block_stop`, parses complete JSON via `json.loads` and emits properly decoded text to replace streaming artifacts (`\"` → `"`, `\\n` → `\n`)
3. **Retry + error handling** (`5d8af65`): New `mrcall_error_handler.py` with `is_retryable()`, `humanize_error()` (Haiku), `log_error()` (DB), `parse_error_details()`. New `error_logs` table (migration 0002). `FINAL_FALLBACK_MESSAGE` with support@mrcall.ai
4. **Model fix** (`a8adf18`): Always use `app_settings.anthropic_model` (not `self.llm.model` which is `gpt-4.1` when `SYSTEM_LLM_PROVIDER=openai` in production)

### Dashboard (mrcall-dashboard)
- `reactive()` for assistant message — fixes streaming messages disappearing after first chunk
- `onTextReplace` callback in `Zylch.js` + `ZylchChat.vue`
- Typing indicator hidden during active streaming
- Merge conflicts resolved on beta-env (ZylchChat.vue, Zylch.js)

### Infrastructure
- Alembic migration 0002: `error_logs` table
- Railway confirmed: runs `alembic upgrade head` automatically (`railway.json` startCommand)
- Planning principles hook in global `~/.claude/settings.json` (UserPromptSubmit, keyword-filtered)

## Deployed State

- **Railway standalone** (`main` branch → GitHub `malemi/zylch`): auto-deploy, latest commit `fc8852e`. api.zylchai.com
- **Scaleway production** (`production` branch → GitLab): pending push (8 commits ahead on main including streaming + retry)
- **Scaleway test** (`dev` branch → GitLab): pending push
- Railway test account: `support@mrcall.ai` / `REDACTED-FIREBASE-UID`
- Scaleway test user: `mario.alemi+19mar2026@gmail.com` / `mlWH0BnYVHSz0qwDY0xFliUkJIl2`
- Scaleway test business: `738535bd-6a76-3ad1-b0d8-606c02a3df95` (Tiscali Store Cagliari)

## What Is In Progress

Nothing actively in progress — all items from session 2026-03-27 completed.

## Immediate Next Steps

1. **Push to dev + production** — user doing this manually
2. **Verify streaming + web search end-to-end on deployed environments**
3. **Config memory for conversation intent** — currently only saves executed changes, not proposed configurations (edge case: user proposes booking hours, page reload loses context)
4. Fix `category_map` in `zylch/tools/mrcall/config_tools.py` with correct post-rename variable names
5. Fix modifiable logic bug on `config_tools.py:149`

## Known Issues and Tech Debt

- `config_tools.py:109-125` `category_map` has wrong variable names (pre-rename names, missing variables)
- `config_tools.py:149` modifiable logic is wrong: requires both `modifiable` and `advanced` flags true
- MrCall agent hardcoded to Anthropic — cannot use other providers due to `web_search_20250305` dependency
- `SupabaseStorage` class name is misleading (pure SQLAlchemy, legacy name)
- `docs/agents/README.md` lists agents that don't match actual source files
- `frontend/` Vue 3 prototype is dormant but still in repo
- `tools/factory.py` is 2000+ lines (exceeds 500-line rule)
- `.env.development` in mrcall-dashboard changed to point to test-env-0 (was angelo.ngrok.io)
- No external telemetry or monitoring (pre-alpha)
- Single replica deployment (no HA)
- Git branch topology: main, dev, production slightly diverged — need alignment
