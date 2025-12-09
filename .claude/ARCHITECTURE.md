# Zylch Architecture

## Critical: No Local Filesystem

**The backend uses Supabase for ALL data storage. NO local filesystem.**

| Data | Storage | Table |
|------|---------|-------|
| OAuth tokens (Google, Microsoft, Anthropic) | Supabase | `oauth_tokens` (encrypted) |
| Email analysis | Supabase | `thread_analysis` |
| Calendar events | Supabase | `calendar_events` |
| Sync state | Supabase | `sync_state` |
| Triggers | Supabase | `triggers`, `trigger_events` |
| Memory/Avatars | Supabase | pg_vector tables |

**NEVER use local filesystem for:**
- Token storage (no pickle files)
- Credentials (no `credentials/` directory)
- Cache (no `cache/` directory)

The `credentials/` and `cache/` directories are **LEGACY and UNUSED**.

---

## System Overview

Zylch is an AI-powered email assistant that provides relationship intelligence, task management, and automated email workflows through multiple interfaces (CLI, HTTP API).

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

**Key Pattern**: Tools are stateless classes with `execute()` method

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

**Purpose**: Notify users of background worker failures or system events in the chat.

**Problem solved**: Background workers (e.g., avatar computation) can fail silently. Users need to know when something requires their attention (e.g., missing API key).

**How it works**:
```
Background Worker (e.g., AvatarComputeWorker)
       │
       │ (failure detected, e.g., missing Anthropic key)
       ▼
storage.create_notification(owner_id, message, type='warning')
       │
       │ (notification stored in user_notifications table)
       ▼
User sends any message in chat
       │
       ▼
ChatService.process_message()
       │
       ├─ Check for unread notifications
       ├─ Format as markdown banner
       ├─ Mark as read
       └─ Prepend to response
       │
       ▼
User sees: "⚠️ Avatar computation skipped: No Anthropic API key..."
           ---
           [normal response]
```

**Behavior**:
- **Show once, mark as read**: Notification appears on first message after creation, then disappears
- **Non-blocking**: Notifications are prepended to response, don't interrupt normal flow
- **Deduplication**: Workers check for existing notifications before creating duplicates

**Table**: `user_notifications`
| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Primary key |
| `owner_id` | TEXT | Firebase UID |
| `message` | TEXT | Notification text |
| `notification_type` | TEXT | `info`, `warning`, `error` |
| `read` | BOOLEAN | Whether user has seen it |
| `created_at` | TIMESTAMPTZ | When created |

**Files**:
- `zylch/storage/supabase_client.py`: `create_notification()`, `get_unread_notifications()`, `mark_notifications_read()`
- `zylch/services/chat_service.py`: Checks and injects notifications in `process_message()`
- `zylch/workers/avatar_compute_worker.py`: Creates notification on missing API key

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

### Commands API (`/api/commands`)

**Purpose**: Expose command metadata so any frontend (CLI, web, mobile) can discover available commands and their help text. The backend is the single source of truth.

**Endpoints**:
- `GET /api/commands` - List all commands with summaries
- `GET /api/commands/help` - Get help for all commands
- `GET /api/commands/help?cmd=gaps` - Get detailed help for specific command

**Source of Truth**: `COMMAND_HELP` dict in `zylch/services/command_handlers.py`

**Help via Chat**: Sending `/gaps --help` (or any command with `--help`) returns help text without executing the command. This is handled by the dispatcher in `chat_service.py` before routing to handlers.

### 6. CLI (`zylch/cli/main.py`)
Interactive command-line interface:
- `/sync` - Morning workflow (archive + intelligence + calendar + gaps)
- `/gaps` - Show relationship gaps
- `/archive` - Archive management
- `/memory` - Memory system
- Natural conversation with agent

### Task Display: `get_tasks` Tool

**Problem**: `/gaps` is fast (3.5s) but only shows counts. Asking "show me tasks" in natural language triggers full agent initialization + Claude API formatting (27s).

**Solution**: `get_tasks` tool that returns pre-formatted task list from avatars.

**How it works**:
```
User: "show me tasks"
       │
       ▼
Agent recognizes task query → calls get_tasks tool
       │
       ▼
Tool queries Supabase avatars (pre-computed) → formats markdown
       │
       ▼
Returns formatted list in ~3-5s (1 LLM call to decide tool, instant data)
```

**Tool location**: `zylch/tools/factory.py` → `_GetTasksTool`

**Performance comparison**:
| Query | Before | After |
|-------|--------|-------|
| `/gaps` | 3.5s (counts only) | 3.5s (full list) |
| "show me tasks" | 27s (LLM formats) | ~5s (tool returns pre-formatted) |

**Why this matters**: Avatars are pre-computed by background worker after `/sync`. The data exists — we just need to display it without asking Claude to format it every time.

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

**Security**:
- All tables use Row Level Security (RLS) scoped by `owner_id`
- Sensitive tokens encrypted with Fernet before storage
- Supabase provides encryption at rest

### Future: Local-First Options

When desktop/mobile apps are developed, we may explore local-first storage:

| Approach | Technology | Use Case | Pros | Cons |
|----------|------------|----------|------|------|
| **SQLite (Local)** | SQLite + sqlcipher | CLI, Desktop apps | Fast, offline, private | No cross-device sync |
| **IndexedDB (Browser)** | Web Crypto AES-GCM | Web app (PWA) | Browser-native, encrypted | Browser storage limits |
| **Tauri + SQLite** | Tauri (Rust) + SQLite | Desktop app | Lightweight, secure | Desktop only |
| **Capacitor + SQLite** | Capacitor plugin | Mobile app | Cross-platform | Wrapper overhead |
| **Hybrid** | Local + Supabase sync | All platforms | Best of both | Complex sync logic |

**Potential local-first architecture** (not yet implemented):
```
┌─────────────────────────────────────────────────────┐
│                    Local Device                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │    CLI      │  │  Desktop    │  │   Mobile    │  │
│  │  (Python)   │  │  (Tauri)    │  │ (Capacitor) │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
│         └────────────────┼────────────────┘         │
│                          ▼                          │
│                 ┌─────────────────┐                 │
│                 │  Local SQLite   │ ← emails, sync  │
│                 └────────┬────────┘                 │
└──────────────────────────┼──────────────────────────┘
                           │ (AI summaries, cross-device)
                           ▼
                    ┌─────────────┐
                    │  Supabase   │
                    └─────────────┘
```

**Decision pending**: Will evaluate when building desktop/mobile apps.

### Token Storage (`oauth_tokens` table)

| Column | Purpose | Encrypted? |
|--------|---------|------------|
| `owner_id` | Firebase UID (partition key) | — |
| `provider` | `google.com`, `microsoft.com`, `anthropic`, `mrcall` | — |
| `email` | User's email (or MrCall business_id) | ❌ |
| `google_token_data` | Base64 pickle of Google Credentials | ✅ Fernet |
| `graph_access_token` | Microsoft Graph access token | ✅ Fernet |
| `graph_refresh_token` | Microsoft Graph refresh token | ✅ Fernet |
| `graph_expires_at` | Token expiration (ISO timestamp) | ❌ |
| `anthropic_api_key` | Anthropic API key | ✅ Fernet |
| `scopes` | OAuth scopes | ❌ |

**Token Methods** (`zylch/storage/supabase_client.py`):
```python
# Store (encrypts automatically)
store_oauth_token(owner_id, provider, email, google_token_data=..., graph_access_token=...)
save_anthropic_key(owner_id, api_key)

# Retrieve (decrypts automatically)
get_google_token(owner_id)      # → base64 pickle string
get_graph_token(owner_id)       # → {access_token, refresh_token, expires_at}
get_anthropic_key(owner_id)     # → "sk-ant-..."

# Delete
delete_oauth_token(owner_id, provider)
delete_anthropic_key(owner_id)
```

### Configuration
- **Environment**: Railway env vars (backend), Vercel env vars (frontend)
- **Defaults**: `zylch/config.py` (Pydantic settings)

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

### Anthropic Claude
- **Models**:
  - Haiku: Fast classification (~$0.92/1K emails)
  - Sonnet: Default analysis (~$7/1K emails)
  - Opus: Executive communications (high cost)
- **Features**: Tool use, prompt caching

### Optional Integrations
- **Pipedrive**: CRM sync
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
- **Firebase Auth**: JWT tokens validated on all API endpoints
- **OAuth Tokens**: Stored encrypted in Supabase (Google, Microsoft)
- **Per-user isolation**: All data scoped by `owner_id` (Firebase UID)

### Token Auto-Refresh (Frontend)

Firebase ID tokens expire after 1 hour. The frontend implements automatic token refresh:

**Flow**:
1. On OAuth callback, backend redirects with `?token=xxx&refresh_token=xxx`
2. Frontend stores both in localStorage (`zylch_token`, `zylch_refresh_token`)
3. `scheduleRefresh()` parses JWT expiry and sets timer for 5 minutes before expiration
4. When timer fires, `doRefreshToken()` calls Firebase's token refresh API
5. New tokens stored, new timer scheduled

**Implementation** (`frontend/src/stores/auth.ts`):
```typescript
// Firebase token refresh API
POST https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}
Body: { grant_type: 'refresh_token', refresh_token: '...' }
Response: { id_token: '...', refresh_token: '...' }
```

**Key files**:
- `frontend/src/stores/auth.ts` - `scheduleRefresh()`, `doRefreshToken()`, `getTokenExpiry()`
- `frontend/src/views/AuthCallbackView.vue` - Extracts `refresh_token` from URL
- `zylch/api/routes/auth.py` - Includes `refresh_token` in OAuth callback redirect

### Token Auto-Refresh (CLI)

The CLI also implements automatic token refresh:

**Flow**:
1. On login, the local auth server receives `refreshToken` from Firebase SDK
2. Stored in `~/.zylch/credentials/{provider}/credentials.json`
3. Before each prompt in the main loop, `needs_refresh()` checks if token expires within 5 minutes
4. If expiring, `refresh_firebase_token()` calls Firebase's token refresh API
5. New tokens saved to credentials file

**Implementation** (`zylch/cli/auth.py`):
```python
def refresh_firebase_token(self) -> bool:
    # Call Firebase API with stored refresh_token
    response = requests.post(
        f"https://securetoken.googleapis.com/v1/token?key={FIREBASE_API_KEY}",
        json={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )
    # Update credentials with new id_token
```

**Key files**:
- `zylch/cli/auth.py` - `refresh_firebase_token()`, `needs_refresh()`, `ensure_valid_token()`
- `zylch/cli/auth_server.py` - Captures `refreshToken` from Firebase SDK during login
- `zylch/cli/main.py` - Auto-refresh check in main loop

### Sensitive Data Encryption

**Anthropic API Keys (BYOK)**:
- **Storage**: Supabase `oauth_tokens` table with `provider='anthropic'`
- **Encryption**: Fernet (AES-128-CBC + HMAC) via `zylch/utils/encryption.py`
- **Key**: `ENCRYPTION_KEY` environment variable (set in Railway)
- **Flow**:
  ```
  User enters key → encrypt(api_key) → Supabase (encrypted blob)
  API call needed → get_anthropic_key() → decrypt() → use with Claude
  ```

**OAuth Tokens (Google/Microsoft)**:
- **Storage**: Supabase `oauth_tokens` table
- **Encryption**: Same Fernet encryption for `google_token_data`, `graph_access_token`, `graph_refresh_token`
- **Scopes stored**: Plaintext (not sensitive)

**Encryption Implementation** (`zylch/utils/encryption.py`):
```python
from zylch.utils.encryption import encrypt, decrypt, is_encryption_enabled

# Check if encryption is available
if is_encryption_enabled():
    encrypted = encrypt("sk-ant-xxx")  # Returns gAAA... (Fernet token)
    decrypted = decrypt(encrypted)      # Returns original key

# Graceful fallback: returns original if ENCRYPTION_KEY not set
```

**Key Management**:
- Generate key once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Store in Railway env vars as `ENCRYPTION_KEY`
- **Never commit** encryption keys to git

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

## Memory System Philosophy

### Core Principle: Zylch is Person-Centric

**A person is NOT an email address.** A person can have:
- Multiple email addresses (work, personal, aliases)
- Multiple phone numbers (mobile, office, WhatsApp)
- Multiple names (formal name, nickname, company role)

The memory system must reflect this reality. When you ask "who is Luigi?", Zylch should find the person regardless of which identifier you use.

### How Human Memory Works (and Zylch Should Too)

Human memory has three phases:
1. **Encoding**: New information arrives
2. **Consolidation**: Information integrates with existing memories
3. **Reconsolidation**: When you recall a memory AND receive new info, you UPDATE the existing memory

Humans don't create parallel conflicting memories. If someone gives you a new phone number, you update your mental model of that person - you don't keep two "phone number memories" in your head.

**Zylch must work the same way.**

### The Problem We Solved

Before: `store_memory()` always did INSERT. If you stored:
1. "Tizio's phone is 348..."
2. Later: "Tizio's phone is 339..." (new number)

You'd have TWO memories that could conflict during retrieval. The system might return the old number!

### The Solution: Memory Reconsolidation

When storing a new memory:
1. Generate embedding for the new content
2. Search existing memories for semantic similarity (cosine > 0.85 threshold)
3. If similar memory exists → **UPDATE** it (reconsolidate)
4. If no similar memory → **INSERT** new memory

This mirrors human memory reconsolidation.

### Two-Layer Memory Architecture

**Layer 1: Identifier Map Cache**
- **Purpose**: O(1) lookup from any identifier to person
- **Technology**: Supabase with indexed lookups
- **Key insight**: Maps email/phone/name → memory_id
- **Benefit**: Avoids expensive remote API calls (Gmail 10+ seconds) when contact is already known

**Layer 2: Semantic Memory (`zylch_memory/`)**
- **Purpose**: Vector-based semantic storage with reconsolidation
- **Technology**: Supabase pg_vector + sentence-transformers
- **Key insight**: Similar memories are the SAME memory (updated, not duplicated)

### Memory Lookup Flow

When user asks "info su Luigi":

```
1. search_local_memory("Luigi")
   ↓
2. IdentifierMapCache.lookup("Luigi")  [O(1), <1ms]
   ↓
   If found AND fresh (TTL 7 days) → RETURN CACHED DATA
   If found BUT stale → Return cached + suggest refresh
   If not found → Proceed to remote searches
   ↓
3. Remote searches (ONLY if not in cache):
   - get_contact() from StarChat
   - search_emails() from local archive
   - search_gmail() from Gmail API (10+ seconds!)
   - search_calendar_events()
```

### Configuration

```python
# zylch_memory/config.py
similarity_threshold: float = 0.85  # Conservative: only merge truly similar memories
confidence_boost_on_update: float = 0.1  # Reinforce memory on reconsolidation
```

### Implementation Details

**Files modified for reconsolidation:**
- `zylch_memory/zylch_memory/config.py` - Added threshold configs
- `zylch_memory/zylch_memory/storage.py` - Added `update_memory()`, `get_embedding_by_id()`
- `zylch_memory/zylch_memory/core.py` - Added `_find_similar_memories()`, modified `store_memory()`

**Files for person-centric lookup:**
- `zylch/storage/supabase_client.py` - All data access methods
- `zylch/tools/factory.py` - `_SearchLocalMemoryTool`, modified `_SaveContactTool`
- `zylch/agent/prompts.py` - "LOCAL MEMORY FIRST" instructions

### Example: Reconsolidation in Action

```python
# First store
id1 = mem.store_memory(
    namespace="contacts",
    category="person",
    context="Contact info for Luigi Scrosati",
    pattern="phone: 348-1234567"
)
# → Creates memory ID 1, confidence 0.5

# Second store (similar content)
id2 = mem.store_memory(
    namespace="contacts",
    category="person",
    context="Contact info for Luigi Scrosati",
    pattern="telephone: 339-9876543 (updated)"
)
# → Similarity 0.97 > 0.85 threshold
# → RECONSOLIDATES memory ID 1
# → Returns ID 1, confidence now 0.6, pattern updated
# → Only ONE memory exists!
```

### When Reconsolidation Does NOT Happen

If texts are semantically different (similarity < 0.85), new memory is created:

```python
# "Tizio phone 348" vs "Tizio tel 339"
# Similarity: 0.72 (different numbers = different semantics)
# → Creates NEW memory (correct behavior!)
```

### The force_new Parameter

For cases where you WANT to create a distinct memory even if similar exists:

```python
mem.store_memory(..., force_new=True)  # Bypasses similarity check
```

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
