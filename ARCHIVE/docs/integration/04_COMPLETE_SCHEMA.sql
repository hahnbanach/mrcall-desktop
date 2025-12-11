-- ============================================
-- ZYLCH AVATAR SYSTEM - COMPLETE DATABASE SCHEMA
-- For virgin Supabase database setup
-- Version: 1.0.0
-- Date: 2025-12-08
-- ============================================
-- CRITICAL: owner_id is TEXT (Firebase UID), NOT UUID
-- This schema includes ALL tables needed for the Zylch system
-- ============================================

-- ============================================
-- EXTENSIONS
-- ============================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- TABLE DEFINITIONS
-- ============================================

-- ============================================
-- 1. EMAILS TABLE (Email Archive)
-- ============================================
CREATE TABLE emails (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
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

-- Full-text search column
ALTER TABLE emails ADD COLUMN fts_document tsvector
    GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(subject, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(body_plain, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(from_email, '')), 'C')
    ) STORED;

COMMENT ON TABLE emails IS 'Email archive storage with full-text search';
COMMENT ON COLUMN emails.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 2. SYNC STATE TABLE
-- ============================================
CREATE TABLE sync_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL UNIQUE,
    history_id TEXT,
    last_sync TIMESTAMPTZ,
    full_sync_completed TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE sync_state IS 'Gmail sync state tracking per user';
COMMENT ON COLUMN sync_state.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 3. THREAD ANALYSIS TABLE (Intelligence Cache)
-- ============================================
CREATE TABLE thread_analysis (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
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

COMMENT ON TABLE thread_analysis IS 'Cached AI analysis of email threads';
COMMENT ON COLUMN thread_analysis.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 4. RELATIONSHIP GAPS TABLE
-- ============================================
CREATE TABLE relationship_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    gap_type TEXT NOT NULL,
    contact_email TEXT,
    contact_name TEXT,
    details JSONB,
    priority INTEGER,
    suggested_action TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

COMMENT ON TABLE relationship_gaps IS 'Detected relationship maintenance gaps';
COMMENT ON COLUMN relationship_gaps.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 5. CALENDAR EVENTS TABLE
-- ============================================
CREATE TABLE calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
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

COMMENT ON TABLE calendar_events IS 'Calendar events for relationship context';
COMMENT ON COLUMN calendar_events.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 6. PATTERNS TABLE (ZylchMemory)
-- ============================================
CREATE TABLE patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
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

COMMENT ON TABLE patterns IS 'Learned behavioral patterns for AI personalization';
COMMENT ON COLUMN patterns.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 7. MEMORIES TABLE
-- ============================================
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
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

COMMENT ON TABLE memories IS 'Long-term memory patterns and context';
COMMENT ON COLUMN memories.owner_id IS 'Firebase UID (TEXT, not UUID)';

-- ============================================
-- 8. AVATARS TABLE (Contact Profiles)
-- ============================================
CREATE TABLE avatars (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
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
    -- Avatar Intelligence Fields (from migration)
    relationship_summary TEXT,
    relationship_status TEXT DEFAULT 'unknown',
    relationship_score INTEGER DEFAULT 5,
    suggested_action TEXT,
    interaction_summary JSONB DEFAULT '{}'::jsonb,
    profile_embedding vector(384),
    last_computed TIMESTAMPTZ,
    compute_trigger TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, contact_id)
);

COMMENT ON TABLE avatars IS 'Contact profiles with behavioral preferences and AI-computed relationship intelligence';
COMMENT ON COLUMN avatars.owner_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN avatars.relationship_summary IS 'LLM-generated narrative of relationship context (replaces per-request LLM calls)';
COMMENT ON COLUMN avatars.relationship_status IS 'Current conversation state: open (needs action), waiting (waiting for them), closed';
COMMENT ON COLUMN avatars.relationship_score IS 'Priority score 1-10 for task ranking';
COMMENT ON COLUMN avatars.suggested_action IS 'Next step recommendation from LLM';
COMMENT ON COLUMN avatars.profile_embedding IS '384-dimensional vector for semantic search on relationship summaries';
COMMENT ON COLUMN avatars.last_computed IS 'Timestamp of last avatar recomputation (for staleness detection)';
COMMENT ON COLUMN avatars.compute_trigger IS 'What triggered last computation: new_email, scheduled, manual';

-- ============================================
-- 9. IDENTIFIER MAP TABLE (Multi-identifier person resolution)
-- ============================================
CREATE TABLE identifier_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    identifier TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, identifier)
);

COMMENT ON TABLE identifier_map IS 'Maps multiple identifiers (emails, phones) to a single contact_id for person resolution';
COMMENT ON COLUMN identifier_map.owner_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN identifier_map.identifier_type IS 'email, phone, or name';
COMMENT ON COLUMN identifier_map.source IS 'manual, email_from, calendar_attendee';

-- ============================================
-- 10. AVATAR COMPUTE QUEUE TABLE (Background job processing)
-- ============================================
CREATE TABLE avatar_compute_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    retry_count INTEGER DEFAULT 0,
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(owner_id, contact_id)
);

COMMENT ON TABLE avatar_compute_queue IS 'Queue for background avatar computation jobs, processed by Railway cron worker';
COMMENT ON COLUMN avatar_compute_queue.owner_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN avatar_compute_queue.trigger_type IS 'new_email, scheduled, manual, backfill';
COMMENT ON COLUMN avatar_compute_queue.priority IS '1-10 (higher = more urgent)';

-- ============================================
-- 11. OAUTH TOKENS TABLE (Encrypted OAuth tokens)
-- ============================================
CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    provider TEXT NOT NULL,
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

COMMENT ON TABLE oauth_tokens IS 'Encrypted OAuth tokens for Google/Microsoft/Anthropic';
COMMENT ON COLUMN oauth_tokens.owner_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN oauth_tokens.provider IS 'google.com, microsoft.com, anthropic, mrcall';

-- ============================================
-- 12. TRIGGERS TABLE (Event-driven automation)
-- ============================================
CREATE TABLE triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('session_start', 'email_received', 'sms_received', 'call_received')),
    instruction TEXT NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE triggers IS 'Event-driven automation triggers for Zylch users';
COMMENT ON COLUMN triggers.owner_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN triggers.trigger_type IS 'session_start, email_received, sms_received, call_received';
COMMENT ON COLUMN triggers.instruction IS 'Natural language instruction to execute when trigger fires';

-- ============================================
-- 13. TRIGGER EVENTS TABLE (Background job queue)
-- ============================================
CREATE TABLE trigger_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('email_received', 'sms_received', 'call_received')),
    event_data JSONB NOT NULL DEFAULT '{}',
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    trigger_id UUID REFERENCES triggers(id),
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER DEFAULT 0,
    last_error TEXT
);

COMMENT ON TABLE trigger_events IS 'Queue for background trigger execution';
COMMENT ON COLUMN trigger_events.owner_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN trigger_events.event_type IS 'email_received, sms_received, call_received';
COMMENT ON COLUMN trigger_events.status IS 'pending (waiting), processing (being handled), completed (done), failed (error)';
COMMENT ON COLUMN trigger_events.event_data IS 'JSON payload with event details (from, subject, body, etc.)';

-- ============================================
-- 14. SHARING AUTH TABLE (Data sharing between users)
-- ============================================
CREATE TABLE sharing_auth (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sender_id TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    recipient_email TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'authorized', 'revoked')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    authorized_at TIMESTAMPTZ,
    UNIQUE(sender_id, recipient_email)
);

COMMENT ON TABLE sharing_auth IS 'Sharing authorization between Zylch users';
COMMENT ON COLUMN sharing_auth.sender_id IS 'Firebase UID (TEXT, not UUID)';
COMMENT ON COLUMN sharing_auth.status IS 'pending (awaiting acceptance), authorized (accepted), revoked (cancelled)';

-- ============================================
-- INDICES
-- ============================================

-- Emails indices
CREATE INDEX idx_emails_owner ON emails(owner_id);
CREATE INDEX idx_emails_thread ON emails(owner_id, thread_id);
CREATE INDEX idx_emails_date ON emails(owner_id, date_timestamp DESC);
CREATE INDEX idx_emails_from ON emails(owner_id, from_email);
CREATE INDEX idx_emails_fts ON emails USING GIN(fts_document);

-- Thread analysis indices
CREATE INDEX idx_thread_analysis_owner ON thread_analysis(owner_id);
CREATE INDEX idx_thread_analysis_contact ON thread_analysis(owner_id, contact_email);
CREATE INDEX idx_thread_analysis_action ON thread_analysis(owner_id, needs_action) WHERE needs_action = TRUE;

-- Relationship gaps indices
CREATE INDEX idx_gaps_owner ON relationship_gaps(owner_id);
CREATE INDEX idx_gaps_unresolved ON relationship_gaps(owner_id, resolved_at) WHERE resolved_at IS NULL;

-- Calendar events indices
CREATE INDEX idx_calendar_owner ON calendar_events(owner_id);
CREATE INDEX idx_calendar_time ON calendar_events(owner_id, start_time);

-- Patterns indices
CREATE INDEX idx_patterns_owner ON patterns(owner_id);
CREATE INDEX idx_patterns_namespace ON patterns(owner_id, namespace);
CREATE INDEX idx_patterns_skill ON patterns(owner_id, skill);
CREATE INDEX idx_patterns_contact ON patterns(owner_id, contact_id);

-- Memories indices
CREATE INDEX idx_memories_owner ON memories(owner_id);
CREATE INDEX idx_memories_namespace ON memories(owner_id, namespace);
CREATE INDEX idx_memories_category ON memories(owner_id, category);

-- Avatars indices
CREATE INDEX idx_avatars_owner ON avatars(owner_id);
CREATE INDEX idx_avatars_contact ON avatars(owner_id, contact_id);
CREATE INDEX idx_avatars_status ON avatars(owner_id, relationship_status);
CREATE INDEX idx_avatars_score ON avatars(owner_id, relationship_score DESC);
CREATE INDEX idx_avatars_last_computed ON avatars(last_computed);

-- Vector similarity search index (only create if avatars table has data)
-- Note: Run this manually after populating data:
-- CREATE INDEX idx_avatars_embedding ON avatars
--     USING ivfflat (profile_embedding vector_cosine_ops)
--     WITH (lists = 100);

-- Identifier map indices
CREATE INDEX idx_identifier_owner ON identifier_map(owner_id);
CREATE INDEX idx_identifier_lookup ON identifier_map(owner_id, identifier);
CREATE INDEX idx_identifier_map_contact ON identifier_map(owner_id, contact_id);

-- Avatar compute queue indices
CREATE INDEX idx_queue_scheduled ON avatar_compute_queue(scheduled_at);
CREATE INDEX idx_queue_priority ON avatar_compute_queue(owner_id, priority DESC, scheduled_at ASC);

-- OAuth tokens index
CREATE INDEX idx_oauth_owner ON oauth_tokens(owner_id);

-- Triggers indices
CREATE INDEX idx_triggers_owner ON triggers(owner_id);
CREATE INDEX idx_triggers_active_type ON triggers(owner_id, trigger_type) WHERE active = TRUE;

-- Trigger events indices
CREATE INDEX idx_trigger_events_pending ON trigger_events(status, created_at) WHERE status = 'pending';
CREATE INDEX idx_trigger_events_owner ON trigger_events(owner_id, created_at DESC);
CREATE INDEX idx_trigger_events_status ON trigger_events(status);

-- Sharing auth indices
CREATE INDEX idx_sharing_sender ON sharing_auth(sender_id);
CREATE INDEX idx_sharing_recipient ON sharing_auth(recipient_email);
CREATE INDEX idx_sharing_status ON sharing_auth(status);

-- ============================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================

-- Enable RLS on all tables
ALTER TABLE emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE thread_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE relationship_gaps ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE patterns ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE avatars ENABLE ROW LEVEL SECURITY;
ALTER TABLE identifier_map ENABLE ROW LEVEL SECURITY;
ALTER TABLE avatar_compute_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE trigger_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE sharing_auth ENABLE ROW LEVEL SECURITY;

-- RLS Policies for emails
CREATE POLICY emails_isolation ON emails
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for sync_state
CREATE POLICY sync_state_isolation ON sync_state
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for thread_analysis
CREATE POLICY thread_analysis_isolation ON thread_analysis
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for relationship_gaps
CREATE POLICY relationship_gaps_isolation ON relationship_gaps
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for calendar_events
CREATE POLICY calendar_events_isolation ON calendar_events
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for patterns
CREATE POLICY patterns_isolation ON patterns
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for memories
CREATE POLICY memories_isolation ON memories
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for avatars
CREATE POLICY avatars_isolation ON avatars
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for identifier_map
CREATE POLICY identifier_map_isolation ON identifier_map
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for avatar_compute_queue
CREATE POLICY avatar_compute_queue_isolation ON avatar_compute_queue
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- RLS Policies for oauth_tokens
CREATE POLICY oauth_tokens_isolation ON oauth_tokens
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- Service role full access to oauth_tokens
CREATE POLICY oauth_tokens_service_role ON oauth_tokens
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- RLS Policies for triggers
CREATE POLICY triggers_isolation ON triggers
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', true))
    WITH CHECK (owner_id = current_setting('app.current_user_id', true));

-- Service role full access to triggers
CREATE POLICY triggers_service_role ON triggers
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- RLS Policies for trigger_events
CREATE POLICY trigger_events_select ON trigger_events
    FOR SELECT
    USING (owner_id = current_setting('app.current_user_id', true));

-- Service role full access to trigger_events
CREATE POLICY trigger_events_service_role ON trigger_events
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- RLS Policies for sharing_auth
CREATE POLICY sharing_auth_sender_select ON sharing_auth
    FOR SELECT
    USING (sender_id = current_setting('app.current_user_id', true));

-- Recipients can see shares sent to them (requires email comparison)
-- Note: This requires app.current_user_email to be set in addition to app.current_user_id
CREATE POLICY sharing_auth_recipient_select ON sharing_auth
    FOR SELECT
    USING (recipient_email = current_setting('app.current_user_email', true));

CREATE POLICY sharing_auth_sender_insert ON sharing_auth
    FOR INSERT
    WITH CHECK (sender_id = current_setting('app.current_user_id', true));

CREATE POLICY sharing_auth_sender_update ON sharing_auth
    FOR UPDATE
    USING (sender_id = current_setting('app.current_user_id', true));

CREATE POLICY sharing_auth_recipient_update ON sharing_auth
    FOR UPDATE
    USING (recipient_email = current_setting('app.current_user_email', true));

-- Service role full access to sharing_auth
CREATE POLICY sharing_auth_service_role ON sharing_auth
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Function to queue avatar computation (idempotent)
CREATE OR REPLACE FUNCTION queue_avatar_compute(
    p_owner_id TEXT,
    p_contact_id TEXT,
    p_trigger_type TEXT DEFAULT 'manual',
    p_priority INTEGER DEFAULT 5
)
RETURNS UUID AS $$
DECLARE
    v_queue_id UUID;
BEGIN
    INSERT INTO avatar_compute_queue (owner_id, contact_id, trigger_type, priority)
    VALUES (p_owner_id, p_contact_id, p_trigger_type, p_priority)
    ON CONFLICT (owner_id, contact_id)
    DO UPDATE SET
        priority = GREATEST(avatar_compute_queue.priority, EXCLUDED.priority),
        scheduled_at = NOW(),
        trigger_type = EXCLUDED.trigger_type
    RETURNING id INTO v_queue_id;

    RETURN v_queue_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get contacts needing avatar updates
CREATE OR REPLACE FUNCTION get_stale_avatars(
    p_owner_id TEXT,
    p_hours_threshold INTEGER DEFAULT 24
)
RETURNS TABLE(contact_id TEXT, hours_since_update NUMERIC) AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.contact_id,
        EXTRACT(EPOCH FROM (NOW() - a.last_computed)) / 3600 AS hours_since_update
    FROM avatars a
    WHERE a.owner_id = p_owner_id
      AND (
          a.last_computed IS NULL
          OR (
              (a.relationship_score >= 8 AND EXTRACT(EPOCH FROM (NOW() - a.last_computed)) / 3600 >= 12)
              OR (a.relationship_score >= 5 AND EXTRACT(EPOCH FROM (NOW() - a.last_computed)) / 3600 >= 24)
              OR (EXTRACT(EPOCH FROM (NOW() - a.last_computed)) / 3600 >= 168)
          )
      )
    ORDER BY a.relationship_score DESC, a.last_computed ASC NULLS FIRST;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function for email full-text search
CREATE OR REPLACE FUNCTION search_emails(
    search_query TEXT,
    user_id TEXT,
    result_limit INT DEFAULT 100
)
RETURNS SETOF emails AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM emails
    WHERE owner_id = user_id
      AND fts_document @@ plainto_tsquery('english', search_query)
    ORDER BY ts_rank(fts_document, plainto_tsquery('english', search_query)) DESC
    LIMIT result_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================
-- VERIFICATION
-- ============================================

DO $$
DECLARE
    v_table_count INTEGER;
    v_index_count INTEGER;
    v_policy_count INTEGER;
BEGIN
    -- Count tables
    SELECT COUNT(*) INTO v_table_count
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
          'emails', 'sync_state', 'thread_analysis', 'relationship_gaps',
          'calendar_events', 'patterns', 'memories', 'avatars',
          'identifier_map', 'avatar_compute_queue', 'oauth_tokens',
          'triggers', 'trigger_events', 'sharing_auth'
      );

    -- Count indices
    SELECT COUNT(*) INTO v_index_count
    FROM pg_indexes
    WHERE schemaname = 'public';

    -- Count RLS policies
    SELECT COUNT(*) INTO v_policy_count
    FROM pg_policies
    WHERE schemaname = 'public';

    RAISE NOTICE '=== Schema Installation Verification ===';
    RAISE NOTICE 'Tables created: % of 14', v_table_count;
    RAISE NOTICE 'Indices created: %', v_index_count;
    RAISE NOTICE 'RLS policies created: %', v_policy_count;

    IF v_table_count = 14 THEN
        RAISE NOTICE '✓ All tables created successfully!';
    ELSE
        RAISE WARNING 'Missing tables - expected 14, found %', v_table_count;
    END IF;
END $$;

-- ============================================
-- USAGE NOTES
-- ============================================

-- 1. RLS Configuration:
--    Set these runtime settings in your application:
--    SET app.current_user_id = '<firebase_uid>';
--    SET app.current_user_email = '<user_email>';
--
-- 2. Vector Index:
--    The avatar embedding index should be created AFTER populating data:
--    CREATE INDEX idx_avatars_embedding ON avatars
--        USING ivfflat (profile_embedding vector_cosine_ops)
--        WITH (lists = 100);
--
-- 3. Service Role:
--    Service role key bypasses RLS - use for backend operations only
--
-- 4. Owner ID Format:
--    ALL owner_id columns are TEXT (Firebase UID), NOT UUID
--
-- 5. Migration from old schema:
--    If migrating from UUID owner_id to TEXT, run:
--    ALTER TABLE <table> ALTER COLUMN owner_id TYPE TEXT;
