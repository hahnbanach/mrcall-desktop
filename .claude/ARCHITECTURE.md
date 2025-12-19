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
| OAuth tokens (Google, Microsoft, Anthropic, MrCall) | Supabase | `oauth_tokens` (encrypted) |
| Email analysis                                      | Supabase | `thread_analysis` |
| Calendar events                                     | Supabase | `calendar_events` |
| Sync state                                          | Supabase | `sync_state` |
| Triggers                                            | Supabase | `triggers`, `trigger_events` |
| Memory/Avatars                                      | Supabase | pg_vector tables |

**NEVER use local filesystem for:**
- Token storage (no pickle files)
- Credentials
- Cache

---

## System Overview

Zylch is an AI-powered email assistant that provides relationship intelligence, task management, and automated communication workflows (email, whatsapp, phone, slack etc) through multiple interfaces (CLI, HTTP API).

## Local Development

**Local development uses the SAME architecture as production:**
- Firebase Auth for user authentication
- Supabase for all data storage (emails, calendar, tokens, avatars)
- Same OAuth flows as production (server-side, not InstalledAppFlow)
- No separate local database or file-based token storage

Run locally with `uvicorn zylch.api.main:app --reload --port 8000` - connects to Supabase directly.

## Core Components

### 1. Agent System (`zylch/agent/`)
- **Purpose**: Orchestrates AI conversations with tool access
- **Key Files**:
  - `core.py`: Main agent logic, tool orchestration
  - `models.py`: Agent data models
  - `prompts.py`: System prompts and templates

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

**Key Pattern**: Tools are identical for all users. Credentials are loaded per-user at execution time from Supabase. If a user hasn't connected a provider, the tool returns a helpful error (e.g., "Vonage not connected. Please use /connect vonage").

### 3. Two-Tier Email System (Cloud-Based)

**Current Implementation: Supabase-Only**

All email data is stored in Supabase, scoped by `owner_id` (Firebase UID).

**Tier 1: Email Archive (Supabase)**
- **Purpose**: Permanent storage of email metadata and content
- **Technology**: Supabase Postgres
- **Tables**: `email_archive`, `email_messages`
- **Sync**: Gmail/Outlook History API (incremental, <1s)
- **Features**: Complete history, cross-device access

**Tier 2: Intelligence Cache (Supabase `thread_analysis`)**
- **Purpose**: AI-generated analysis and summaries
- **Technology**: Supabase Postgres
- **Content**: Analysis text, needs_action, priority, contact info
- **Window**: 30-day rolling analysis

**Data Flow**:
```
Gmail/Outlook API
       ↓
Supabase (email_archive) ← Email metadata/content stored here
       ↓
Claude AI (on-demand analysis)
       ↓
Supabase (thread_analysis) ← AI summaries stored here
```

**Privacy Note**: Email content is stored encrypted at rest by Supabase. All data is scoped by `owner_id` with Row Level Security (RLS).

### 4. Service Layer (`zylch/services/`)

**Purpose**: Business logic shared between CLI and API (no duplication)

**Key Services**:
- **SyncService**: Email/calendar synchronization
  - `sync_emails()`, `sync_calendar()`, `run_full_sync()`
- **GapService**: Relationship gap analysis
  - `analyze_gaps()`, `get_gaps_summary()`, `get_email_tasks()`
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

**Key files**: `supabase_client.py` (`create_notification()`), `chat_service.py` (injection), `avatar_compute_worker.py` (creates on missing API key)

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
- `/api/webhooks/sendgrid` - Email read tracking webhooks
- `/api/track/pixel/{tracking_id}` - Tracking pixel endpoint

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

**Phase 1 Commands** (replacing high-frequency tools):
| Command | Replaces Tool | Semantic Triggers |
|---------|---------------|-------------------|
| `/stats` | `_EmailStatsTool` | "email stats", "how many emails" |
| `/email list --draft` | `_ListDraftsTool` | "my drafts", "show drafts" |
| `/calendar` | `ListCalendarEventsTool` | "my calendar", "meetings today" |
| `/tasks` | `_GetTasksTool` | "my tasks", "todo list" |
| `/jobs` | `ListScheduledJobsTool` | "scheduled jobs", "my reminders" |

**Performance**: <100ms matching (embeddings cached after first load)

### 7. CLI (`zylch/cli/main.py`)
Interactive command-line interface:
- `/sync` - Sync emails, calendar, pipedrive (data only, no processing)
- `/email list|create|send|delete|search` - Email and draft management
- `/train build memory-email` - Generate personalized extraction prompt from email patterns
- `/memory process` - Extract facts from synced data into blobs (uses personalized prompt)
- `/memory search` - Search entity memories
- `/gaps` - Show relationship gaps
- Natural conversation with agent

### 8. Memory System (Entity-Centric Blobs)

**Data Flow**:
```
Gmail/Calendar/Pipedrive → /sync → Local Tables (emails, calendar_events)
                                          ↓
                              /memory process (MemoryWorker)
                                          ↓
                           Extract facts via Haiku LLM
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
- `/memory process` - Process all unprocessed data into blobs
- `/memory process email` - Process only emails
- `/memory process calendar` - Process only calendar events
- `/memory search <query>` - Hybrid FTS + semantic search
- `/memory --reset` - Delete blobs AND reset processing timestamps

**Reconsolidation**: When storing new facts, system searches for existing blob about same entity (hybrid score ≥ 0.65). If found, LLM merges old + new content. This prevents duplicate blobs about same person/topic.

### Task Display: `get_tasks` Tool

`_GetTasksTool` in `factory.py` returns pre-formatted task list from pre-computed avatars (~5s vs 27s for LLM formatting). Avatars are computed by background worker after `/sync`.

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

### Decision 2: Person-Centric Task Detection

**Problem**: Thread-based gaps miss follow-ups across multiple threads

**Solution**: Aggregate threads by contact email, detect tasks at person level

**Implementation** (`relationship_analyzer.py:find_email_tasks()`):
```python
# Group threads by contact
person_threads = {}
for thread in threads:
    contact_email = extract_contact(thread)
    person_threads[contact_email].append(thread)

# Detect tasks per person
for contact_email, threads in person_threads.items():
    last_thread = max(threads, key=lambda t: t['last_email']['date'])
    needs_action = detect_task(last_thread, person_context=threads)
```

### Decision 3: Manual Closure Persistence

**Problem**: User-closed threads reopened after sync

**Solution**: `manually_closed` flag in thread data
- Set by `mark_threads_closed_by_subject()`
- Preserved during sync (NEVER re-analyze manually closed threads)
- Respected by gap analysis

### Decision 4: Auto-Sync After Email Send

**Problem**: Gap analysis outdated after sending emails

**Solution**: Trigger incremental sync after `send_gmail_draft`
- Adds 1-3s latency to email send (acceptable)
- Keeps cache current automatically
- Implementation in `factory.py:_SendDraftTool`

### Decision 5: Chat API Wraps CLI

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
| `email_archive` | Email metadata and content |
| `thread_analysis` | AI-generated summaries and analysis |
| `calendar_events` | Calendar events |
| `sync_state` | Gmail/Outlook history IDs, last sync timestamps |
| `relationship_gaps` | Detected relationship gaps |
| `oauth_tokens` | All tokens (Google, Microsoft, Anthropic, MrCall) - encrypted |
| `triggers` | Triggered instructions |
| `trigger_events` | Event queue for trigger processing |
| `sharing_auth` | Sharing authorizations |
| `memories` | Avatar/memory system (pg_vector) |
| `user_notifications` | System notifications for users |
| `email_triage` | AI triage verdicts per thread |
| `importance_rules` | User-configurable contact importance rules |
| `triage_training_samples` | Anonymized training data + user corrections |
| `email_read_events` | Email read tracking events (SendGrid + custom pixel) |
| `sendgrid_message_mapping` | SendGrid message ID to Zylch message ID mapping |
| `user_prompts` | Personalized prompts generated from user email patterns |

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

**For complete details**, see [Credentials Management Documentation](/docs/architecture/credentials-management.md)

### Configuration
- **Environment**: Railway env vars (backend), Vercel env vars (frontend)
- **Defaults**: `zylch/config.py` (Pydantic settings)
- **System .env only contains**: Supabase config, Firebase config, Google OAuth client, encryption key
- **NOT in .env**: User credentials (Anthropic, Pipedrive, Vonage) - these are BYOK via `/connect`

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

### Anthropic Claude (BYOK)
- **Credential Storage**: User provides their own API key via `/connect anthropic`
- **No system .env fallback**: `ANTHROPIC_API_KEY` removed from `.env.example`
- **Models**:
  - Haiku: Fast classification (~$0.92/1K emails)
  - Sonnet: Default analysis (~$7/1K emails)
  - Opus: Executive communications (high cost)
- **Features**: Tool use, prompt caching

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
3. AI analysis performed on-demand, summaries stored in `thread_analysis`
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

**For complete authentication details**, see [Credentials Management Documentation](/docs/architecture/credentials-management.md)

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
  - Supports both Basic Auth (legacy) and OAuth bearer tokens (new)
  - Automatic token refresh on 401 responses
  - Fallback to Basic Auth if OAuth not configured

**Configuration** (`zylch/config.py`):
- `MRCALL_CLIENT_ID`: OAuth client ID (partner_e2e68f877b0722f7)
- `MRCALL_CLIENT_SECRET`: OAuth client secret (encrypted)
- `MRCALL_REALM`: MrCall realm (default: mrcall0)
- `MRCALL_BASE_URL`: StarChat API base URL (test: https://test-env-0.scw.hbsrv.net/)

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

### Sensitive Data Encryption

**All User Credentials (BYOK)**:
- **Storage**: Supabase `oauth_tokens` table in unified `credentials` JSONB column
- **Encryption**: Fernet (AES-128-CBC + HMAC) via `zylch/utils/encryption.py`
- **Key**: `ENCRYPTION_KEY` environment variable (set in Railway)
- **No fallback**: If user hasn't connected a provider, tools return helpful error (not system default)
- **Applies to**: Anthropic API key, Vonage credentials, Pipedrive token, OAuth tokens

**For complete details on the unified credentials system**, see [Credentials Management Documentation](/docs/architecture/credentials-management.md)

### Data Privacy
- All user data scoped by Firebase UID (`owner_id`)
- Email content stored in Supabase (encrypted at rest by Supabase)
- Anthropic API keys encrypted with Fernet (application-level encryption)
- No data shared between users (RLS enforced)
- Data sent to Claude for analysis uses user's own API key (BYOK model)

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

### Future Scaling
- **API**: Add Railway replicas
- **Cache**: Redis for session management
- **Search**: Consider Elasticsearch for advanced queries

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

1. **Extract facts** from each email using Haiku (cheap, fast)
2. **Hybrid search** for existing blob about the entity (FTS + semantic)
3. **Reconsolidate** if match found (LLM-merge), else create new blob
4. **Mark email as processed** via `memory_processed_at` column

**Key Files**:
- `zylch/workers/memory_worker.py` - MemoryWorker class
- `zylch_memory/blob_storage.py` - BlobStorage (store/update blobs)
- `zylch_memory/hybrid_search.py` - HybridSearchEngine (FTS + semantic)
- `zylch_memory/llm_merge.py` - LLMMergeService (reconsolidation)

### Hybrid Search

Combines PostgreSQL FTS (lexical) with pgvector (semantic) at sentence granularity:

```
hybrid_score = alpha * FTS_score + (1-alpha) * semantic_score
```

- **Named entities** ("John Smith"): α = 0.7 (FTS-heavy)
- **Conceptual queries** ("communication style"): α = 0.3 (semantic-heavy)
- **Default**: α = 0.5 (balanced)

### Commands

| Command | Purpose |
|---------|---------|
| `/memory search <query>` | Hybrid search (FTS + semantic) |
| `/memory store <content>` | Store with auto-reconsolidation |
| `/memory stats` | Show blob/sentence counts |
| `/memory list [limit]` | List recent blobs |
| `/memory --reset` | Delete ALL blobs (irreversible) |

### Fresh Start (Rebuild Everything)

To rebuild memory from scratch:

```bash
/memory --reset       # Delete all blobs first
/sync --reset         # Clear emails/calendar (warns about memory)
/sync --days 30       # Re-sync and process into fresh blobs
```

**`/sync --reset`** clears emails and calendar, then warns to run `/memory --reset` if you want fresh memory too.

### Database Schema

**Table: `blobs`**
- `id`, `owner_id`, `namespace`, `content`, `embedding`, `events`, timestamps

**Table: `blob_sentences`**
- `id`, `blob_id`, `owner_id`, `sentence_text`, `embedding`

**Column: `emails.memory_processed_at`**
- NULL = not processed, timestamp = when processed

## Personalized Prompts System (December 2025)

### Problem Solved

The default memory extraction prompt uses generic rules for classifying emails (cold outreach, important contacts, etc.). This fails because:
- Generic regex patterns miss nuanced cold outreach (e.g., fundraising asks to non-investors)
- No understanding of user's role, business context, or priorities
- VIP contacts aren't prioritized over random senders

### Solution: Learn from User's Email Patterns

The `/train build memory-email` command analyzes the user's recent emails (up to 100) to understand their communication context:

1. **Recent emails** = Sample of communication patterns, contacts, topics
2. **User's sent emails** = Role, business context, signature patterns
3. **Frequent contacts** = People who appear multiple times

The LLM judges email importance based on **tone and content** (not reply history), generating a personalized extraction prompt that understands:
- The user's role (founder vs investor vs engineer)
- Types of emails they receive
- How to assess importance from email content itself

### Architecture

**Key Files**:
- `zylch/services/prompt_builder.py` - PromptBuilder class that analyzes patterns
- `zylch/workers/memory_worker.py` - Uses personalized prompt for extraction (includes CC field)
- `zylch/storage/migrations/006_user_prompts.sql` - Database table

**Data Flow**:
```
/sync → emails stored in DB
    ↓
/train build memory-email
    ↓
PromptBuilder analyzes:
  - 100 recent emails (sample)
  - Sent emails (user profile)
  - Frequent contacts
    ↓
Claude Sonnet generates personalized prompt
    ↓
Stored in user_prompts table
    ↓
/memory process email uses personalized prompt
```

### Commands

| Command | Purpose |
|---------|---------|
| `/train build memory-email` | Analyze email patterns and generate personalized prompt |
| `/train show memory-email` | Display current personalized prompt |
| `/train reset memory-email` | Delete custom prompt, revert to default |

### Gate on Memory Processing

When user runs `/memory process email` without a custom prompt, they see a recommendation:
```
⚠️ No personalized extraction prompt found

For better memory extraction, create a personalized prompt first:
/train build memory-email
```

### Database

**Table: `user_prompts`**
- `id`, `owner_id`, `prompt_type`, `prompt_content`, `metadata`, timestamps
- Unique constraint on `(owner_id, prompt_type)`
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

2. **Intelligence Integration**: Read tracking data flows into the avatar/briefing system:
   - Status computation: New statuses `waiting_unread`, `waiting_acknowledged`
   - Priority boosting: +2 for unread 7+ days, +1 for unread 3+ days
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
- `zylch/services/avatar_aggregator.py` - Read tracking data integration (lines 230-351)
- `zylch/workers/crm_worker.py` - Status/priority/action generation with read awareness
- `zylch/services/task_formatter.py` - Display indicators in briefing
- `zylch/storage/supabase_client.py` - Database operations (lines 2311-2583)
- `zylch/storage/migrations/003_email_read_tracking.sql` - Database schema (~400 lines)

**Database tables**: `email_read_events`, `sendgrid_message_mapping`, `messages.read_events` (JSONB)

**API Endpoints**:
- `POST /api/webhooks/sendgrid` - Receive SendGrid open events
- `GET /api/track/pixel/{tracking_id}` - Serve tracking pixel

**Briefing Integration**: Read indicators appear in `/briefing` command output, showing:
- Which emails have been read with timestamps
- Which emails remain unread with days since sent
- Enhanced LLM suggestions: "Follow up on proposal - unread for 5 days"

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

## Known Limitations

1. **HNSW index updates**: HNSW doesn't support in-place vector updates. After reconsolidation, the old vector position remains until index rebuild. This is acceptable for now.
2. **Contact tools**: Not available in API (CLI-only, require StarChat)
3. **Stateless API**: Client manages conversation history
4. **Single account**: Gmail OAuth for one account per deployment
5. **Training data requires scale**: Need ~1000+ samples before fine-tuning makes sense
