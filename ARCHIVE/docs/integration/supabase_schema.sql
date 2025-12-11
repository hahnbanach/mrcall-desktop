-- ============================================
-- ZYLCH SUPABASE SCHEMA
-- Phase 1: Core tables with RLS
-- ============================================

-- Enable pg_vector extension for embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- 1. EMAILS TABLE (Email Archive)
-- ============================================
CREATE TABLE emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    gmail_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    from_email TEXT,
    from_name TEXT,
    to_emails TEXT,
    cc_emails TEXT,
    subject TEXT,
    date TIMESTAMPTZ NOT NULL,
    date_timestamp BIGINT,
    snippet TEXT,
    body_plain TEXT,
    body_html TEXT,
    labels TEXT,
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

-- Full-text search
ALTER TABLE emails ADD COLUMN fts_document tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(body_plain, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(from_email, '')), 'C')
    ) STORED;

CREATE INDEX idx_emails_fts ON emails USING GIN(fts_document);

-- RLS
ALTER TABLE emails ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own emails" ON emails
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 2. SYNC STATE TABLE
-- ============================================
CREATE TABLE sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL UNIQUE,
    history_id TEXT,
    last_sync TIMESTAMPTZ,
    full_sync_completed TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE sync_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own sync_state" ON sync_state
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 3. THREAD ANALYSIS TABLE (Intelligence Cache)
-- ============================================
CREATE TABLE thread_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    thread_id TEXT NOT NULL,
    contact_email TEXT,
    contact_name TEXT,
    last_email_date TIMESTAMPTZ,
    last_email_direction TEXT,
    analysis JSONB,
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

ALTER TABLE thread_analysis ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own thread_analysis" ON thread_analysis
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 4. RELATIONSHIP GAPS TABLE
-- ============================================
CREATE TABLE relationship_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    gap_type TEXT NOT NULL,
    contact_email TEXT,
    contact_name TEXT,
    details JSONB,
    priority INTEGER,
    suggested_action TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_gaps_owner ON relationship_gaps(owner_id);
CREATE INDEX idx_gaps_unresolved ON relationship_gaps(owner_id, resolved_at) WHERE resolved_at IS NULL;

ALTER TABLE relationship_gaps ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own gaps" ON relationship_gaps
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 5. CALENDAR EVENTS TABLE
-- ============================================
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    google_event_id TEXT NOT NULL,
    summary TEXT,
    description TEXT,
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    location TEXT,
    attendees JSONB,
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

ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own calendar" ON calendar_events
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 6. PATTERNS TABLE (ZylchMemory)
-- ============================================
CREATE TABLE patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    namespace TEXT NOT NULL,
    skill TEXT NOT NULL,
    intent TEXT NOT NULL,
    context JSONB,
    action JSONB,
    outcome TEXT,
    contact_id TEXT,
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    times_successful INTEGER DEFAULT 0,
    state TEXT DEFAULT 'active',
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_accessed TIMESTAMPTZ,
    UNIQUE(owner_id, namespace, skill, intent)
);

CREATE INDEX idx_patterns_owner ON patterns(owner_id);
CREATE INDEX idx_patterns_namespace ON patterns(owner_id, namespace);
CREATE INDEX idx_patterns_skill ON patterns(owner_id, skill);
CREATE INDEX idx_patterns_contact ON patterns(owner_id, contact_id);

ALTER TABLE patterns ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own patterns" ON patterns
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 7. MEMORIES TABLE
-- ============================================
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    namespace TEXT NOT NULL,
    category TEXT NOT NULL,
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

ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own memories" ON memories
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 8. AVATARS TABLE
-- ============================================
CREATE TABLE avatars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    contact_id TEXT NOT NULL,
    display_name TEXT,
    identifiers JSONB,
    preferred_channel TEXT,
    preferred_tone TEXT,
    preferred_language TEXT,
    response_latency JSONB,
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

ALTER TABLE avatars ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own avatars" ON avatars
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 9. IDENTIFIER MAP TABLE
-- ============================================
CREATE TABLE identifier_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    identifier TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, identifier)
);

CREATE INDEX idx_identifier_owner ON identifier_map(owner_id);
CREATE INDEX idx_identifier_lookup ON identifier_map(owner_id, identifier);

ALTER TABLE identifier_map ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own identifiers" ON identifier_map
    FOR ALL USING (owner_id = auth.uid());

-- ============================================
-- 10. OAUTH TOKENS TABLE
-- Stores encrypted OAuth tokens for Google/Microsoft
-- ============================================
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL,
    provider TEXT NOT NULL,  -- 'google.com' or 'microsoft.com'
    email TEXT NOT NULL,
    -- Google OAuth tokens (pickled Credentials object, base64 encoded)
    google_token_data TEXT,
    -- Microsoft Graph tokens
    graph_access_token TEXT,
    graph_refresh_token TEXT,
    graph_expires_at TIMESTAMPTZ,
    -- Anthropic API key (user-provided for BYOK model)
    anthropic_api_key TEXT,
    -- Metadata
    scopes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, provider)
);

CREATE INDEX idx_oauth_owner ON oauth_tokens(owner_id);

ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users access own oauth_tokens" ON oauth_tokens
    FOR ALL USING (owner_id = auth.uid());

-- Service role policy for backend access
CREATE POLICY "Service role full access to oauth_tokens" ON oauth_tokens
    FOR ALL USING (true)
    WITH CHECK (true);

-- ============================================
-- DONE!
-- ============================================
