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
        │  │  • Memory Agent Pipeline         │  │
        │  │  • CRM Agent Pipeline            │  │
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
- Slash commands (`/sync`, `/gaps`, `/memory`)
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
- **GapService**: Relationship gap detection
- **ChatService**: Conversational AI orchestration
- **TriggerService**: Event-driven automation (background worker)
- **CommandHandlers**: Slash command processing

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
- `avatars` - Pre-computed contact intelligence
- `triggers` - Event-driven instructions
- `memories` - Vector-based memory store
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
- **Tasks**: Task extraction and gap analysis

**Tool Registration** (`factory.py`):
```python
def create_all_tools(config, memory, owner_id):
    tools = [
        _SyncEmailsTool(sync_service),
        _GetContactTool(starchat_client),
        _SaveContactTool(starchat_client, memory),
        _SearchLocalMemoryTool(memory),
        _GetTasksTool(gap_service),
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

### Two-Tier Email Storage

**Problem**: Old system re-fetched 600+ emails every sync (15-30 min), lost history outside 30-day window

**Solution**: Separate archive (permanent) and intelligence (30-day window)

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
          │ (On-demand analysis)
          ▼
┌──────────────────┐
│  Intelligence    │ ← AI-generated analysis (30-day window)
│   (Supabase)     │ • Summaries, tasks, gaps
│                  │ • Refreshed weekly
│  Table: avatars  │ • Pre-computed for speed
└──────────────────┘
```

**Benefits**:
- **100x faster sync**: <1s incremental vs 15-30min full fetch
- **Complete history**: Never lose emails (archive is permanent)
- **Efficient AI**: Only analyze recent 30 days (reduces cost)
- **Fast queries**: Pre-computed avatars = instant gap detection

**Performance**:
- Initial archive: ~2 min (one-time for 500 emails)
- Incremental sync: <1s (Gmail History API)
- Gap analysis: <100ms (queries pre-computed avatars)

**See**: [Email Archive](../features/email-archive.md)

---

### Von Neumann Memory Architecture

**Philosophy**: Memory as single source of truth, Avatar as computed view

Zylch implements a **Von Neumann-inspired architecture** where the Memory system is the authoritative data store, and Avatar (contact intelligence) is a computed/cached view derived from Memory.

**Core Principle**:
- **Memory** = Source of Truth (I/O events, raw data, facts)
- **Avatar** = Computed View (aggregated intelligence, formatted for display)

**Data Flow**:

```
┌─────────────────────────────────────────────────────────┐
│         Von Neumann Memory Architecture                  │
└─────────────────────────────────────────────────────────┘

I/O Events (Email, Calendar, StarChat)
       │
       ▼
┌──────────────────┐
│  Memory Agent    │ ← Processes raw I/O events
│   Pipeline       │ • Extracts facts and patterns
│                  │ • Stores to Memory (source of truth)
│                  │ • Reconsolidates existing memories
└─────────┬────────┘
          │
          │ (Facts stored in Memory)
          ▼
┌──────────────────┐
│     Memory       │ ← Single Source of Truth
│   (Supabase)     │ • All raw facts and patterns
│                  │ • Vector embeddings (semantic search)
│  Table: memories │ • Never deleted
└─────────┬────────┘
          │
          │ (On-demand or scheduled computation)
          ▼
┌──────────────────┐
│   CRM Agent      │ ← Computes Avatar from Memory
│    Pipeline      │ • Reads from Memory
│                  │ • Aggregates by contact
│                  │ • Formats for display
└─────────┬────────┘
          │
          │ (Computed intelligence)
          ▼
┌──────────────────┐
│     Avatar       │ ← Computed View (Cache)
│   (Supabase)     │ • Pre-computed contact intelligence
│                  │ • Relationship status & score
│  Table: avatars  │ • Suggested actions (formatted)
└──────────────────┘ • 30-day TTL (recomputed as needed)
```

**Key Differences from Old System**:

| Aspect | Old System (AvatarComputeWorker) | New System (Von Neumann) |
|--------|----------------------------------|--------------------------|
| **Source of Truth** | Avatars (mixed raw + computed) | Memory (only raw facts) |
| **Data Flow** | I/O → Avatar (direct) | I/O → Memory → Avatar (computed) |
| **Avatar Role** | Primary storage | Cached view |
| **Recomputation** | Difficult (data mixed) | Easy (recompute from Memory) |
| **Consistency** | Prone to drift | Always consistent with Memory |

**Benefits**:
- **Separation of Concerns**: Raw data (Memory) vs computed view (Avatar)
- **Recomputable**: Avatar can always be regenerated from Memory
- **Flexible**: Change Avatar format without losing data
- **Auditable**: Memory contains complete history of facts
- **Scalable**: Avatar computation can be parallelized or distributed

**Pipeline Triggers**:
1. **Memory Agent Pipeline** (after I/O events):
   - Email sync → Extract facts → Store to Memory
   - Calendar sync → Extract meetings → Store to Memory
   - StarChat call → Extract contact info → Store to Memory

2. **CRM Agent Pipeline** (scheduled or on-demand):
   - Nightly: Recompute all Avatars from Memory
   - On-demand: Recompute specific Avatar when requested
   - After Memory update: Mark affected Avatars as stale

**Performance**:
- Memory storage: <100ms (with reconsolidation)
- Avatar computation: ~5 min for 15 contacts (background)
- Avatar retrieval: <100ms (cached, pre-computed)

**See**: [Von Neumann Architecture](../features/von-neumann-architecture.md) (if exists)

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
  to_emails TEXT[],
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

-- Avatar intelligence (pre-computed)
CREATE TABLE avatars (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  contact_id TEXT NOT NULL,  -- 12-char MD5 hash
  display_name TEXT,
  relationship_status TEXT,  -- 'open', 'waiting', 'closed'
  relationship_score INTEGER,  -- 0-10
  suggested_actions JSONB,
  last_interaction TIMESTAMPTZ,
  aggregation_timestamp TIMESTAMPTZ,
  -- pg_vector for semantic search
  embedding vector(384)
);
CREATE INDEX idx_avatars_owner ON avatars(owner_id, relationship_score DESC);

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
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_calendar_owner ON calendar_events(owner_id, start_time);

-- Triggers (event-driven automation)
CREATE TABLE triggers (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  event_type TEXT NOT NULL,  -- 'session_start', 'email_received', etc.
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
  status TEXT DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
  processed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Memory system (vector storage)
CREATE TABLE memories (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  namespace TEXT NOT NULL,  -- 'user:{owner_id}', 'global:skills', 'shared:{recipient}:{sender}'
  category TEXT,  -- 'email', 'contacts', 'calendar', 'task', 'general'
  context TEXT,
  pattern TEXT,
  confidence REAL DEFAULT 0.5,
  embedding vector(384),  -- Sentence-transformers all-MiniLM-L6-v2
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_memories_namespace ON memories(owner_id, namespace);

-- OAuth tokens (encrypted) - Unified JSONB credentials storage
CREATE TABLE oauth_tokens (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  provider TEXT NOT NULL,  -- 'google', 'microsoft', 'anthropic', 'vonage', etc.
  email TEXT,
  credentials JSONB,  -- Unified encrypted credentials (Fernet)
  connection_status TEXT DEFAULT 'connected',
  scopes TEXT[],
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(owner_id, provider)
);
-- NOTE: Legacy columns (google_token_data, graph_*, anthropic_api_key) removed
-- All credentials now stored in unified JSONB 'credentials' column

-- Sharing authorizations
CREATE TABLE share_authorizations (
  id UUID PRIMARY KEY,
  sender_email TEXT NOT NULL,
  recipient_email TEXT NOT NULL,
  status TEXT DEFAULT 'pending',  -- 'pending', 'accepted', 'rejected', 'revoked'
  accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(sender_email, recipient_email)
);

-- User notifications (background worker alerts)
CREATE TABLE user_notifications (
  id UUID PRIMARY KEY,
  owner_id TEXT NOT NULL,
  message TEXT NOT NULL,
  notification_type TEXT DEFAULT 'info',  -- 'info', 'warning', 'error'
  read BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
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

**See**: [Memory System](../features/memory-system.md)

---

### Two-Layer Memory Architecture

**Layer 1: Identifier Map** (fast lookup)
- **Purpose**: O(1) lookup from any identifier to person
- **Technology**: Supabase with indexed queries
- **Maps**: email/phone/name → contact_id (12-char MD5 hash)
- **Benefit**: Avoids expensive API calls (Gmail 10+ seconds) when contact is known

**Layer 2: Semantic Memory** (vector-based)
- **Purpose**: Vector-based semantic storage with reconsolidation
- **Technology**: Supabase pg_vector + sentence-transformers
- **Embedding**: 384-dim vectors (all-MiniLM-L6-v2)
- **Index**: HNSW (Hierarchical Navigable Small World) - 150x faster than brute-force

**Memory Lookup Flow**:

```
User: "info su Luigi"
       │
       ▼
┌──────────────────────────┐
│ 1. Identifier Map Lookup │ ← O(1), <1ms
│    (Supabase index)      │
└──────┬───────────────────┘
       │
       ├─ Found & Fresh (TTL 7 days) → RETURN CACHED
       ├─ Found & Stale → Return cached + suggest refresh
       └─ Not Found → Proceed to remote searches
       │
       ▼
┌──────────────────────────┐
│ 2. Remote Searches       │ ← Only if not cached
│    (ONLY IF NEEDED)      │
└──────────────────────────┘
       │
       ├─ StarChat CRM search
       ├─ Local email archive search
       ├─ Gmail API search (10+ seconds!)
       └─ Calendar events search
```

**Performance Benefits**:
- **Cached contact**: <1ms (Supabase index)
- **Uncached contact**: 2-15s (remote APIs)
- **Cache hit rate**: ~85% (most queries are repeat lookups)

**See**: [Avatar Aggregation](../features/avatar-aggregation.md)

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

**See**: [Security & Authentication](#security--authentication) in `.claude/ARCHITECTURE.md`

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
- Gap analysis: <100ms (pre-computed avatars)

**Memory Operations**:
- Memory retrieval: O(log n) with HNSW indexing
- Memory storage: <100ms (with reconsolidation check)
- Similarity search: 150x faster than brute-force
- Identifier lookup: <1ms (Supabase index)

**API Response Times**:
- Chat message: 2-5s (depends on tool usage)
- Archive search: 100-300ms
- Gap analysis: 1-3s
- Natural language: 5-15s (full agent + Claude)

**Background Workers**:
- Avatar computation: ~5 min for 15 contacts after `/sync`
- Trigger processing: <1s per trigger (Claude Haiku)
- Event queue: Processed every 1 minute

---

### Scalability Considerations

**Current Limits**:
- **Emails**: Tested with 500 messages, scales to millions with Supabase
- **Avatars**: 30-day window (~250-300 contacts typical)
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
- Separate worker pool for triggers/avatars
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

**See**: `.claude/ARCHITECTURE.md#future-local-first-options`

---

### Decision 2: Two-Tier Email Storage

**Problem**: Re-fetching 600+ emails every sync (15-30 min), losing history

**Solution**: Separate permanent archive and 30-day intelligence cache

**Benefits**:
- 100x faster sync (<1s vs 15-30min)
- Complete history preserved
- Efficient AI analysis (only recent emails)

**Implementation**: `emails` table (archive) + `avatars` table (intelligence)

**See**: [Two-Tier Email Storage](#two-tier-email-storage)

---

### Decision 3: Person-Centric Task Detection

**Problem**: Thread-based gaps miss follow-ups across multiple threads

**Solution**: Aggregate threads by contact, detect tasks at person level

**Benefits**:
- Comprehensive relationship view
- Multi-thread task detection
- Relationship strength scoring

**Implementation**: Avatar aggregation service

**See**: [Avatar Aggregation](../features/avatar-aggregation.md)

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

### Decision 7: Von Neumann Memory Architecture

**Problem**: Mixed raw data and computed intelligence in Avatars, making recomputation difficult

**Solution**: Separate Memory (source of truth) and Avatar (computed view) with agent pipelines

**Benefits**:
- Memory as single source of truth (never lose raw data)
- Avatar can be recomputed from Memory at any time
- Flexible Avatar format (change without data loss)
- Clear separation: Memory Agent (I/O → Memory) and CRM Agent (Memory → Avatar)

**Implementation**:
- **Memory Agent Pipeline**: Processes I/O events → stores facts to Memory
- **CRM Agent Pipeline**: Reads Memory → computes Avatar intelligence
- **Data Flow**: I/O → Memory Agent → Memory → CRM Agent → Avatar

**Performance**:
| Operation | Time |
|-----------|------|
| Memory storage | <100ms (with reconsolidation) |
| Avatar computation | ~5 min for 15 contacts (background) |
| Avatar retrieval | <100ms (cached) |
| Avatar recomputation | On-demand or scheduled (nightly) |

**See**: [Von Neumann Architecture](#von-neumann-memory-architecture)

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
                    │  Supabase   │ ← avatars, sharing
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
       ├─ Queue avatar computation
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
- Avatar cache (30-day TTL)
- Email thread cache (Supabase → Redis)

**Benefits**:
- Faster API responses (<50ms for cached data)
- Reduced database load
- Lower costs at scale

**See**: [REDIS_SCALING_TODO.md](../features/REDIS_SCALING_TODO.md)

---

## Related Documentation

### Core Features
- **[Email Archive](../features/email-archive.md)** - Two-tier email storage
- **[Email Archive](../features/email-archive.md)** - Two-tier email storage and AI-powered analysis
- **[Calendar Integration](../features/calendar-integration.md)** - Google/Microsoft calendars
- **[Relationship Intelligence](../features/relationship-intelligence.md)** - Gap detection
- **[Avatar Aggregation](../features/avatar-aggregation.md)** - Person-centric intelligence
- **[Memory System](../features/memory-system.md)** - Vector-based memory with reconsolidation
- **[Triggers & Automation](../features/triggers-automation.md)** - Event-driven automation
- **[Sharing System](../features/sharing-system.md)** - Consent-based intelligence sharing
- **[MrCall Integration](../features/mrcall-integration.md)** - Telephony and WhatsApp

### Guides
- **[CLI Commands](../guides/cli-commands.md)** - Complete CLI reference
- **[Gmail OAuth Setup](../guides/gmail-oauth.md)** - Google authentication
- **[Relationship Intelligence](../features/relationship-intelligence.md)** - Understanding gap detection

### Future Development
- **[Billing System](../features/BILLING_SYSTEM_TODO.md)** - Stripe subscriptions (Phase H)
- **[WhatsApp Integration](../features/WHATSAPP_INTEGRATION_TODO.md)** - Multi-channel messaging
- **[Microsoft Calendar](../features/MICROSOFT_CALENDAR_TODO.md)** - Full Outlook support (Phase I.5)
- **[Desktop App](../features/DESKTOP_APP_TODO.md)** - Tauri local-first app
- **[Mobile App](../features/MOBILE_APP_TODO.md)** - React Native iOS + Android
- **[Real-Time Push](../features/REAL_TIME_PUSH_TODO.md)** - Gmail Pub/Sub notifications
- **[Redis Scaling](../features/REDIS_SCALING_TODO.md)** - Caching layer (Phase J)

### Technical Reference
- **[.claude/ARCHITECTURE.md](../../.claude/ARCHITECTURE.md)** - Detailed technical architecture
- **[.claude/DEVELOPMENT_PLAN.md](../../.claude/DEVELOPMENT_PLAN.md)** - Development phases and timeline

---

**Last Updated**: December 2025
