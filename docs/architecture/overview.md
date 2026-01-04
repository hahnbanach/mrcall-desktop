# Architecture Overview

## Table of Contents

- [System Overview](#system-overview)
- [Core Architecture](#core-architecture)
- [Data Storage Strategy](#data-storage-strategy)
- [Memory System Design](#memory-system-design)
- [Security & Authentication](#security--authentication)
- [Performance & Scaling](#performance--scaling)
- [Key Architectural Decisions](#key-architectural-decisions)
- [Future Architecture](#future-architecture)

---

## System Overview

Zylch is an AI-powered relationship intelligence platform that provides:
- **Email & Calendar Intelligence**: Analyze communications for tasks and gaps
- **Person-Centric Memory**: Remember people across all their identifiers
- **Event-Driven Automation**: Trigger actions based on real-world events
- **Intelligence Sharing**: Share relationship context with team members

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

**Key Components**:
- **Client Interfaces**: CLI, Web, Mobile, API clients
- **Backend**: FastAPI server with service layer and tool system
- **Storage**: Supabase Postgres with Row Level Security (RLS)
- **External APIs**: Gmail, Calendar, StarChat, Claude

---

## Core Architecture

### Layered Design

Zylch follows a **three-tier architecture**:

#### 1. Presentation Layer (Clients)

**CLI** (`zylch/cli/`)
- Interactive command-line interface
- Slash commands (`/sync`, `/tasks`, `/memory`)
- Natural language conversation
- Local auth server for OAuth flows

**Web App** (Next.js + Vue 3, separate repo)
- Rich UI for relationship intelligence
- Real-time notifications
- Visual task management
- Mobile-responsive design

**API** (`zylch/api/`)
- RESTful endpoints
- WebSocket for real-time updates (planned)
- OpenAPI/Swagger documentation
- Authentication via Firebase JWT

#### 2. Business Logic Layer (Services)

**Service Layer** (`zylch/services/`)
- **SyncService**: Email/calendar synchronization
- **ChatService**: Conversational AI orchestration
- **TriggerService**: Event-driven automation (background worker)
- **CommandHandlers**: Slash command processing
- **TaskAgent**: Task detection from emails

**Why Services?**
- Single source of truth (no duplication between CLI and API)
- Testable business logic
- Reusable across interfaces

**Example**: Both CLI and API use the same service:
```python
# CLI calls:
sync_service.run_full_sync(days_back=30)

# API exposes:
POST /api/sync/full {"days_back": 30}
# → calls sync_service.run_full_sync(days_back=30)
```

#### 3. Data Layer (Storage)

**Supabase Postgres** (cloud-based)
- All data stored in Supabase
- Scoped by `owner_id` (Firebase UID)
- Row Level Security (RLS) for multi-tenancy
- pg_vector for semantic search

**Key Tables**:
- `emails` - Email metadata and content
- `calendar_events` - Calendar meetings
- `task_items` - Detected tasks and follow-ups
- `triggers` - Event-driven instructions
- `blobs` - Vector-based semantic memory (facts about contacts)
- `oauth_tokens` - Encrypted tokens

**See**: [Database Schema](#database-schema)

---

### Tool System

Zylch uses a **plugin-based tool system** where each capability is a self-contained tool:

**Tool Pattern**:
```python
class Tool:
    def execute(self, **kwargs) -> ToolResult:
        """Perform action and return result."""
        pass
```

**Available Tools** (`zylch/tools/`):
- **Email**: `gmail.py`, `outlook.py` - Send, read, search emails
- **Calendar**: `gcalendar.py` - Manage Google Calendar events
- **Archive**: `email_archive.py` - Permanent email storage
- **Contacts**: `starchat.py` - MrCall/StarChat CRM integration
- **Memory**: Memory tools in `factory.py` - Save/search memories
- **Tasks**: Task extraction via `task_agent.py`

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

**AI Agent** (`agent/core.py`) orchestrates tool execution based on user requests.

---

## Data Storage Strategy

### Cloud-First Architecture

**Current**: All data in Supabase (cloud-based, Postgres with pg_vector)

**Why Supabase?**
- Cross-device sync out of the box
- Managed infrastructure (no server maintenance)
- Built-in authentication (RLS)
- pg_vector for semantic search (150x faster than brute-force)
- Encryption at rest

### Email Archive and Task Detection

**Problem**: Old system re-fetched 600+ emails every sync (15-30 min), lost history outside 30-day window

**Solution**: Permanent email archive + on-demand task detection

```
┌───────────────────────────────────────────────────────┐
│                   Email Data Flow                      │
└───────────────────────────────────────────────────────┘

Gmail/Outlook API
       │
       ▼
┌──────────────────┐
│  Email Archive   │ ← Permanent storage (all emails)
│   (Supabase)     │ • Full content and metadata
│                  │ • Never deleted
│  Table: emails   │ • Enables full-text search
└─────────┬────────┘ • Cross-device access
          │
          │ (On-demand task detection)
          ▼
┌──────────────────┐
│   Task Items     │ ← AI-detected tasks
│   (Supabase)     │ • Suggested actions
│                  │ • Urgency levels
│ Table: task_items│ • Contact attribution
└──────────────────┘
```

**Benefits**:
- **100x faster sync**: <1s incremental vs 15-30min full fetch
- **Complete history**: Never lose emails (archive is permanent)
- **Efficient AI**: Only analyze recent emails for tasks
- **Fast queries**: Task items pre-computed for instant display

**Performance**:
- Initial archive: ~2 min (one-time for 500 emails)
- Incremental sync: <1s (Gmail History API)
- Task display: <100ms (queries task_items table)

**See**: [Email Archive](../features/email-archive.md)

---

### Memory System (Blobs)

Zylch uses a **blob-based memory system** where semantic knowledge is stored in the `blobs` table with vector embeddings for similarity search.

**Data Flow**:

```
┌─────────────────────────────────────────────────────────┐
│              Memory System Architecture                  │
└─────────────────────────────────────────────────────────┘

I/O Events (Email, Calendar, StarChat)
       │
       ▼
┌──────────────────┐
│  Memory Agent    │ ← Processes raw I/O events
│   Pipeline       │ • Extracts facts and patterns
│                  │ • Stores to blobs (source of truth)
│                  │ • Reconsolidates existing memories
└─────────┬────────┘
          │
          │ (Facts stored in blobs)
          ▼
┌──────────────────┐
│      Blobs       │ ← Semantic Memory Store
│   (Supabase)     │ • All raw facts and patterns
│                  │ • Vector embeddings (semantic search)
│   Table: blobs   │ • Person-centric organization
└──────────────────┘
```

**Key Features**:
- **Reconsolidation**: Similar memories merged (no duplicates)
- **Vector Search**: Semantic similarity via pg_vector
- **Namespacing**: Memories scoped by owner and contact

**See**: [Entity Memory System](../features/entity-memory-system.md)

---

### Database Schema

**Core Tables** (all scoped by `owner_id`):

```sql
-- Email archive (permanent storage)
CREATE TABLE emails (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  thread_id TEXT,
  message_id TEXT UNIQUE,
  from_email TEXT,
  to_email TEXT[],
  subject TEXT,
  body_plain TEXT,
  body_html TEXT,
  date_timestamp TIMESTAMPTZ,
  labels TEXT[],
  -- Full-text search index
  search_vector tsvector,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_emails_owner ON emails(owner_id, date_timestamp DESC);

-- Task items (detected tasks)
CREATE TABLE task_items (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  email_id UUID REFERENCES emails(id),
  contact_email TEXT,
  contact_name TEXT,
  suggested_action TEXT,
  reason TEXT,
  urgency TEXT,  -- 'high', 'medium', 'low'
  sources JSONB,  -- { emails: [...], blobs: [...] }
  analyzed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_task_items_owner ON task_items(owner_id, analyzed_at DESC);

-- Blobs (semantic memory)
CREATE TABLE blobs (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  namespace TEXT NOT NULL,
  category TEXT,
  context TEXT,
  pattern TEXT,
  confidence REAL DEFAULT 0.5,
  embedding vector(384),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_blobs_namespace ON blobs(owner_id, namespace);

-- Calendar events
CREATE TABLE calendar_events (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  event_id TEXT,
  summary TEXT,
  start_time TIMESTAMPTZ,
  end_time TIMESTAMPTZ,
  attendees JSONB,
  meeting_link TEXT,
  memory_processed_at TIMESTAMPTZ DEFAULT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_calendar_owner ON calendar_events(owner_id, start_time);

-- Triggers (event-driven automation)
CREATE TABLE triggers (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  instruction TEXT NOT NULL,
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trigger events (queue for background worker)
CREATE TABLE trigger_events (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_data JSONB,
  status TEXT DEFAULT 'pending',
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- OAuth tokens (encrypted)
CREATE TABLE oauth_tokens (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  email TEXT,
  credentials JSONB,  -- Fernet encrypted
  connection_status TEXT DEFAULT 'connected',
  scopes TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(owner_id, provider)
);

-- Sharing authorizations
CREATE TABLE share_authorizations (
  id UUID PRIMARY KEY,
  sender_email TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(sender_email, recipient_email)
);
```

**Row Level Security** (RLS):
- All tables have RLS policies scoped by `owner_id`
- Backend uses service role key (bypasses RLS, enforces manually)
- **Why?**: Firebase Auth (not Supabase Auth), so `auth.uid()` doesn't match Firebase UIDs

**Encryption**:
- OAuth tokens: Fernet-encrypted before storage
- Email content: Encrypted at rest by Supabase
- API keys (BYOK): Fernet-encrypted

**See**: [Security & Authentication](#security--authentication)

---

## Memory System Design

### Person-Centric Philosophy

**Core Principle**: A person is NOT an email address.

A person can have:
- Multiple email addresses (work, personal, aliases)
- Multiple phone numbers (mobile, office, WhatsApp)
- Multiple names (formal name, nickname, company role)

The memory system must reflect this reality.

### How Human Memory Works (and Zylch Should Too)

Human memory has three phases:
1. **Encoding**: New information arrives
2. **Consolidation**: Information integrates with existing memories
3. **Reconsolidation**: When you recall a memory AND receive new info, you UPDATE the existing memory

**Humans don't create parallel conflicting memories.** If someone gives you a new phone number, you update your mental model - you don't keep two "phone number memories".

**Zylch works the same way.**

### Memory Reconsolidation

When storing a new memory:

```
1. Generate embedding for new content
         ↓
2. Search existing memories for similarity (cosine > 0.85)
         ↓
   ┌─────┴─────┐
   │           │
   ▼           ▼
Similar    No Similar
Found       Found
   │           │
   ▼           ▼
UPDATE     INSERT
(reconsolidate)  (new memory)
```

**Example**:
```python
# First store
mem.store_memory(
    namespace="contacts",
    category="person",
    context="Contact info for Luigi",
    pattern="phone: 348-1234567"
)
# → Creates memory ID 1, confidence 0.5

# Second store (similar content)
mem.store_memory(
    namespace="contacts",
    category="person",
    context="Contact info for Luigi",
    pattern="phone: 339-9876543 (updated)"
)
# → Similarity 0.97 > 0.85 threshold
# → UPDATES memory ID 1, confidence 0.6
# → Only ONE memory exists!
```

**Why This Matters**:
- No conflicting memories (old phone vs new phone)
- Confidence increases with reinforcement
- Mirrors human memory consolidation
- Prevents memory pollution

**See**: [Entity Memory System](../features/entity-memory-system.md)

---

### Memory Architecture

**Semantic Memory** (vector-based)
- **Purpose**: Vector-based semantic storage with reconsolidation
- **Technology**: Supabase pg_vector + sentence-transformers
- **Embedding**: 384-dim vectors (all-MiniLM-L6-v2)
- **Index**: HNSW (Hierarchical Navigable Small World) - 150x faster than brute-force

**Memory Search Flow**:

```
User: "info su Luigi"
       │
       ▼
┌──────────────────────────┐
│ Hybrid Search            │ ← FTS + Semantic
│ (Supabase pg_vector)     │
└──────┬───────────────────┘
       │
       └─ Combines keyword (FTS) and semantic (cosine) scoring
       │
       ▼
┌──────────────────────────┐
│ Results                  │ ← Matching blobs
│ (with context)           │
└──────────────────────────┘
```

**Performance Benefits**:
- **Memory search**: <100ms (hybrid scoring)
- **Task retrieval**: <50ms (pre-computed)

**See**: [Entity Memory System](../features/entity-memory-system.md)

---

### Namespace Architecture

Memories are organized by namespaces for privacy and context:

**Namespace Pattern**: `{scope}:{identifier}`

| Namespace | Purpose | Example |
|-----------|---------|---------|
| `user:{owner_id}` | Personal memories | `user:abc123` |
| `global:skills` | System-wide patterns | `global:skills` |
| `shared:{recipient}:{sender}` | Shared intelligence | `shared:xyz789:abc123` |

**Why Namespaces?**
- **Privacy**: User memories isolated from global
- **Sharing**: Shared memories scoped to sender-recipient pair
- **Retrieval**: Cascading search (user → global → shared)

**Cascading Retrieval**:
1. Search `user:{owner_id}` (1.5x relevance boost for personal patterns)
2. If no match, search `global:skills` (system patterns)
3. If sharing enabled, search `shared:{owner_id}:{*}` (received intelligence)

**See**: [Sharing System](../features/sharing-system.md)

---

## Security & Authentication

### Multi-Layered Security

Zylch implements defense-in-depth:

```
┌─────────────────────────────────────────────────────┐
│                 Security Layers                      │
└─────────────────────────────────────────────────────┘

1. Firebase Auth (JWT validation)
       ↓
2. Row Level Security (RLS) - Supabase
       ↓
3. Application-level encryption (Fernet)
       ↓
4. Supabase encryption at rest
```

### Authentication Flow

**Firebase Auth + Supabase**:

```
User Login (Google/Microsoft OAuth)
       │
       ▼
┌──────────────────┐
│  Firebase Auth   │ ← Issues JWT with custom claims
└────────┬─────────┘
         │ (JWT: { sub: "firebase_uid", email: "user@example.com" })
         ▼
┌──────────────────┐
│  FastAPI Backend │ ← Validates JWT on every request
└────────┬─────────┘
         │ (Extract owner_id from JWT)
         ▼
┌──────────────────┐
│    Supabase      │ ← All queries filtered by owner_id
└──────────────────┘
```

**Why Firebase + Supabase?**
- Firebase: Best-in-class OAuth (Google, Microsoft, Apple)
- Supabase: Powerful Postgres + pg_vector
- Hybrid: Leverage strengths of both

**RLS Bypass**: Backend uses service role key (bypasses RLS) because:
- Firebase UID (text) doesn't match Supabase UUID
- RLS `auth.uid()` returns Supabase UUIDs
- Backend manually enforces `owner_id` scoping

**Defense-in-Depth**: RLS policies still defined for protection if anon key accidentally used.

---

### Token Management

**OAuth Tokens** (Google, Microsoft):
- **Storage**: Supabase `oauth_tokens` table
- **Encryption**: Fernet (AES-128-CBC + HMAC)
- **Auto-refresh**: Tokens refreshed 5 minutes before expiry
- **Scopes**: Stored plaintext (not sensitive)

**All User Credentials** (BYOK):
- **Storage**: Supabase `oauth_tokens` table in unified `credentials` JSONB column
- **Encryption**: Fernet-encrypted (whole JSONB blob)
- **No .env fallback**: Users MUST connect via `/connect <provider>` command
- **Providers**: Anthropic, Vonage, Pipedrive (all BYOK - user provides their own keys)

**Token Storage Pattern**:
```python
# Store (encrypts automatically)
storage.store_oauth_token(owner_id, "anthropic", email, anthropic_api_key="sk-ant-...")
# → credentials JSONB updated → Fernet.encrypt(whole_json) → Supabase

# Retrieve (decrypts automatically)
creds = storage.get_oauth_token(owner_id, "anthropic")
# → Supabase → Fernet.decrypt() → {"api_key": "sk-ant-..."}

# If user hasn't connected provider:
# → Returns None, tool shows "Provider not connected. Use /connect <provider>"
```

**Encryption Key Management**:
- Generate once: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Store in Railway env var: `ENCRYPTION_KEY`
- **Never commit** to git

**Token Auto-Refresh**:
- **Frontend** (Vue 3): Automatic refresh 5 min before expiry
- **CLI** (Python): Automatic refresh in main loop
- **Both**: Use Firebase token refresh API

**See**: [Security & Authentication](../ARCHITECTURE.md#security--authentication) in `docs/ARCHITECTURE.md`

---

### Data Privacy

**Privacy Model**:
- All data scoped by Firebase UID (`owner_id`)
- Row Level Security ensures users only access their own data
- Email content encrypted at rest by Supabase
- OAuth tokens encrypted with Fernet (application-level)
- No data shared between users without explicit consent

**Sharing Model**:
- **Consent-based**: Recipient must authorize before receiving data
- **Namespace isolation**: `shared:{recipient}:{sender}` pattern
- **Attribution**: Shared memories tagged with sender identity
- **Revocable**: Sharing can be revoked at any time

**BYOK (Bring Your Own Key)**:
- Users provide their own Anthropic API key
- Data never sent to third-party AI without user's key
- User controls AI costs directly

**See**: [Sharing System](../features/sharing-system.md)

---

## Performance & Scaling

### Current Performance Characteristics

**Email Operations**:
- Initial archive sync: ~2 min (500 emails, one-time)
- Incremental sync: <1s (Gmail History API)
- Email search: <100ms (Postgres FTS)
- Task display: <100ms (queries task_items)

**Memory Operations**:
- Memory retrieval: O(log n) with HNSW indexing
- Memory storage: <100ms (with reconsolidation check)
- Similarity search: 150x faster than brute-force
- Identifier lookup: <1ms (Supabase index)

**API Response Times**:
- Chat message: 2-5s (depends on tool usage)
- Archive search: 100-300ms
- Task list: <100ms
- Natural language: 5-15s (full agent + Claude)

**Background Workers**:
- Trigger processing: <1s per trigger (Claude Haiku)
- Event queue: Processed every 1 minute

---

### Scalability Considerations

**Current Limits**:
- **Emails**: Tested with 500 messages, scales to millions with Supabase
- **Tasks**: Detected from 30-day email window
- **Concurrent API**: Railway auto-scaling (horizontal)
- **Database**: Supabase connection pooling (up to 60 connections)

**Scaling Strategy**:

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

**See**: [REDIS_SCALING_TODO.md](../features/REDIS_SCALING_TODO.md) for Phase J scaling plan.

---

## Key Architectural Decisions

### Decision 1: Cloud-First Storage

**Problem**: Email data needed across devices (CLI, web, mobile)

**Solution**: Supabase (cloud Postgres) for all data

**Benefits**:
- Cross-device sync out of the box
- No server maintenance
- Built-in authentication (RLS)
- pg_vector for semantic search

**Trade-off**: Privacy (email content in cloud vs local-only)

**Future**: Local-first option for desktop/mobile (Tauri + SQLite)

**See**: `docs/ARCHITECTURE.md#future-local-first-options`

---

### Decision 2: Email Archive + Task Detection

**Problem**: Re-fetching 600+ emails every sync (15-30 min), losing history

**Solution**: Permanent email archive + AI-powered task detection

**Benefits**:
- 100x faster sync (<1s vs 15-30min)
- Complete history preserved
- Efficient AI analysis (only recent emails)

**Implementation**: `emails` table (archive) + `task_items` table (detected tasks)

**See**: [Email Archive and Task Detection](#email-archive-and-task-detection)

---

### Decision 3: Person-Centric Task Detection

**Problem**: Thread-based gaps miss follow-ups across multiple threads

**Solution**: Aggregate threads by contact, detect tasks at person level

**Benefits**:
- Comprehensive relationship view
- Multi-thread task detection
- Relationship strength scoring

**Implementation**: Task Agent (`zylch/tools/task_agent.py`)

**See**: [Relationship Intelligence](../features/relationship-intelligence.md)

---

### Decision 4: Memory Reconsolidation

**Problem**: Duplicate/conflicting memories (old phone vs new phone)

**Solution**: Update existing memory when similar memory found (similarity > 0.85)

**Benefits**:
- No memory conflicts
- Mirrors human memory
- Confidence increases with reinforcement

**Implementation**: Similarity check before INSERT

**See**: [Memory Reconsolidation](#memory-reconsolidation)

---

### Decision 5: Service Layer for CLI and API

**Problem**: Duplicating business logic between CLI and API

**Solution**: Shared service layer (`zylch/services/`)

**Benefits**:
- Single source of truth
- No code duplication
- Easier testing

**Trade-off**: CLI inherits API dependencies

**Pattern**:
```python
# Service (single implementation)
class SyncService:
    def run_full_sync(self, days_back):
        # Business logic here
        pass

# CLI uses service
sync_service.run_full_sync(days_back=30)

# API exposes service
@router.post("/api/sync/full")
def sync_full(request: SyncRequest):
    return sync_service.run_full_sync(request.days_back)
```

---

### Decision 6: Event-Driven Automation

**Problem**: Users want automated actions on events (new email, call received)

**Solution**: Trigger system with background worker

**Benefits**:
- Async processing (non-blocking)
- Retry logic
- Persistent queue

**Implementation**: `triggers` table + `TriggerService` worker

**See**: [Triggers & Automation](../features/triggers-automation.md)

---

### Decision 7: Memory as Source of Truth

**Problem**: Need persistent knowledge about contacts that survives across sessions

**Solution**: Blob-based memory system with vector embeddings

**Benefits**:
- Memory as single source of truth (never lose raw data)
- Semantic search for relevant context
- Reconsolidation prevents duplicates

**Implementation**:
- **Memory Agent Pipeline**: Processes I/O events → stores facts to blobs
- **Data Flow**: I/O → Memory Agent → blobs table

**Performance**:
| Operation | Time |
|-----------|------|
| Memory storage | <100ms (with reconsolidation) |
| Memory search | <100ms (vector similarity) |
| Task display | <100ms (pre-computed) |

**See**: [Memory System Design](#memory-system-design)

---

## Future Architecture

### Local-First Storage (Planned)

**When**: Desktop/mobile apps developed

**Architecture**:
```
┌─────────────────────────────────────────────────────┐
│                    Local Device                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │    CLI      │  │  Desktop    │  │   Mobile    │  │
│  │  (Python)   │  │  (Tauri)    │  │ (React Native)│  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
│         └────────────────┼────────────────┘         │
│                          ▼                          │
│                 ┌─────────────────┐                 │
│                 │  Local SQLite   │ ← emails, cache │
│                 │  (encrypted)    │                 │
│                 └────────┬────────┘                 │
└──────────────────────────┼──────────────────────────┘
                           │ (AI summaries, sync)
                           ▼
                    ┌─────────────┐
                    │  Supabase   │ ← tasks, sharing
                    └─────────────┘
```

**Benefits**:
- Email content stays on device (privacy)
- Offline access
- Faster queries (local SQLite)
- Lower cloud costs

**Trade-offs**:
- Complex sync logic
- Storage limits on mobile
- Backup responsibility

**Technologies**:
- **Desktop**: Tauri (Rust + Vue 3) + SQLite
- **Mobile**: React Native + SQLite (via Capacitor plugin)
- **Sync**: Custom sync engine (local ↔ Supabase)

**See**: [DESKTOP_APP_TODO.md](../features/DESKTOP_APP_TODO.md), [MOBILE_APP_TODO.md](../features/MOBILE_APP_TODO.md)

---

### Real-Time Push Notifications (Planned)

**When**: Real-time features become competitive requirement

**Architecture**:
```
Gmail Push API
       │ (Pub/Sub)
       ▼
┌──────────────┐
│  GCP Pub/Sub │ ← Email arrival notifications
└──────┬───────┘
       │ (webhook)
       ▼
┌──────────────┐
│   Backend    │ ← Process event
└──────┬───────┘
       │
       ├─ Queue task detection
       ├─ Queue trigger events
       └─ Send WebSocket update
       │
       ▼
┌──────────────┐
│  WebSocket   │ ← Push to connected clients
└──────────────┘
```

**Benefits**:
- <5 second latency (email → notification)
- No polling (battery efficient)
- Real-time collaboration

**See**: [REAL_TIME_PUSH_TODO.md](../features/REAL_TIME_PUSH_TODO.md)

---

### Redis Caching Layer (Phase J - Scaling)

**When**: API P95 >500ms OR database costs >$200/month

**Use Cases**:
- Session management (JWT → user data)
- Rate limiting (per-user request counts)
- Task cache (frequently accessed tasks)
- Email thread cache (Supabase → Redis)

**Benefits**:
- Faster API responses (<50ms for cached data)
- Reduced database load
- Lower costs at scale

**See**: [REDIS_SCALING_TODO.md](../features/REDIS_SCALING_TODO.md)

---

## Related Documentation

### Core Features
- **[Email Archive](../features/email-archive.md)** - Email storage and AI-powered analysis
- **[Calendar Integration](../features/calendar-integration.md)** - Google/Microsoft calendars
- **[Relationship Intelligence](../features/relationship-intelligence.md)** - Task detection
- **[Entity Memory System](../features/entity-memory-system.md)** - Entity-centric memory with hybrid search
- **[Triggers & Automation](../features/triggers-automation.md)** - Event-driven automation
- **[Sharing System](../features/sharing-system.md)** - Consent-based intelligence sharing
- **[MrCall Integration](../features/mrcall-integration.md)** - Telephony and WhatsApp

### Guides
- **[CLI Commands](../guides/cli-commands.md)** - Complete CLI reference
- **[Gmail OAuth Setup](../guides/gmail-oauth.md)** - Google authentication
- **[Relationship Intelligence](../features/relationship-intelligence.md)** - Understanding task detection

### Future Development
- **[Billing System](../features/BILLING_SYSTEM_TODO.md)** - Stripe subscriptions (Phase H)
- **[WhatsApp Integration](../features/WHATSAPP_INTEGRATION_TODO.md)** - Multi-channel messaging
- **[Microsoft Calendar](../features/MICROSOFT_CALENDAR_TODO.md)** - Full Outlook support (Phase I.5)
- **[Desktop App](../features/DESKTOP_APP_TODO.md)** - Tauri local-first app
- **[Mobile App](../features/MOBILE_APP_TODO.md)** - React Native iOS + Android
- **[Real-Time Push](../features/REAL_TIME_PUSH_TODO.md)** - Gmail Pub/Sub notifications
- **[Redis Scaling](../features/REDIS_SCALING_TODO.md)** - Caching layer (Phase J)

### Technical Reference
- **[docs/ARCHITECTURE.md](../ARCHITECTURE.md)** - Detailed technical architecture
- **[.claude/DEVELOPMENT_PLAN.md](../../.claude/DEVELOPMENT_PLAN.md)** - Development phases and timeline

---

**Last Updated**: December 2025
