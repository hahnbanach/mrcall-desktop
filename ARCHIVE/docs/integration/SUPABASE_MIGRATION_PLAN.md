# Supabase Migration Plan

**Version:** 1.0
**Date:** December 2025
**Status:** Planning

---

## Executive Summary

Migrate Zylch from single-user SQLite to multi-tenant Supabase (Postgres) to support the production web dashboard at app.zylchai.com.

**Current Problem:** All users share the same SQLite files → data overwrites.
**Solution:** Supabase Postgres with Row-Level Security (RLS) → per-user isolation.

---

## 1. Current State Assessment

### 1.1 SQLite Databases in Use

| Database | Location | Purpose | Size (typical) |
|----------|----------|---------|----------------|
| Email Archive | `cache/emails/archive.db` | Permanent email storage + FTS5 | 5-50 MB |
| ZylchMemory | `.swarm/zylch_memory.db` | Patterns, memories, avatars, embeddings | 1-80 MB |
| Sharing | `cache/sharing.db` | Authorization tokens | <1 MB |
| Pattern Store | `.swarm/patterns.db` | Legacy (deprecated) | — |

### 1.2 JSON Caches in Use

| File | Location | Purpose | Multi-tenant Issue |
|------|----------|---------|-------------------|
| Intelligence Cache | `cache/emails/threads.json` | AI-analyzed threads (30-day) | Shared between users |
| Calendar Cache | `cache/calendar/events.json` | Calendar events | Shared between users |
| Relationship Gaps | `cache/relationship_gaps.json` | Gap analysis results | Shared between users |
| Identifier Map | `cache/identifier_map.json` | O(1) contact lookup | Shared between users |
| Memory JSON | `cache/memory_*.json` | User preferences | Per-user but local |

### 1.3 Avatar Architecture Dependencies

The ZylchMemory Avatar system is **critical** and has these dependencies:

1. **Namespace Hierarchy**: `user:{user_id}:contact:{contact_id}:*`
2. **HNSW Indices**: Per-namespace vector indices for semantic search
3. **Reconsolidation**: UPDATE existing memories (not INSERT duplicates)
4. **Cascading Retrieval**: Contact → User → Global priority

**Migration must preserve:**
- Namespace isolation (maps directly to RLS)
- Semantic search capability (pg_vector replaces HNSW)
- Reconsolidation logic (same algorithm, different DB)
- Avatar aggregation (same queries, Postgres syntax)

### 1.4 Multi-Tenant Requirements

| Requirement | Current | Target |
|-------------|---------|--------|
| User isolation | None | RLS on `owner_id` |
| Data access | Any user reads all | User reads only own data |
| Storage location | Local files | Cloud Postgres |
| OAuth tokens | Local pickle files | Supabase (encrypted with Fernet) |
| API keys | Environment vars | Supabase (encrypted with Fernet) |
| Embeddings | HNSW + SQLite | pg_vector |

---

## 2. Supabase Schema Design

### 2.1 Core Tables with RLS

```sql
-- Enable RLS on all tables
ALTER TABLE emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
-- etc.

-- Standard RLS policy (applied to all user tables)
CREATE POLICY "Users can only access own data" ON {table}
    FOR ALL
    USING (owner_id = auth.uid())
    WITH CHECK (owner_id = auth.uid());
```

### 2.2 Email Archive Schema

```sql
CREATE TABLE emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    gmail_id TEXT NOT NULL,           -- Original Gmail message ID
    thread_id TEXT NOT NULL,
    from_email TEXT,
    from_name TEXT,
    to_emails TEXT,                   -- JSON array
    cc_emails TEXT,                   -- JSON array
    subject TEXT,
    date TIMESTAMPTZ NOT NULL,
    date_timestamp BIGINT,            -- Unix timestamp for fast sorting
    snippet TEXT,
    body_plain TEXT,
    body_html TEXT,
    labels TEXT,                      -- JSON array
    message_id_header TEXT,
    in_reply_to TEXT,
    "references" TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, gmail_id)
);

CREATE INDEX idx_emails_owner ON emails(owner_id);
CREATE INDEX idx_emails_thread ON emails(owner_id, thread_id);
CREATE INDEX idx_emails_date ON emails(owner_id, date_timestamp DESC);
CREATE INDEX idx_emails_from ON emails(owner_id, from_email);

-- Full-text search (Postgres native)
ALTER TABLE emails ADD COLUMN fts_document tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(body_plain, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(from_email, '')), 'C')
    ) STORED;

CREATE INDEX idx_emails_fts ON emails USING GIN(fts_document);
```

### 2.3 Sync State Schema

```sql
CREATE TABLE sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id) UNIQUE,
    history_id TEXT,                  -- Gmail history ID for incremental sync
    last_sync TIMESTAMPTZ,
    full_sync_completed TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 2.4 Intelligence Cache Schema

```sql
CREATE TABLE thread_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    thread_id TEXT NOT NULL,
    contact_email TEXT,
    contact_name TEXT,
    last_email_date TIMESTAMPTZ,
    last_email_direction TEXT,        -- 'inbound' or 'outbound'
    analysis JSONB,                   -- AI analysis result
    needs_action BOOLEAN DEFAULT FALSE,
    task_description TEXT,
    priority INTEGER,
    manually_closed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, thread_id)
);

CREATE INDEX idx_thread_analysis_owner ON thread_analysis(owner_id);
CREATE INDEX idx_thread_analysis_contact ON thread_analysis(owner_id, contact_email);
CREATE INDEX idx_thread_analysis_action ON thread_analysis(owner_id, needs_action) WHERE needs_action = TRUE;
```

### 2.5 Relationship Gaps Schema

```sql
CREATE TABLE relationship_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    gap_type TEXT NOT NULL,           -- 'meeting_no_followup', 'urgent_no_meeting', 'silent_contact', 'email_task'
    contact_email TEXT,
    contact_name TEXT,
    details JSONB,                    -- Type-specific details
    priority INTEGER,
    suggested_action TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,

    UNIQUE(owner_id, gap_type, contact_email)  -- Prevent duplicates
);

CREATE INDEX idx_gaps_owner ON relationship_gaps(owner_id);
CREATE INDEX idx_gaps_unresolved ON relationship_gaps(owner_id, resolved_at) WHERE resolved_at IS NULL;
```

### 2.6 Calendar Events Schema

```sql
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    google_event_id TEXT NOT NULL,
    summary TEXT,
    description TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    location TEXT,
    attendees JSONB,                  -- Array of {email, name, status}
    organizer_email TEXT,
    is_external BOOLEAN DEFAULT FALSE,
    meet_link TEXT,
    calendar_id TEXT DEFAULT 'primary',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, google_event_id)
);

CREATE INDEX idx_calendar_owner ON calendar_events(owner_id);
CREATE INDEX idx_calendar_time ON calendar_events(owner_id, start_time);
CREATE INDEX idx_calendar_attendee ON calendar_events USING GIN(attendees);
```

### 2.7 ZylchMemory Schema (Patterns + Avatars)

```sql
-- Enable pg_vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Patterns table (skill learning)
CREATE TABLE patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    namespace TEXT NOT NULL,          -- 'user:{uid}:contact:{cid}:behavioral:email'
    skill TEXT NOT NULL,
    intent TEXT NOT NULL,
    context JSONB,
    action JSONB,
    outcome TEXT,
    contact_id TEXT,                  -- Denormalized for fast queries
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    times_successful INTEGER DEFAULT 0,
    state TEXT DEFAULT 'active',      -- active, stale, archived
    embedding vector(384),            -- pg_vector for semantic search
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed TIMESTAMPTZ,

    UNIQUE(owner_id, namespace, skill, intent)
);

CREATE INDEX idx_patterns_owner ON patterns(owner_id);
CREATE INDEX idx_patterns_namespace ON patterns(owner_id, namespace);
CREATE INDEX idx_patterns_skill ON patterns(owner_id, skill);
CREATE INDEX idx_patterns_contact ON patterns(owner_id, contact_id);
CREATE INDEX idx_patterns_embedding ON patterns USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Memories table (behavioral rules)
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    namespace TEXT NOT NULL,
    category TEXT NOT NULL,           -- email, calendar, whatsapp, mrcall, task
    context TEXT,
    pattern TEXT,
    examples JSONB,
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    state TEXT DEFAULT 'active',
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed TIMESTAMPTZ
);

CREATE INDEX idx_memories_owner ON memories(owner_id);
CREATE INDEX idx_memories_namespace ON memories(owner_id, namespace);
CREATE INDEX idx_memories_category ON memories(owner_id, category);
CREATE INDEX idx_memories_embedding ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Avatars table (aggregated contact profiles)
CREATE TABLE avatars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    contact_id TEXT NOT NULL,
    display_name TEXT,
    identifiers JSONB,                -- Array of emails/phones
    preferred_channel TEXT,
    preferred_tone TEXT,
    preferred_language TEXT,
    response_latency JSONB,           -- ResponseLatency object
    aggregated_preferences JSONB,
    relationship_strength REAL,
    first_interaction TIMESTAMPTZ,
    last_interaction TIMESTAMPTZ,
    interaction_count INTEGER DEFAULT 0,
    profile_confidence REAL DEFAULT 0.5,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, contact_id)
);

CREATE INDEX idx_avatars_owner ON avatars(owner_id);
CREATE INDEX idx_avatars_contact ON avatars(owner_id, contact_id);

-- Identifier map (for O(1) contact lookup)
CREATE TABLE identifier_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    identifier TEXT NOT NULL,         -- Normalized email/phone/name
    identifier_type TEXT NOT NULL,    -- 'email', 'phone', 'name'
    contact_id TEXT NOT NULL,         -- Links to avatar
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, identifier)
);

CREATE INDEX idx_identifier_owner ON identifier_map(owner_id);
CREATE INDEX idx_identifier_lookup ON identifier_map(owner_id, identifier);
```

### 2.8 OAuth Tokens Schema (with Encryption)

```sql
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,              -- Firebase UID
    provider TEXT NOT NULL,              -- 'google', 'microsoft', 'anthropic'
    email TEXT,
    google_token_data TEXT,              -- Encrypted JSON (Google OAuth)
    graph_access_token TEXT,             -- Encrypted (Microsoft Graph)
    graph_refresh_token TEXT,            -- Encrypted (Microsoft refresh)
    graph_expires_at TIMESTAMPTZ,
    anthropic_api_key TEXT,              -- Encrypted (user's BYOK key)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, provider)
);

CREATE INDEX idx_oauth_owner ON oauth_tokens(owner_id);
CREATE INDEX idx_oauth_provider ON oauth_tokens(owner_id, provider);

-- RLS policy
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own tokens" ON oauth_tokens
    FOR ALL USING (owner_id = auth.uid()::text);
```

**Encryption:** All token fields are encrypted with Fernet (AES-128-CBC + HMAC) before storage. The `ENCRYPTION_KEY` is stored only in Railway environment, never in Supabase.

### 2.9 Sharing/Authorization Schema

```sql
CREATE TABLE authorizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES auth.users(id),
    recipient_id UUID NOT NULL REFERENCES auth.users(id),
    permissions JSONB,                -- {read: true, write: false, ...}
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,

    UNIQUE(owner_id, recipient_id)
);

-- Special RLS: owner can manage, recipient can read their grants
CREATE POLICY "Owners manage authorizations" ON authorizations
    FOR ALL USING (owner_id = auth.uid());

CREATE POLICY "Recipients see their grants" ON authorizations
    FOR SELECT USING (recipient_id = auth.uid());
```

---

## 3. Migration Strategy

### 3.1 Direct Migration (Alpha - No Dual-Write)

Siamo in alpha, migrazione diretta senza complessità:

```
Phase 1: Setup Supabase (1 giorno)
├── Crea progetto Supabase
├── Esegui schema SQL con RLS
├── Configura pg_vector extension
└── Test connessione

Phase 2: Backend Switch (2-3 giorni)
├── Crea SupabaseStorage class
├── Sostituisci SQLiteArchiveBackend → SupabaseBackend
├── Sostituisci JSON caches → Postgres tables
├── Aggiungi owner_id a tutte le query
└── Test locale

Phase 3: Deploy & Test (1 giorno)
├── Aggiungi env vars su Railway
├── Deploy
├── Test con 2 utenti diversi (verifica isolamento)
└── Done
```

**Totale: ~4-5 giorni**

### 3.2 Data Migration Scripts

**Email Archive Migration:**
```python
async def migrate_email_archive(user_id: str, supabase_client):
    """Migrate user's email archive from SQLite to Supabase"""
    sqlite_path = f"cache/emails/archive.db"

    conn = sqlite3.connect(sqlite_path)
    cursor = conn.execute("SELECT * FROM emails")

    batch = []
    for row in cursor:
        batch.append({
            'owner_id': user_id,
            'gmail_id': row['id'],
            'thread_id': row['thread_id'],
            'from_email': row['from_email'],
            'from_name': row['from_name'],
            'to_emails': row['to_emails'],
            'subject': row['subject'],
            'date': row['date'],
            'date_timestamp': row['date_timestamp'],
            'body_plain': row['body_plain'],
            'labels': row['labels'],
            # ... other fields
        })

        if len(batch) >= 500:
            await supabase_client.table('emails').upsert(batch).execute()
            batch = []

    if batch:
        await supabase_client.table('emails').upsert(batch).execute()
```

**Memory Migration with Embeddings:**
```python
async def migrate_patterns(user_id: str, supabase_client):
    """Migrate patterns with embeddings to Supabase"""
    memory_db = f".swarm/zylch_memory.db"

    conn = sqlite3.connect(memory_db)
    cursor = conn.execute("""
        SELECT p.*, e.vector
        FROM patterns p
        LEFT JOIN embeddings e ON p.embedding_id = e.id
        WHERE p.user_id = ?
    """, (user_id,))

    for row in cursor:
        embedding = None
        if row['vector']:
            embedding = np.frombuffer(row['vector'], dtype=np.float32).tolist()

        await supabase_client.table('patterns').upsert({
            'owner_id': user_id,
            'namespace': row['namespace'],
            'skill': row['skill'],
            'intent': row['intent'],
            'context': json.loads(row['context']) if row['context'] else None,
            'action': json.loads(row['action']) if row['action'] else None,
            'confidence': row['confidence'],
            'embedding': embedding,
            # ... other fields
        }).execute()
```

### 3.3 Backend Code Changes

**New Storage Layer:**
```python
# zylch/storage/supabase_client.py
from supabase import create_client, Client

class SupabaseStorage:
    def __init__(self, url: str, key: str):
        self.client: Client = create_client(url, key)

    async def get_emails(self, owner_id: str, limit: int = 100) -> List[dict]:
        """Get emails for user (RLS enforced)"""
        result = await self.client.table('emails')\
            .select('*')\
            .eq('owner_id', owner_id)\
            .order('date_timestamp', desc=True)\
            .limit(limit)\
            .execute()
        return result.data

    async def search_emails(self, owner_id: str, query: str) -> List[dict]:
        """Full-text search using Postgres FTS"""
        result = await self.client.rpc('search_emails', {
            'search_query': query,
            'user_id': owner_id
        }).execute()
        return result.data

    async def semantic_search_patterns(
        self,
        owner_id: str,
        embedding: List[float],
        limit: int = 5
    ) -> List[dict]:
        """Semantic search using pg_vector"""
        result = await self.client.rpc('search_similar_patterns', {
            'query_embedding': embedding,
            'user_id': owner_id,
            'match_count': limit
        }).execute()
        return result.data
```

**Supabase Functions (SQL):**
```sql
-- Full-text search function
CREATE OR REPLACE FUNCTION search_emails(search_query TEXT, user_id UUID)
RETURNS SETOF emails AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM emails
    WHERE owner_id = user_id
      AND fts_document @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(fts_document, plainto_tsquery('english', search_query)) DESC
    LIMIT 100;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Semantic search function (pg_vector)
CREATE OR REPLACE FUNCTION search_similar_patterns(
    query_embedding vector(384),
    user_id UUID,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    id UUID,
    namespace TEXT,
    skill TEXT,
    intent TEXT,
    action JSONB,
    confidence REAL,
    similarity REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        p.id,
        p.namespace,
        p.skill,
        p.intent,
        p.action,
        p.confidence,
        1 - (p.embedding <=> query_embedding) AS similarity
    FROM patterns p
    WHERE p.owner_id = user_id
      AND p.state = 'active'
      AND p.confidence >= 0.4
    ORDER BY p.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

---

## 4. Authentication Strategy

### 4.1 Option A: Keep Firebase Auth + Supabase Storage

```
User → Firebase Auth → Get Firebase JWT →
Backend validates JWT → Extract UID →
Use UID as owner_id in Supabase queries
```

**Pros:** No auth migration, users keep existing logins
**Cons:** Two auth systems, Supabase RLS needs custom JWT validation

### 4.2 Option B: Migrate to Supabase Auth

```
User → Supabase Auth → Get Supabase JWT →
Backend uses JWT → RLS automatically enforced
```

**Pros:** Single auth system, native RLS support
**Cons:** Users must re-authenticate, migration effort

### 4.3 Recommendation: Option A (Phase 1), then Option B (Phase 2)

1. **Phase 1:** Keep Firebase Auth, manually pass `owner_id` to queries
2. **Phase 2:** Evaluate Supabase Auth migration based on user feedback

---

## 5. Risk Analysis

### 5.1 Critical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Data loss during migration | Critical | Low | Dual-write mode, SQLite backup |
| RLS misconfiguration | Critical | Medium | Thorough testing, security audit |
| Performance regression | High | Medium | Benchmark before/after, indexing |
| Avatar search quality degradation | High | Low | Side-by-side comparison testing |
| Reconsolidation logic failure | High | Low | Unit tests, same algorithm |

### 5.2 Rollback Plan

Each phase has rollback capability:

```
Phase 2-3 (Email): Revert to SQLite reads (data still there)
Phase 4-5 (Memory): Revert to HNSW + SQLite (data still there)
Phase 6 (Caches): Revert to JSON files (regenerate from API)
```

**Point of no return:** After Phase 7 cleanup. Before that, full rollback possible.

---

## 6. Cost Analysis

### 6.1 Supabase Pricing (Pro Plan)

| Resource | Included | Overage |
|----------|----------|---------|
| Database | 8GB | $0.125/GB |
| Bandwidth | 250GB | $0.09/GB |
| Auth MAUs | 100K | $0.00325/MAU |
| Storage | 100GB | $0.021/GB |

**Estimated monthly cost for 100 users:**
- Database: ~2GB = $0 (included)
- Bandwidth: ~10GB = $0 (included)
- Auth: 100 MAU = $0 (included)
- **Total: $25/month** (Pro plan base)

### 6.2 Comparison with Current

| Item | Current (Railway SQLite) | Supabase |
|------|--------------------------|----------|
| Database | $0 (embedded) | $25/month |
| Backup | Manual | Automatic |
| Multi-tenant | None | Built-in RLS |
| Scaling | Limited | Automatic |

---

## 7. Timeline Estimate

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Setup Supabase | 1 giorno | None |
| Phase 2: Backend Switch | 2-3 giorni | Phase 1 |
| Phase 3: Deploy & Test | 1 giorno | Phase 2 |

**Totale: ~4-5 giorni**

---

## 8. Testing Checklist

### 8.1 Security Tests

- [ ] User A cannot read User B's emails
- [ ] User A cannot read User B's patterns
- [ ] User A cannot read User B's avatars
- [ ] RLS works with service role key bypass (for migrations)
- [ ] SQL injection attempts blocked

### 8.2 Functional Tests

- [ ] Email sync works (incremental + full)
- [ ] Email search returns correct results
- [ ] Pattern storage with reconsolidation
- [ ] Semantic search returns similar patterns
- [ ] Avatar aggregation produces correct output
- [ ] Identifier map lookup works
- [ ] Gap analysis produces correct gaps

### 8.3 Performance Tests

- [ ] Email search < 100ms (1000 emails)
- [ ] Semantic search < 50ms (10k patterns)
- [ ] Incremental sync < 5s
- [ ] Full page load < 2s

---

## 9. Decision Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DB provider | Supabase | Postgres + pg_vector + RLS + affordable |
| Auth strategy | Firebase first, then evaluate | Minimize user disruption |
| Migration approach | Dual-write | Safe, reversible |
| Embedding storage | pg_vector | Native Postgres, no external service |
| FTS approach | Postgres native | Good enough, no extra cost |
| Token encryption | Fernet (AES-128-CBC + HMAC) | Industry standard, key separation |
| Encryption key storage | Railway only | Neither Supabase nor attackers can decrypt |

---

## 10. Next Steps

1. **Create Supabase project** (manual step)
2. **Run schema creation script** (this document's SQL)
3. **Update config.py** with Supabase credentials
4. **Create SupabaseStorage class**
5. **Implement dual-write in EmailArchiveBackend**
6. **Test with single user**
7. **Proceed with migration phases**

---

**Document Owner:** Development Team
**Last Updated:** December 6, 2025

---

## Appendix: SQL Migrations

### A.1 Add Anthropic API Key Column

```sql
-- Run this in Supabase SQL Editor
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS anthropic_api_key TEXT;
```

### A.2 Encryption Utility (Python)

```python
# zylch/utils/encryption.py
from cryptography.fernet import Fernet

def encrypt(plaintext: str) -> str:
    fernet = _get_fernet()  # Gets key from ENCRYPTION_KEY env
    if not fernet:
        return plaintext  # Graceful fallback for local dev
    return fernet.encrypt(plaintext.encode()).decode()

def decrypt(ciphertext: str) -> str:
    fernet = _get_fernet()
    if not fernet:
        return ciphertext
    return fernet.decrypt(ciphertext.encode()).decode()
```
