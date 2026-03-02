# Zylch Architecture

> **⚠️ PRE-ALPHA DEVELOPMENT**
>
> This project is in active pre-alpha development. There are NO production users, NO data to migrate, and NO backward compatibility requirements.
>
> **Guidelines:**
> - Delete legacy code freely - don't preserve unused columns/tables
> - No dual-write patterns - use the new unified approach only
> - No migration scripts needed - just update the schema directly
> - Break things fast, fix things fast

---

## Critical: No Local Filesystem

**The backend uses Supabase for ALL data storage. NO local filesystem.**

| Data                                                | Storage | Table |
|-----------------------------------------------------|---------|-------|
| OAuth tokens (Google, Microsoft, LLM providers, MrCall) | Supabase | `oauth_tokens` (encrypted) |
| Email data                                          | Supabase | `emails` (with vector/FTS search) |
| Task items                                          | Supabase | `task_items` |
| Calendar events                                     | Supabase | `calendar_events` |
| Sync state                                          | Supabase | `sync_state` |
| Triggers                                            | Supabase | `triggers`, `trigger_events` |
| Memory blobs                                        | Supabase | `blobs`, `blob_sentences` (pg_vector) |

**NEVER use local filesystem for:**
- Token storage (no pickle files)
- Credentials
- Cache

---

## System Overview

Zylch is an AI-powered email assistant that provides relationship intelligence, task management, and automated communication workflows (email, whatsapp, phone, slack etc) through multiple interfaces (CLI, HTTP API).

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Client Interfaces                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐   │
│  │   CLI   │  │   Web   │  │ Mobile  │  │   API   │   │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘   │
└───────┼───────────┼─────────────┼────────────┼─────────┘
        │           │              │            │
        └───────────┴──────────────┴────────────┘
                           ▼
        ┌────────────────────────────────────────┐
        │        FastAPI Backend (Python)        │
        │  ┌──────────────────────────────────┐  │
        │  │       Service Layer              │  │
        │  │  • SyncService                   │  │
        │  │  • ChatService                   │  │
        │  │  • TriggerService (background)   │  │
        │  │  • TaskAgent (task detection)    │  │
        │  │  • Memory Agent Pipeline         │  │
        │  └──────────────────────────────────┘  │
        │  ┌──────────────────────────────────┐  │
        │  │       Tool System                │  │
        │  │  • Email (Gmail/Outlook)         │  │
        │  │  • Calendar (Google/MS)          │  │
        │  │  • StarChat (MrCall)             │  │
        │  │  • Memory (ZylchMemory)          │  │
        │  └──────────────────────────────────┘  │
        └────────────────┬───────────────────────┘
                         │
        ┌────────────────┴───────────────────────┐
        │                                         │
        ▼                                         ▼
┌───────────────┐                      ┌──────────────────┐
│   Supabase    │                      │  External APIs   │
│  (Postgres)   │                      │  • Gmail API     │
│               │                      │  • Calendar API  │
│ • RLS enabled │                      │  • Graph API     │
│ • pg_vector   │                      │  • StarChat      │
│ • encrypted   │                      │  • Claude        │
└───────────────┘                      └──────────────────┘
```

### Active User Interfaces

| Interface | Location | Stack | Status |
|-----------|----------|-------|--------|
| **zylch-cli** | `~/hb/zylch-cli` | Python (Textual TUI) | Active - primary Zylch user interface |
| **mrcall-dashboard** | `~/hb/mrcall-dashboard` | Vue 3, Vuex, PrimeVue | Active - MrCall business configuration |
| **Zylch API** | `zylch/api/` | FastAPI | Active - backend for all interfaces |
| **Zylch web frontend** | `frontend/` | Vue 3, Pinia, Tailwind | **Dormant** - prototype, not under active development |

## Deployment Model

The Zylch backend (`zylch/api/`) is a single codebase that serves **two distinct products** depending on configuration:

| Deployment | `.env` file | Firebase Project | Purpose | Users connect via |
|------------|-------------|-----------------|---------|-------------------|
| **Zylch** | `.env.development` / `.env.production` | `zylch-test-9a895` | Full AI email assistant (Gmail, Calendar, Memory, Tasks) | zylch-cli (`~/hb/zylch-cli`) |
| **MrCall Configurator** | `.env.mrcall` | `talkmeapp-e696c` | MrCall assistant configuration only | mrcall-dashboard (`~/hb/mrcall-dashboard`) |

**Why two deployments?**
- **Different Firebase projects**: Zylch users authenticate via `zylch-test` Firebase, MrCall Dashboard users via `talkmeapp` Firebase. Firebase tokens are not interchangeable across projects.
- **Different feature scope**: Zylch exposes the full feature set (email, calendar, memory, tasks, etc.). MrCall Configurator only exposes MrCall assistant configuration via sandbox mode.
- **Different Google OAuth clients**: Each deployment uses a different GCP project for Google OAuth (see [Environment Files](#configuration)).

**Same codebase, same Supabase**: Both deployments share the same Supabase database and the same code. The `.env` file determines which Firebase project validates tokens and which Google OAuth client is used.

**Release process**: Changes to the backend require deploying both Railway instances (if both are affected). Changes to zylch-cli require a separate CLI release.

## Local Development

**Local development uses the SAME architecture as production:**
- Firebase Auth for user authentication
- Supabase for all data storage (emails, calendar, tokens, tasks, memory blobs)
- Same OAuth flows as production (server-side, not InstalledAppFlow)
- No separate local database or file-based token storage

Run locally with `uvicorn zylch.api.main:app --reload --port 8000` — symlink `.env` to the deployment you're working on (`.env.development` for Zylch, `.env.mrcall` for MrCall Configurator).

## Core Components

### 1. Agents (`zylch/agents/`)
- **Purpose**: User-facing conversational agents with multiple tools
- **Key Files**:
  - `base_agent.py`: SpecializedAgent base class for multi-tool agents
  - `emailer_agent.py`: Email composition and search agent
  - `mrcall_agent.py`: Runs unified MrCall agent with 4 tools (configure_*, get_current_config, respond_text)
- **Sub-packages**:
  - `trainers/`: Agent trainers (generate personalized prompts from user data)
    - `mrcall_configurator.py`: Layer 1 - Generates feature-specific sub-prompts for MrCall. All features use a unified `dynamic_context` path: `_build_variables_context()` fetches variable metadata from StarChat API (`nested=True`, `languageDescriptions` param), parses the collections-array response `[{variables: [...]}]`, and injects per-variable context (humanName, description, defaultValue, type, current value) into meta-prompts via `{variables_context}` placeholder. Additionally, `_build_conversation_variables_context()` parses `ASSISTANT_TOOL_VARIABLE_EXTRACTION` from the business config to discover caller-extracted variables (FIRST_NAME, EMAIL_ADDRESS, etc.), combines them with static `public:*` variables (date/time, business status) and exportable aliases (CALLER_NUMBER, RECURRENT_CONTACT), and injects via `{conversation_variables_context}` placeholder. Both context builders accept an optional pre-fetched `business` dict to avoid redundant API calls.
    - `mrcall.py`: Layer 2 - Combines sub-prompts into unified agent with tool selection
    - `memory_email.py`: EmailMemoryAgentTrainer for fact extraction
    - `task_email.py`: EmailTaskAgentTrainer for task detection
  - See [docs/agents/mrcall-configurator.md](agents/mrcall-configurator.md) for full architecture

### 1b. Workers (`zylch/workers/`)
- **Purpose**: Background data processors (not user-facing)
- **Key Files**:
  - `memory.py`: MemoryWorker - Extracts facts from emails/calendar into memory blobs
  - `task_creation.py`: TaskWorker - Task detection and processing

### 2. Tools (`zylch/tools/`)
Modular tools for agent capabilities:
- **Email**: Gmail/Outlook API wrapper, draft management, sending
- **Archive**: Permanent email storage in Supabase with full-text search
- **Calendar**: Google/Outlook Calendar integration with Meet/Teams links
- **Tasks**: Email-to-task extraction, relationship gap analysis
- **CRM**: Pipedrive integration (optional)
- **Contacts**: StarChat/MrCall integration
- **SMS**: Vonage SMS sending (requires `/connect vonage` in CLI)
- **Read Tracking**: Email open tracking via SendGrid webhooks and custom pixels

### 2.5 Domain Models & ML (`zylch/models/`, `zylch/ml/`)
- **Importance Rules** (`zylch/models/importance_rules.py`): User-configurable rules for contact prioritization
- **Anonymizer** (`zylch/ml/anonymizer.py`): PII detection and replacement for training data extraction

**Key Pattern**: Tools are identical for all users. Credentials are loaded per-user at execution time from Supabase. If a user hasn't connected a provider, the tool returns a helpful error (e.g., "Vonage not connected. Please use /connect vonage").

**Tool Registration** (`factory.py`):
```python
def create_all_tools(config, memory, owner_id):
    tools = [
        _SyncEmailsTool(sync_service),
        _GetContactTool(starchat_client),
        _GetWhatsAppContactsTool(starchat_client),
        _SearchLocalMemoryTool(memory, search_engine),
        _GetTasksTool(supabase_client),
        # ... more tools
    ]
    return tools
```

### 3. Two-Tier Email System (Cloud-Based)

**Current Implementation: Supabase-Only**

All email data is stored in Supabase, scoped by `owner_id` (Firebase UID).

**Tier 1: Email Archive (Supabase)**
- **Purpose**: Permanent storage of email metadata and content
- **Technology**: Supabase Postgres
- **Tables**: `email_archive`, `email_messages`
- **Sync**: Gmail/Outlook History API (incremental, <1s)
- **Features**: Complete history, cross-device access

**Tier 2: Task Intelligence (Supabase `task_items`)**
- **Purpose**: Extracted tasks with source traceability
- **Technology**: Supabase Postgres
- **Content**: Task action, urgency, contact info, sources JSONB
- **Features**: Full traceability via `sources` column linking to emails/blobs

**Data Flow**:
```
Gmail/Outlook API
       ↓
Supabase (emails) ← Email metadata/content stored here
       ↓
Claude AI (task extraction)
       ↓
Supabase (task_items) ← Tasks with sources stored here
```

**Privacy Note**: Email content is stored encrypted at rest by Supabase. All data is scoped by `owner_id` with Row Level Security (RLS).

### 4. Service Layer (`zylch/services/`)

**Purpose**: Business logic shared between CLI and API (no duplication)

**Key Services**:
- **SyncService**: Email/calendar synchronization
  - `sync_emails()`, `sync_calendar()`, `run_full_sync()`
  - **Calendar always syncs 14 days forward** regardless of `--days` parameter (emails respect `--days` for past)
- **ChatService**: Conversational AI (wraps CLI for tool access)
- **ArchiveService**: Email archive operations
- **CommandHandlers**: Slash command processing (v0.3.0+)
  - All `/command` handlers in one module
  - Returns markdown strings (no Anthropic API calls)
  - Used by both CLI and web app
- **TriggerService**: Event-driven automation (v0.3.0+)
  - Queues and processes trigger events
  - Background worker for async execution

### User Notification System

Background workers notify users of failures via `user_notifications` table. Notifications are shown once in chat (prepended to response), then marked read.

**Key files**: `supabase_client.py` (`create_notification()`), `chat_service.py` (injection)

**Pattern**: CLI and API both use the same service layer functions

```python
# CLI uses:
sync_service.run_full_sync(days_back=30)

# API exposes:
POST /api/sync/full {"days_back": 30}
# → calls sync_service.run_full_sync(days_back=30)
```

### 5. API Layer (`zylch/api/`)

**Structure**:
```
routes/        # FastAPI endpoints
services/      # Business logic layer (shared with CLI)
```

**Key APIs**:
- `/api/chat` - Conversational AI endpoint (wraps CLI)
- `/api/archive` - Email archive operations
- `/api/sync` - Email/calendar sync
- `/api/gaps` - Relationship gap analysis
- `/api/commands` - Command discovery and help (see below)
- `/api/mrcall/training/status` - MrCall training status (snapshot-based change detection)
- `/api/mrcall/training/start` - Start MrCall training (selective retraining)
- `/api/webhooks/sendgrid` - Email read tracking webhooks
- `/api/track/pixel/{tracking_id}` - Tracking pixel endpoint

**Static Endpoints** (served directly from `main.py`):
- `/` - API info (name, version, status)
- `/health` - Health check
- `/robots.txt` - SEO/crawler directives (allows `/`, `/health`, `/docs`; disallows `/api/`, `/webhooks/`)

### Commands API (`/api/commands`)

**Purpose**: Expose command metadata so any frontend (CLI, web, mobile) can discover available commands and their help text. The backend is the single source of truth.

**Endpoints**:
- `GET /api/commands` - List all commands with summaries
- `GET /api/commands/help` - Get help for all commands
- `GET /api/commands/help?cmd=gaps` - Get detailed help for specific command

**Source of Truth**: `COMMAND_HELP` dict in `zylch/services/command_handlers.py`

**Help via Chat**: Sending `/gaps --help` (or any command with `--help`) returns help text without executing the command. This is handled by the dispatcher in `chat_service.py` before routing to handlers.

### 6. Semantic Command Matching (`zylch/services/`)

Natural language triggers that route to slash commands without using Claude API. Uses **hybrid scoring** (same pattern as memory blob search).

**Exclusions**: Semantic matching is skipped when in Task Mode, MrCall Config Mode, or when the input starts with `/mrcall` (to prevent false rewrites of valid slash commands).

**Key Files**:
- `trigger_parser.py`: Hybrid matching (keyword + semantic) with typed parameter DSL
- `command_matcher.py`: Routes natural language to commands
- `command_handlers.py`: `COMMAND_TRIGGERS` dict with trigger templates

**Hybrid Scoring** (same as HybridSearchEngine):
```
hybrid_score = alpha * keyword_overlap + (1-alpha) * semantic_similarity
```
- Default `alpha=0.5` (balanced keyword + semantic)
- Keyword matching: FTS-style coverage scoring with stop word removal
- Semantic matching: Cosine similarity with `all-MiniLM-L6-v2` embeddings
- Threshold: 0.65 minimum confidence for match

**How It Works**:
1. User input embedded with `all-MiniLM-L6-v2` (same model as memory)
2. Keywords extracted (stop words removed)
3. Hybrid score computed against pre-computed trigger embeddings
4. If match > 0.65 confidence, extract typed parameters and route to command
5. Parameters extracted using `{param:type}` DSL syntax

**Typed Parameter DSL**:
```python
COMMAND_TRIGGERS = {
    '/sync': [
        "sync",
        "synchronize the past {days:int} days",
    ],
    '/stats': [
        "stats", "email stats", "inbox statistics",
    ],
    '/tasks': [
        "tasks", "my tasks", "what do I need to do",
    ],
}
```

**Supported Types**: `int`, `email`, `text`, `date`, `time`, `duration`, `model`

**Example**:
```
Input: "sync"
Keyword score: 1.0 (exact match)
Semantic score: 0.85
Hybrid (alpha=0.5): 0.925 → "/sync"

Input: "synchronize with the past 2 days"
Keyword score: 0.8
Semantic score: 0.90
Hybrid: 0.85 → "/sync 2"
```

**Performance**: <100ms matching (embeddings cached after first load)

### 7. CLI (`zylch/cli/main.py`)
Interactive command-line interface:
- `/sync` - Sync emails, calendar, pipedrive (data only, no processing). Calendar always syncs 14 days forward.
- `/email list|create|send|delete|search` - Email and draft management
- `/agent memory train email` - Generate personalized memory extraction agent
- `/agent memory run email` - Extract facts from emails + calendar into memory blobs (email channel includes calendar automatically)
- `/agent task train email` - Generate personalized task detection agent (calendar-aware, unified prompt)
- `/agent task process email` - Detect tasks from emails + calendar (email channel includes calendar automatically)
- `/memory search` - Search entity memories
- `/tasks` - Show detected tasks
- `/reset` - Reset all user data (requires `--hard` confirmation)
- `/tutorial` - Getting started guide and daily workflow
- Natural conversation with agent

**Note**: The `email` channel automatically includes calendar events. There is no separate `calendar` channel - output shows separate counts for transparency (e.g., "42 emails, 15 calendar events").

### 8. Memory System (Entity-Centric Blobs)

**Core Principle: A person is NOT an email address.**

A person can have multiple email addresses, phone numbers, and names. The memory system stores knowledge as entity blobs with sentence-level embeddings. Entity identity lives IN the blob content (not in namespace structure), found via hybrid search.

**Namespace = Ownership** (e.g., `user:{owner_id}`), not per-entity. This prevents fragmentation when the same entity appears in different contexts.

**Namespace Pattern**: `{scope}:{identifier}`

| Namespace | Purpose | Example |
|-----------|---------|---------|
| `user:{owner_id}` | Personal memories | `user:abc123` |
| `global:skills` | System-wide patterns | `global:skills` |
| `shared:{recipient}:{sender}` | Shared intelligence | `shared:xyz789:abc123` |

**Cascading Retrieval**:
1. Search `user:{owner_id}` (1.5x relevance boost for personal patterns)
2. If no match, search `global:skills` (system patterns)
3. If sharing enabled, search `shared:{owner_id}:{*}` (received intelligence)

**Data Flow**:
```
Gmail/Calendar/Pipedrive → /sync → Local Tables (emails, calendar_events)
                                          ↓
                              /agent process (MemoryWorker)
                                          ↓
                           Extract facts via LLM
                                          ↓
                          Hybrid search for existing blob
                                          ↓
                    [Found] LLM-merge → Update blob
                    [Not found] → Create new blob
                                          ↓
                              Mark source as processed
```

**Key Tables**:
- `emails.memory_processed_at` - NULL = unprocessed, timestamp = when processed
- `calendar_events.memory_processed_at` - Same pattern
- `blobs` - Entity-centric memory storage
- `blob_sentences` - Sentence-level embeddings for search

**Commands**:
- `/sync` - Fetches data to local DB (no processing)
- `/agent memory run email` - Process emails + calendar into blobs (email includes calendar automatically)
- `/memory search <query>` - Hybrid FTS + semantic search
- `/memory reset` - Delete blobs AND reset processing timestamps

**Reconsolidation**: When storing new facts, system searches for existing blob about same entity (hybrid score ≥ 0.65). If found, LLM merges old + new content. This prevents duplicate blobs about same person/topic.

### Task Display: `get_tasks` Tool

`_GetTasksTool` in `factory.py` queries the `task_items` table directly, applying urgency ordering (high → medium → low) and limiting low-urgency tasks to 10. Tasks are populated by `/agent task process` after email sync.

## Key Architectural Decisions

### Decision 1: Two-Tier Email Storage

**Problem**: Old system re-fetched 600+ emails every sync (15-30 min), lost history outside 30-day window

**Solution**:
- **Archive**: Permanent Supabase storage (all emails forever)
- **Intelligence Cache**: 30-day analyzed window in Supabase (AI-enriched)

**Benefits**:
- 100x faster sync (<1s vs 15-30min)
- Complete history preserved
- Efficient AI analysis (only recent emails)

### Decision 2: Manual Closure Persistence

**Problem**: User-closed threads reopened after sync

**Solution**: `manually_closed` flag in thread data
- Set by `mark_threads_closed_by_subject()`
- Preserved during sync (NEVER re-analyze manually closed threads)
- Respected by gap analysis

### Decision 3: Auto-Sync After Email Send

**Problem**: Analysis outdated after sending emails

**Solution**: Trigger incremental sync after `send_gmail_draft`
- Adds 1-3s latency to email send (acceptable)
- Keeps cache current automatically
- Implementation in `factory.py:_SendDraftTool`

### Decision 4: Chat API Wraps CLI

**Problem**: Duplicating tool initialization for HTTP API

**Solution**: `ChatService` wraps `ZylchAICLI` class
- Reuses all tool initialization
- No code duplication
- Single source of truth

**Trade-off**: Inherits CLI dependencies (memory system, StarChat)

## Data Storage

### Current: Supabase (Cloud-Based)

**All data stored in Supabase**, scoped by `owner_id` (Firebase UID):

| Table | Purpose |
|-------|---------|
| `emails` | Email metadata and content with vector embeddings for semantic search |
| `task_items` | Task items with `sources` JSONB for data traceability |
| `calendar_events` | Calendar events |
| `sync_state` | Gmail/Outlook history IDs, last sync timestamps |
| `oauth_tokens` | All tokens (Google, Microsoft, Anthropic, MrCall) - encrypted |
| `scheduled_jobs` | Scheduled reminders and timed actions |
| `triggers` | Triggered instructions |
| `trigger_events` | Event queue for trigger processing |
| `sharing_auth` | Sharing authorizations |
| `user_notifications` | System notifications for users |
| `email_triage` | AI triage verdicts per thread |
| `importance_rules` | User-configurable contact importance rules |
| `triage_training_samples` | Anonymized training data + user corrections |
| `email_read_events` | Email read tracking events (SendGrid + custom pixel) |
| `sendgrid_message_mapping` | SendGrid message ID to Zylch message ID mapping |
| `agent_prompts` | Personalized agents generated from user email patterns. Also stores MrCall training snapshots (`mrcall_{business_id}_snapshot`) for selective retraining |

**Email Triage Tables** (December 2025):

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `email_triage` | Stores AI triage verdicts | `thread_id`, `needs_human_attention`, `triage_category`, `is_cold_outreach` |
| `importance_rules` | User-defined contact priority rules | `condition`, `importance`, `priority`, `enabled` |
| `triage_training_samples` | Training data for small model fine-tuning | `email_data` (anonymized), `predicted_verdict`, `feedback_type` |

**Modified Columns**:

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `emails` | `is_auto_reply` | BOOLEAN | RFC 3834 auto-reply flag |
| `emails` | `auto_reply_headers` | JSONB | Raw headers for debugging |
| `messages` | `read_events` | JSONB | Email read tracking events array |

**Security**:
- All tables use Row Level Security (RLS) scoped by `owner_id`
- Sensitive tokens encrypted with Fernet before storage
- Supabase provides encryption at rest

### Future: Local-First Options

When desktop/mobile apps are developed, we may explore local-first storage (SQLite + sqlcipher for CLI/Desktop, IndexedDB for PWA, Capacitor for mobile). Decision pending until those apps are built.

### Token Storage & Credentials

**Unified Credentials Architecture** (December 2025):

All user credentials (OAuth tokens, API keys) are stored in Supabase's `oauth_tokens` table using a unified JSONB column. This enables:
- **BYOK (Bring Your Own Key)**: Users provide their own API keys (Anthropic, Vonage, etc.)
- **Zero-schema migrations**: Add new providers by inserting database rows, not code changes
- **Encrypted storage**: Fernet encryption for all sensitive credentials
- **No filesystem fallback**: All credentials in Supabase only

**Key tables**:
- `oauth_tokens`: User credentials (encrypted JSONB)
- `integration_providers`: Provider configuration (dynamic UI generation)
- `oauth_states`: CSRF protection for OAuth flows

**For complete details**, see [Credentials Management Documentation](architecture/credentials-management.md)

### Configuration
- **Environment**: Railway env vars (backend), Vercel env vars (frontend)
- **Defaults**: `zylch/config.py` (Pydantic settings)
- **System .env contains**: Supabase config, Firebase config, Google OAuth client, encryption key, optional `ANTHROPIC_API_KEY` (system-level fallback for integrations), LLM model names (`ANTHROPIC_MODEL`, `OPENAI_MODEL`, `MISTRAL_MODEL`, `DEFAULT_MODEL`)
- **NOT in .env**: User credentials (Pipedrive, Vonage) - these are BYOK via `/connect`
- **Optional in .env**: `ANTHROPIC_API_KEY` - system-level fallback when user has no key (used by MrCall integration)
- **Optional in .env**: `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `MISTRAL_MODEL` - override default model per provider (defaults defined in `config.py`)
- **CRITICAL**: `MRCALL_BASE_URL` must point to the same StarChat server as the MrCall Dashboard's `VUE_APP_STARCHAT_URL`. In dev both use `https://test-env-0.scw.hbsrv.net`; in production both use `https://api.mrcall.ai`. A mismatch causes "business not found" errors because business data is server-specific.

**Environment Files** (symlink `.env` → the one you need):

| File | Purpose | Firebase Project | Google OAuth Client (GCP project) |
|------|---------|-----------------|-----------------------------------|
| `.env.development` | Zylch local dev | `zylch-test-9a895` | `49237749736-...` (`zylch-test`) |
| `.env.production` | Zylch prod (Railway) | `zylch-test-9a895` | `49237749736-...` (`zylch-test`) |
| `.env.mrcall` | MrCall Dashboard backend | `talkmeapp-e696c` | `375340415237-...` (`talkmeapp`) |

**⚠️ Common pitfall**: Using `.env.mrcall` when testing Zylch CLI features like `/connect google` causes `redirect_uri_mismatch` because the Google OAuth client (`375340415237-...`) belongs to a different GCP project that may not have `http://localhost:8000/api/auth/google/callback` registered. MrCall Dashboard users don't need `/connect google` — they only use `/connect mrcall`.

### Firebase Service Account

Stored as **Base64-encoded JSON** in Railway env vars:

```bash
# Encode the service account JSON:
cat firebase-service-account.json | base64

# Set in Railway:
FIREBASE_SERVICE_ACCOUNT_BASE64=eyJ0eXBlIjoic2VydmljZV9hY2NvdW50Ii...
```

Backend decodes automatically on startup (`zylch/api/firebase_auth.py`).

## External Integrations

### Google APIs
- **Gmail**: Read, send, drafts (OAuth 2.0)
- **Calendar**: Events, Meet links (OAuth 2.0)
- **Auth**: Shared credentials for Gmail + Calendar

### LLM Providers (BYOK via LiteLLM)

Zylch supports multiple LLM providers through LiteLLM abstraction:

| Provider | Default Model | Region | Features |
|----------|---------------|--------|----------|
| **Anthropic** | `claude-opus-4-6-20260205` | US | Tool use, web search, prompt caching |
| **OpenAI** | `gpt-4.1` | US | Tool use (1M context) |
| **Mistral** | `mistral-large-3` | 🇪🇺 EU | Tool use, GDPR-friendly |

**Model Configuration**: One model per provider, configured via environment variables (`ANTHROPIC_MODEL`, `OPENAI_MODEL`, `MISTRAL_MODEL`). `PROVIDER_MODELS` in `zylch/llm/providers.py` reads from `zylch/config.py` settings (pydantic-settings). No multi-tier model selection — the same model handles all tasks (classification, drafting, analysis). `ModelSelector` in `zylch/assistant/models.py` is a pass-through that returns the configured default model (supports `force_model` override).

**Credential Storage**: User provides API key via `/connect <provider>`
**System-level fallback**: If `ANTHROPIC_API_KEY` is set in `.env`, it's used when the user has no key configured. This enables integrations like MrCall Dashboard where the operator provides the key so users don't need to run `/connect anthropic`.
**Provider Selection**: `get_active_llm_provider(owner_id)` checks connected providers in order. If no user key found, `ToolConfig.from_settings_with_owner()` falls back to `settings.anthropic_api_key`.

**Anthropic-Only Features**:
- Web search (`web_search_20250305` tool type)
- Prompt caching (`cache_control: {"type": "ephemeral"}`)

Non-Anthropic providers see a clear message when attempting to use these features.

### Optional Integrations (All BYOK)
- **Pipedrive**: CRM sync (user provides API token via `/connect pipedrive`)
- **Vonage**: SMS sending (user provides API key/secret via `/connect vonage`)
- **StarChat/MrCall**: Contact management, WhatsApp integration (pending API endpoint)
- **SendGrid**: Bulk email (not currently used)

### WhatsApp Integration (Pending)

**Status**: Tool structure ready, awaiting StarChat REST API endpoint

**Architecture**:
- Tool: `_GetWhatsAppContactsTool` in `factory.py`
- Client method: `StarChatClient.get_whatsapp_contacts()`
- Required endpoint: `GET /mrcall/v1/crm/whatsapp/{businessId}/messages`
- Authentication: StarChat BasicAuth (NEVER direct database access)

**Implementation**:
1. Tool registered and ready to use
2. Returns empty list with message until StarChat provides endpoint
3. See `STARCHAT_REQUESTS.md` Request #3 for API specification

**Critical Security Rule**:
- **NEVER** bypass StarChat authentication with direct PostgreSQL access
- **ALWAYS** use StarChat REST API endpoints with proper authentication
- All data access must go through authenticated API calls

### /connect Command Architecture

Provider connections are managed through a unified backend system:

**Backend (single source of truth):**
- `GET /api/connections/providers/{provider}` - Returns provider metadata (config_fields, labels, env_vars)
- `POST /api/connections/provider/{provider}/credentials` - Saves user credentials
- `DELETE /api/connections/provider/{provider}/credentials` - Disconnects provider
- `GET /api/connections/status` - Shows all connection statuses
- `/connect reset <provider>` - Disconnects specific provider (via chat command)

**Database:**
- `integration_providers` table defines all providers with `config_fields` JSONB
- Adding a new provider = SQL INSERT only (no code changes needed)
- `config_fields` includes: type, label, required, encrypted, env_var

**CLI (thin client):**
- Calls backend API for provider info
- Displays dynamic form based on `config_fields`
- Checks environment variables using `env_var` from config_fields
- Sends credentials to backend for storage

**Provider Types:**
- OAuth providers (google, microsoft, mrcall): CLI handles browser redirect
- API-key providers (anthropic, openai, mistral, vonage, pipedrive, sendgrid, etc.): CLI shows form, backend stores

Supported providers: google, microsoft, mrcall, anthropic, openai, mistral, pipedrive, vonage, sendgrid

## Security & Privacy

### Current: Cloud-Based Storage

| Data | Where Stored | Security |
|------|--------------|----------|
| Email content | Supabase | RLS + encryption at rest |
| Email metadata | Supabase | RLS + encryption at rest |
| AI summaries | Supabase | RLS + encryption at rest |
| OAuth tokens | Supabase | RLS + Fernet encryption |
| Sync state | Supabase | RLS |

**How it works**:
1. Emails fetched from Gmail/Outlook API by backend
2. Stored in Supabase with `owner_id` scoping (Row Level Security)
3. Task extraction performed on-demand, stored in `task_items` with source traceability
4. All sensitive tokens (OAuth, API keys) encrypted with Fernet before storage

**Privacy model**:
- All data scoped by Firebase UID (`owner_id`)
- Row Level Security ensures users only access their own data
- Supabase provides encryption at rest
- No data shared between users

### RLS & Service Role Key

**Important**: The backend uses Supabase's **service role key**, which **bypasses RLS entirely**.

```python
# From supabase_client.py
# Use service_role key for backend (bypasses RLS, we enforce owner_id manually)
```

**Why?**
- We use **Firebase Auth** (not Supabase Auth)
- `owner_id` is a Firebase UID (text string like `"abc123xyz"`), not a Supabase UUID
- Supabase's `auth.uid()` returns Supabase UUIDs, which don't match Firebase UIDs
- RLS policies using `auth.uid()` won't work with Firebase tokens

**How we enforce security instead**:
- Every query manually filters by `owner_id`
- The backend validates Firebase JWT before any operation
- Service role key is never exposed to frontend

**RLS policies in migrations**:
- Still defined for defense-in-depth
- Would protect if someone accidentally used the anon key
- Use `current_setting('request.jwt.claims', true)::json->>'sub'` pattern for JWT-based RLS (not `auth.uid()`)

**Future consideration**: Local-first architecture (see "Future: Local-First Options" above) would provide stronger privacy guarantees by keeping email content on user devices only.

### Authentication

**For complete authentication details**, see [Credentials Management Documentation](architecture/credentials-management.md)

**Summary**:
- **Firebase Auth**: JWT tokens validated on all API endpoints
- **OAuth 2.0**: Secure flow with CSRF protection for Google/Microsoft/MrCall
- **Token Auto-Refresh**: Automatic refresh before expiration (frontend & CLI)

#### MrCall OAuth 2.0 Integration

**Authentication Method**: Authorization Code flow with PKCE (Proof Key for Code Exchange)

**OAuth Flow**:
1. User runs `/connect mrcall` command in CLI
2. Backend generates OAuth authorization URL with PKCE challenge
3. CLI starts local HTTP server on port 8765 and opens browser
4. User redirected to StarChat consent page (https://test-env-0.scw.hbsrv.net/)
5. User logs in and approves permission on StarChat
6. StarChat redirects to http://localhost:8765/callback with authorization code
7. CLI sends code to backend which exchanges it for access/refresh tokens
8. Backend stores encrypted tokens in Supabase `oauth_tokens` table
9. Tokens automatically refreshed with 5-minute expiration buffer

**Key Components**:
- **Backend Endpoints** (`zylch/api/routes/auth.py`):
  - `GET /api/auth/mrcall/authorize` - Generates OAuth URL with PKCE
  - `POST /api/auth/mrcall/callback` - Exchanges code for tokens
  - `GET /api/auth/mrcall/status` - Checks connection status
  - `POST /api/auth/mrcall/revoke` - Revokes and deletes tokens

- **CLI OAuth Handler** (`zylch/cli/oauth_handlers.py`):
  - Local HTTP server on port 8765 for OAuth callback
  - Browser automation for consent page
  - PKCE verifier management

- **Token Storage** (`zylch/api/token_storage.py`):
  - Encrypted storage in Supabase `oauth_tokens.credentials` (JSONB)
  - Automatic token refresh with 5-minute buffer
  - Integration with StarChat client

- **StarChat Client** (`zylch/tools/starchat.py`):
  - Supports three auth types: OAuth (CLI), Firebase (Dashboard), Basic Auth (legacy)
  - Both OAuth and Firebase tokens sent via `auth` header (not `Authorization`)
  - All authenticated endpoints use `delegated_{realm}` path prefix (e.g., `/mrcall/v1/delegated_mrcall0/crm/...`)
  - Automatic token refresh on 401 responses (OAuth only)
  - Fallback to Basic Auth if OAuth not configured

**Configuration** (`zylch/config.py`):
- `MRCALL_CLIENT_ID`: OAuth client ID (partner_e2e68f877b0722f7)
- `MRCALL_CLIENT_SECRET`: OAuth client secret (encrypted)
- `MRCALL_REALM`: MrCall realm (default: mrcall0)
- `MRCALL_BASE_URL`: StarChat API base URL (test: https://test-env-0.scw.hbsrv.net/)

**OAuth Scopes Requested**:
```
business:read business:write contacts:read contacts:write sessions:read sessions:write templates:read
```
- `business:write` is required for updating assistant variables via `/agent mrcall run`

**Security Features**:
- PKCE prevents authorization code interception
- State parameter prevents CSRF attacks
- Tokens encrypted with Fernet before Supabase storage
- Local callback server only accepts connections from localhost
- Automatic token cleanup on revocation

**Token Refresh Strategy**:
- Tokens refreshed when within 5 minutes of expiration
- Refresh happens automatically on API calls via StarChat client
- Failed refresh triggers re-authentication prompt

#### MrCall Dashboard Integration

The MrCall Dashboard (Vue.js) integrates with Zylch via the `/api/chat` endpoint, sharing the same Firebase project (`talkmeapp-e696c`) so authentication tokens are interchangeable. Dashboard users require **zero manual setup** — no `/connect mrcall`, no `/connect anthropic`, no `/mrcall link`.

**Integration Flow**:
1. User clicks "Configure with AI" button on BusinessConfiguration page
2. Dashboard navigates to `ConfigureAI.vue` with `businessId` in query params
3. On mount, the page automatically sends `/mrcall open <businessId>` to Zylch
4. Zylch enters MrCall config mode for that assistant
5. Left sidebar provides quick command buttons (`/mrcall variables`, `/mrcall show`, `/help`)

**Seamless Authentication**:
- Dashboard sends the user's Firebase JWT in `Authorization: Bearer <token>` header
- Zylch API (`routes/chat.py`) extracts the raw token and passes it in context as `firebase_token`
- `_enter_mrcall_config_mode()` creates a `StarChatClient` with `auth_type="firebase"`, passing the JWT via StarChat's `auth` header
- This works because both apps share Firebase project `talkmeapp-e696c` — StarChat accepts the token and returns `x-mrcall-role: owner`

**Auto-Link**: When `/mrcall open <businessId>` is sent, the business_id is automatically linked for the user (`set_mrcall_link()`), so subsequent commands like `/mrcall variables` work without a separate `/mrcall link` step.

**Semantic Matcher Exclusion**: Messages starting with `/mrcall` bypass the semantic command matcher, and messages in MrCall config mode skip semantic matching entirely. This prevents false rewrites (e.g., `/mrcall open` being rewritten to something else).

**Key Files (Dashboard at ~/hb/mrcall-dashboard)**:
- `src/views/ConfigureAI.vue` - Two-column layout (commands sidebar + chat) with training status indicator
- `src/views/business/BusinessConfiguration.vue` - Business config page with training status button (green/red/yellow)
- `src/components/ZylchChat.vue` - Chat component using Zylch API
- `src/utils/Zylch.js` - API client (uses `Authorization: Bearer` header, includes training API methods)

**System-Level API Key**: The MrCall `.env` includes `ANTHROPIC_API_KEY` so dashboard users don't need to run `/connect anthropic`. The key stays server-side and is never exposed to the frontend. If a user has their own key via `/connect anthropic`, that takes priority.

**Firebase Token Authentication**: Dashboard users authenticate via Firebase JWT (shared Firebase project `talkmeapp-e696c`). Since they don't run the CLI OAuth flow, MrCall commands create a `StarChatClient` with `auth_type="firebase"` using the Firebase token from the request context. This bypasses the OAuth credential lookup entirely. The pattern is:
```python
is_dashboard = context and context.get("source") in ("dashboard", "mrcall_dashboard")
firebase_token = context.get("firebase_token") if context else None

if is_dashboard and firebase_token:
    starchat = StarChatClient(
        base_url=settings.mrcall_base_url,
        auth_type="firebase",
        jwt_token=firebase_token,
        realm=settings.mrcall_realm,
        owner_id=owner_id,
    )
```

#### MrCall Dashboard Sandbox Mode

Dashboard users operate in a restricted "sandbox" environment that limits access to MrCall configuration features only.

**Sandbox Enforcement**:
- **Detection**: `X-Client-Source: mrcall_dashboard` HTTP header identifies dashboard requests
- **Gate Location**: Command execution blocked at COMMAND_HANDLERS dispatch (not at parsing)
- **Extensibility**: `sandbox_mode: Optional[str]` in SessionState allows future sandbox types

**Allowed Commands** (whitelist):
| Command | Behavior |
|---------|----------|
| `/mrcall *` | All subcommands except `/mrcall exit` |
| `/agent mrcall *` | Only agent mrcall permitted |
| `/help` | Shows sandbox-specific help |

**Blocked Commands** (everything else):
| Command | Result |
|---------|--------|
| `/email`, `/calendar`, `/tasks`, `/memory`, `/sync`, `/connect`, etc. | "Comando non disponibile nella dashboard MrCall" |
| `/mrcall exit` | Blocked (user must stay in config mode) |

**Semantic Matching**: Natural language still works, but the resulting command is blocked at execution. Example: "sincronizza le email" → `/sync` → blocked.

**Free-form Chat**: Allowed only when in MrCall config mode (user must first `/mrcall open <id>`).

**Slash Command Routing**: When in MrCall config mode, only free-form messages (not starting with `/`) are routed to the MrCall Orchestrator Agent. Slash commands like `/agent mrcall train` bypass the config mode router and go directly to their normal handlers. This is enforced in `chat_service.py` with `if not user_message.strip().startswith('/')`.

**Key Files**:
- `zylch/services/sandbox_service.py` - Whitelist logic and blocked responses
- `zylch/tools/factory.py` - `SessionState.sandbox_mode`
- `zylch/api/routes/chat.py` - X-Client-Source header detection
- `zylch/services/chat_service.py` - Sandbox gates at multiple points

### Sensitive Data Encryption

**All User Credentials (BYOK)**:
- **Storage**: Supabase `oauth_tokens` table in unified `credentials` JSONB column
- **Encryption**: Fernet (AES-128-CBC + HMAC) via `zylch/utils/encryption.py`
- **Key**: `ENCRYPTION_KEY` environment variable (set in Railway)
- **No fallback**: If user hasn't connected a provider, tools return helpful error (not system default)
- **Applies to**: Anthropic API key, Vonage credentials, Pipedrive token, OAuth tokens

**For complete details on the unified credentials system**, see [Credentials Management Documentation](architecture/credentials-management.md)

### Data Privacy
- All user data scoped by Firebase UID (`owner_id`)
- Email content stored in Supabase (encrypted at rest by Supabase)
- LLM provider API keys encrypted with Fernet (application-level encryption)
- No data shared between users (RLS enforced)
- Data sent to LLM providers for analysis uses user's own API key (BYOK model)

## Performance Characteristics

### Email Operations
- **Initial archive sync**: ~2 min (one-time, 500 emails)
- **Incremental sync**: <1s (Gmail History API)
- **Intelligence cache build**: ~30s (30-day window)
- **Email search**: <100ms (FTS5 index)

### API Response Times
- **Chat message**: 2-5s (depends on tool usage)
- **Archive search**: 100-300ms
- **Gap analysis**: 1-3s

## Scalability Considerations

### Current Limits
- **Emails**: Tested with 500 messages, scales to millions with Supabase
- **Threads**: 30-day intelligence window (~250-300 threads typical)
- **Concurrent API**: Railway auto-scaling

### Scaling Strategy

**Phase 1: Current** (0-1,000 users)
- Single FastAPI instance on Railway
- Supabase Postgres (managed)
- Background workers (APScheduler in-process)

**Phase 2: Growth** (1,000-10,000 users)
- Add Railway replicas (horizontal scaling)
- Move background workers to separate processes
- Add Redis for caching and session management

**Phase 3: Scale** (10,000+ users)
- Railway auto-scaling (multiple replicas)
- Redis caching layer (Upstash)
- Separate worker pool for triggers
- Consider Elasticsearch for advanced search

**Bottlenecks to Monitor**:
- Database connections (Supabase limit: 60)
- Claude API rate limits (1,000 requests/min for Pro)
- Background worker queue depth
- Memory system HNSW index size

## Error Handling

### Gmail API Errors
- **History ID expired**: Automatic fallback to date-based sync
- **Rate limits**: Exponential backoff (handled by google-api-python-client)
- **Auth expiry**: Automatic token refresh

### Database Errors
- **Supabase connection**: Automatic retry with exponential backoff
- **RLS violations**: Check owner_id scoping

## Development Patterns

### Tool Development
1. Create class in `zylch/tools/`
2. Implement `execute()` method
3. Register in `factory.py:create_all_tools()`
4. Add to agent's available tools

### API Endpoint Development
1. Create Pydantic models in `api/routes/`
2. Implement business logic in `services/`
3. Register router in `api/main.py`
4. Test with `/docs` (Swagger UI)

### Testing Strategy
- **Unit tests**: Tool logic (pytest)
- **Integration tests**: API endpoints (pytest + TestClient)
- **Manual tests**: CLI commands, real Gmail account

## Memory System

### Core Principle: Entity-Centric

The memory system stores knowledge as entity blobs with sentence-level embeddings. Entity identity lives IN the blob content (not in namespace structure), found via hybrid search.

**Namespace = Ownership** (e.g., `user:{owner_id}`), not per-entity. This prevents fragmentation when the same entity appears in different contexts.

### Memory Reconsolidation

**How human memory works**: When you learn someone moved to a new city, you don't create a second "location" memory—you *update* the existing one.

**How ZylchMemory works**:
1. New information arrives (e.g., from email)
2. Hybrid search (FTS + semantic) finds existing blobs about the same entity
3. If found (score ≥ 0.65): LLM-merge new info with existing blob
4. If not found: Create new blob

**Why this matters**:
- No duplicate memories ("Mario lives in Rome" vs "Mario lives in Milan")
- Coherent knowledge graph (one source of truth per entity)
- Natural memory evolution (updates reflect reality changes)

### Memory Agent (Email Processing)

During `/sync`, the Memory Agent processes unprocessed emails:

1. **Extract facts** from each email using LLM
2. **Hybrid search** for existing blob about the entity (FTS + semantic)
3. **Reconsolidate** if match found (LLM-merge), else create new blob
4. **Mark email as processed** via `memory_processed_at` column

**Key Files**:
- `zylch/workers/memory.py` - MemoryWorker class
- `zylch/memory/blob_storage.py` - BlobStorage (store/update blobs)
- `zylch/memory/hybrid_search.py` - HybridSearchEngine (FTS + semantic)
- `zylch/memory/llm_merge.py` - LLMMergeService (reconsolidation)

### Task Agent (Task Processing)

The Task Agent processes emails and calendar events to detect actionable tasks with intelligent lifecycle management:

1. **Fetch unprocessed items** using `task_processed_at IS NULL`
2. **Group emails by thread** - only analyze latest per thread
3. **Hard symbolic check** - `_is_user_email()` blocks user's own email (never trust LLM)
4. **Fetch ALL existing tasks** for same contact via `get_tasks_by_contact()` (list)
5. **Fetch calendar context** - upcoming/recent meetings with contact via `get_calendar_events_by_attendee()`
6. **Apply trained prompt** with existing task context + calendar context
7. **LLM returns `task_action`** + `target_task_id`: create, update, close, or none
8. **Handle action**:
   - `close`: Mark target task completed (by ID)
   - `update`: Update target task with new info (by ID)
   - `create`: Create new task
   - `none`: Skip, no task needed
9. **Mark as processed** via `task_processed_at` column

**Calendar Context Awareness**:
- Upcoming meeting with contact → LLM may suppress "schedule call" type tasks
- Recent meeting with contact → LLM considers if follow-up is needed based on meeting type
- Uses `{{calendar_context}}` placeholder in trained prompt

**Performance Optimization**:
- Calendar context is pre-computed at batch level (not per-email) to avoid N+1 queries
- Uses PostgreSQL RPC function `get_events_by_attendee()` for server-side JSONB filtering
- GIN index on `attendees` column for fast containment queries

**Key Files**:
- `zylch/workers/task_creation.py` - TaskWorker class with `_is_user_email()` hard check, `analyze_item_sync()` single source of truth
- `zylch/agents/trainers/task_email.py` - EmailTaskAgentTrainer for prompt generation (includes calendar awareness)
- `zylch/storage/migrations/022_calendar_attendee_search.sql` - RPC function and GIN index

**Training**: `/agent task train email` runs as background job (5-30+ seconds), generates calendar-aware prompt, notifies on completion.

### Hybrid Search

Combines 3 scoring components:

1. **FTS (Full-Text Search)**: PostgreSQL `ts_rank` on `tsv` column (only #IDENTIFIERS section)
2. **Semantic**: pgvector cosine similarity on sentence embeddings (full blob content)
3. **Exact Pattern**: ILIKE match for detected email/phone/URL patterns on #IDENTIFIERS section

**Scoring logic**:
- If exact pattern detected: `0.8 * exact + 0.1 * FTS + 0.1 * semantic`
- Otherwise: `alpha * FTS + (1-alpha) * semantic`

**Alpha defaults**:
- Named entities ("John Smith"): α = 0.7 (FTS-heavy)
- Conceptual queries ("communication style"): α = 0.3 (semantic-heavy)
- Default: α = 0.5 (balanced)

**Pattern detection** (`zylch/memory/pattern_detection.py`): Extracts email, phone, URL from query using regex fullmatch. When detected, exact matching on #IDENTIFIERS takes priority.

**Key files**:
- `zylch/memory/hybrid_search.py` - HybridSearchEngine
- `zylch/memory/pattern_detection.py` - detect_pattern()
- `zylch/storage/migrations/009_hybrid_search_exact_match.sql` - SQL function

### Commands

| Command | Purpose |
|---------|---------|
| `/memory search <query>` | Hybrid search (FTS + semantic) |
| `/memory store <content>` | Store with auto-reconsolidation |
| `/memory stats` | Show blob/sentence counts |
| `/memory list [limit]` | List recent blobs |
| `/memory reset` | Delete ALL blobs (irreversible) |

### Fresh Start (Rebuild Everything)

To rebuild memory from scratch:

```bash
/memory reset         # Delete all blobs first
/sync reset           # Clear emails/calendar (warns about memory)
/sync days 30         # Re-sync and process into fresh blobs
```

**`/sync reset`** clears emails and calendar, then warns to run `/memory reset` if you want fresh memory too.

### Database Schema

**Table: `blobs`**
- `id`, `owner_id`, `namespace`, `content`, `embedding`, `events`, timestamps

**Table: `blob_sentences`**
- `id`, `blob_id`, `owner_id`, `sentence_text`, `embedding`

**Column: `emails.memory_processed_at`**
- NULL = not processed by memory agent, timestamp = when processed

**Column: `emails.task_processed_at`**
- NULL = not processed by task agent, timestamp = when processed

**Column: `calendar_events.task_processed_at`**
- NULL = not processed by task agent, timestamp = when processed

### 9. Task Orchestration (Task Mode)

**Architecture: Router + Specialized Agents**

To handle complex, multi-step tasks statefully, we use a router pattern that switches the user's context between a general-purpose agent and a dedicated task orchestrator.

**Core Components:**

1.  **Router (`ChatService`)**:
    -   Intercepts all user messages.
    -   Checks `SessionState` for an active `task_id`.
    -   **If active:** Routes message to `TaskOrchestratorAgent` (Stateful).
    -   **If inactive:** Routes message to `MainAgent` (Stateless/General Purpose).
    -   Handles `/tasks open <ID>` and `/tasks exit` commands to switch modes.

2.  **`TaskOrchestratorAgent` (Stateful Orchestrator)**:
    -   **Role:** Manages the lifecycle of a specific task.
    -   **State:** Persists in memory via `SessionState` (knows current task, last action result).
    -   **Prompt:** Uses a structured "Observation-Thought-Action" loop to reason about the task.
    -   **Tools:** Has only ONE tool: `call_agent(agent_name, instructions)`.
    -   **Behavior:** It delegates work to specialized agents but maintains control of the conversation.

3.  **Specialized Agents (`EmailerAgent`, `MrCallAgent`)**:
    -   **Role:** "Expert arms" that perform specific actions.
    -   **Interface:** `run(instructions)`.
    -   **Stateless:** They execute a request and return a result (e.g., a draft email, a config update).

**State Management (`SessionState`)**:
-   Currently in-memory (per `ChatService` instance).
-   Stores: `task_id` (active task UUID), `last_action_result` (for confirmation flows).
-   Enables the "Virtualenv" experience where the AI knows context across multiple turns without re-reading the whole history.

**Workflow**:
1.  User: `/tasks open 123` -> Router activates Task Mode.
2.  User: "Draft a reply" -> `TaskOrchestratorAgent` calls `EmailerAgent`.
3.  `EmailerAgent` returns draft -> `TaskOrchestratorAgent` shows draft + asks confirmation.
4.  User: "Send it" -> `TaskOrchestratorAgent` (knowing context) calls `EmailerAgent` to send.
5.  User: `/tasks exit` -> Router clears Task Mode.

## Personalized Prompts System (December 2025)

### Problem Solved

The default memory extraction prompt uses generic rules for classifying emails (cold outreach, important contacts, etc.). This fails because:
- Generic regex patterns miss nuanced cold outreach (e.g., fundraising asks to non-investors)
- No understanding of user's role, business context, or priorities
- VIP contacts aren't prioritized over random senders

### Solution: Learn from User's Email Patterns

The `/agent memory train email` command analyzes the user's recent email threads (20 threads, last email per thread) to understand their communication context:

1. **Recent threads** = Sample of communication patterns, contacts, topics (thread-based to avoid context overflow)
2. **User's sent emails** = Role, business context, signature patterns
3. **Frequent contacts** = People who appear multiple times

The LLM judges email importance based on **tone and content** (not reply history), generating a personalized extraction agent that understands:
- The user's role (founder vs investor vs engineer)
- Types of emails they receive
- How to assess importance from email content itself

### Architecture

**Key Files**:
- `zylch/agents/trainers/memory_email.py` - EmailMemoryAgentTrainer class that analyzes patterns
- `zylch/agents/trainers/task_email.py` - EmailTaskAgentTrainer for task detection prompts
- `zylch/workers/memory.py` - Uses personalized agent for extraction
- `zylch/workers/task_creation.py` - Uses personalized agent for task detection

**Data Flow**:
```
/sync → emails stored in DB
    ↓
/agent memory train email
    ↓
EmailMemoryAgentTrainer analyzes:
  - 20 recent threads (last email per thread)
  - Sent emails (user profile)
  - Frequent contacts
    ↓
LLM generates personalized agent
    ↓
Stored in agent_prompts table
    ↓
/agent memory process email uses personalized agent
```

### Commands

| Command | Purpose |
|---------|---------|
| `/agent memory train email` | Generate personalized memory extraction agent |
| `/agent memory run email` | Process emails + calendar into memory blobs |
| `/agent memory show email` | Display current memory agent |
| `/agent memory reset email` | Delete memory agent |
| `/agent task train email` | Generate personalized task detection agent (background job) |
| `/agent task process email` | Detect tasks from emails + calendar |
| `/agent task show email` | Display current task agent |
| `/agent task reset email` | Delete task agent |

**Note**: The `email` channel automatically includes calendar events. Output shows separate counts for transparency.

### Gate on Processing

When user runs `/agent memory process email` without a custom agent, they see a recommendation:
```
⚠️ No personalized extraction agent found

For better memory extraction, create a personalized agent first:
/agent memory train email
```

### Database

**Table: `agent_prompts`**
- `id`, `owner_id`, `agent_type`, `agent_prompt`, `metadata`, timestamps
- Unique constraint on `(owner_id, agent_type)`
- Metadata includes: emails_analyzed count, frequent_contacts_count

### Benefits

1. **Content-based importance** - Judges emails by tone/content, not reply history
2. **Role awareness** - System knows if you're a founder (not investor) and filters accordingly
3. **Zero maintenance** - Run once, prompt stored and used automatically

## Email Triage System (December 2025)

**For complete triage system documentation**, see [Email Triage Feature Documentation](/docs/features/email-triage.md)

### Summary

The Email Triage System solves a critical bug where support emails were incorrectly marked as "resolved" when an auto-reply was sent. Key features:

1. **RFC 3834 Auto-Reply Detection**: Header-based detection (saves Claude API costs)
2. **Importance Rules Engine**: User-configurable contact priority rules
3. **Training Data Collection**: Anonymized ML training samples for future small model fine-tuning
4. **Performance**: Auto-reply threads analyzed in <100ms (vs ~3-5s with Claude)

**Components**:
- `zylch/utils/auto_reply_detector.py` - RFC 3834 header detection (35 tests)
- `zylch/models/importance_rules.py` - Safe rule evaluation engine (32 tests)
- `zylch/ml/anonymizer.py` - PII anonymization for training data
- `zylch/api/routes/settings.py` - Importance rules CRUD API

**Database tables**: `email_triage`, `importance_rules`, `triage_training_samples`

## Email Read Tracking System (December 2025)

**For complete read tracking documentation**, see [Email Read Tracking Feature Documentation](/docs/features/email-read-tracking.md)

### Summary

The Email Read Tracking System enables Zylch to detect when recipients open emails, providing critical intelligence for follow-up timing and relationship management. Key features:

1. **Dual Tracking Approach**:
   - **PRIMARY**: SendGrid webhooks for batch/campaign emails (no custom pixel injection needed)
   - **SECONDARY**: Custom 1x1 tracking pixel for individual emails

2. **Intelligence Integration**: Read tracking data flows into the task system:
   - Status computation: Unread/read tracking per email
   - Priority context for follow-up decisions
   - LLM context: Enhanced action generation with read awareness
   - Display indicators: `📧❌ (unread 5d)` or `📧✓ (read 4d ago)`

3. **Privacy & Compliance**:
   - US privacy laws (CAN-SPAM, CCPA) compliant
   - Personal emails (Gmail/Outlook): No unsubscribe required
   - IP collection disabled by default
   - 90-day data retention with auto-cleanup

4. **Performance**: SendGrid webhook processing <100ms, pixel endpoint <50ms

**Components**:
- `zylch/api/routes/webhooks.py` - SendGrid webhook handler with ECDSA signature verification
- `zylch/api/routes/tracking.py` - Tracking pixel endpoint (1x1 transparent GIF)
- `zylch/storage/supabase_client.py` - Database operations
- `zylch/storage/migrations/003_email_read_tracking.sql` - Database schema

**Database tables**: `email_read_events`, `sendgrid_message_mapping`, `messages.read_events` (JSONB)

**API Endpoints**:
- `POST /api/webhooks/sendgrid` - Receive SendGrid open events
- `GET /api/track/pixel/{tracking_id}` - Serve tracking pixel

**Task Integration**: Read indicators can inform task urgency via LLM suggestions: "Follow up on proposal - unread for 5 days"

## Future Development TODOs

The following future development plans are documented in detail in `docs/features/`:

### 🔴 Critical Priority
- **[BILLING_SYSTEM_TODO.md](../docs/features/BILLING_SYSTEM_TODO.md)** - Stripe integration, subscription tiers (Free/Pro/Team), feature gating, revenue generation (Phase H)
- **[WHATSAPP_INTEGRATION_TODO.md](../docs/features/WHATSAPP_INTEGRATION_TODO.md)** - WhatsApp integration via StarChat API, multi-channel threading, 6.9B user market

### 🟡 Medium-High Priority
- **[MICROSOFT_CALENDAR_TODO.md](../docs/features/MICROSOFT_CALENDAR_TODO.md)** - Complete Outlook Calendar implementation, Teams meeting links, feature parity (Phase I.5)

### 🟡 Medium Priority
- **[DESKTOP_APP_TODO.md](../docs/features/DESKTOP_APP_TODO.md)** - Tauri desktop application (Rust + Vue 3), local SQLite, hybrid sync
- **[MOBILE_APP_TODO.md](../docs/features/MOBILE_APP_TODO.md)** - React Native cross-platform (iOS + Android), push notifications, biometric auth
- **[REAL_TIME_PUSH_TODO.md](../docs/features/REAL_TIME_PUSH_TODO.md)** - Gmail Pub/Sub push notifications, <5 second latency, WebSocket updates

### 🟢 Low Priority (Scaling)
- **[REDIS_SCALING_TODO.md](../docs/features/REDIS_SCALING_TODO.md)** - Upstash Redis caching, rate limiting, session management (Phase J)

Each TODO file contains:
- Business impact analysis and market sizing
- Current state and what's missing
- Detailed implementation phases with timelines
- Success metrics (technical, business, UX)
- Open questions and technical decisions

**Triggers for Implementation**:
- Billing: Required for revenue generation and monetization
- WhatsApp: Waiting for StarChat API endpoint availability
- Microsoft Calendar: When Outlook users exceed 40% of user base
- Desktop/Mobile: When user requests justify development effort
- Real-time Push: When real-time features become competitive requirement
- Redis Scaling: When API P95 >500ms OR database costs >$200/month

## Related Documentation

### Core Features
- **[Email Archive](features/email-archive.md)** - Email storage and AI-powered analysis
- **[Calendar Integration](features/calendar-integration.md)** - Google/Microsoft calendars
- **[Relationship Intelligence](features/relationship-intelligence.md)** - Task detection
- **[Entity Memory System](features/entity-memory-system.md)** - Entity-centric memory with hybrid search
- **[Triggers & Automation](features/triggers-automation.md)** - Event-driven automation
- **[Sharing System](features/sharing-system.md)** - Consent-based intelligence sharing
- **[MrCall Integration](features/mrcall-integration.md)** - Telephony and WhatsApp

### Architecture Deep-Dives
- **[Credentials Management](architecture/credentials-management.md)** - Unified token/credential storage
- **[Database Schema](architecture/db_schema.sql)** - Full SQL schema reference

### Future Development
- **[Billing System](features/BILLING_SYSTEM_TODO.md)** - Stripe subscriptions (Phase H)
- **[WhatsApp Integration](features/WHATSAPP_INTEGRATION_TODO.md)** - Multi-channel messaging
- **[Microsoft Calendar](features/MICROSOFT_CALENDAR_TODO.md)** - Full Outlook support (Phase I.5)
- **[Desktop App](features/DESKTOP_APP_TODO.md)** - Tauri local-first app
- **[Mobile App](features/MOBILE_APP_TODO.md)** - React Native iOS + Android
- **[Real-Time Push](features/REAL_TIME_PUSH_TODO.md)** - Gmail Pub/Sub notifications
- **[Redis Scaling](features/REDIS_SCALING_TODO.md)** - Caching layer (Phase J)

## Known Limitations

1. **HNSW index updates**: HNSW doesn't support in-place vector updates. After reconsolidation, the old vector position remains until index rebuild. This is acceptable for now.
2. **Contact tools**: Not available in API (CLI-only, require StarChat)
3. **Stateless API**: Client manages conversation history
4. **Single account**: Gmail OAuth for one account per deployment
5. **Training data requires scale**: Need ~1000+ samples before fine-tuning makes sense
