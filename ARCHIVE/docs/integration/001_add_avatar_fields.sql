-- Migration: Add Avatar-Based Relational Memory Infrastructure (v3 - TEXT owner_id)
-- Date: 2025-12-08
-- Purpose: Enable pre-computed person representations for instant task retrieval
-- Fixed: owner_id is TEXT, not UUID

-- ============================================================================
-- STEP 1: Enable pg_vector extension
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- STEP 2: Check and add columns to avatars table
-- ============================================================================

-- Add relationship intelligence fields (only if they don't exist)
DO $$
BEGIN
    -- relationship_summary
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='relationship_summary') THEN
        ALTER TABLE avatars ADD COLUMN relationship_summary TEXT;
    END IF;

    -- relationship_status
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='relationship_status') THEN
        ALTER TABLE avatars ADD COLUMN relationship_status TEXT DEFAULT 'unknown';
    END IF;

    -- relationship_score
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='relationship_score') THEN
        ALTER TABLE avatars ADD COLUMN relationship_score INTEGER DEFAULT 5;
    END IF;

    -- suggested_action
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='suggested_action') THEN
        ALTER TABLE avatars ADD COLUMN suggested_action TEXT;
    END IF;

    -- interaction_summary
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='interaction_summary') THEN
        ALTER TABLE avatars ADD COLUMN interaction_summary JSONB DEFAULT '{}'::jsonb;
    END IF;

    -- profile_embedding
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='profile_embedding') THEN
        ALTER TABLE avatars ADD COLUMN profile_embedding vector(384);
    END IF;

    -- last_computed
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='last_computed') THEN
        ALTER TABLE avatars ADD COLUMN last_computed TIMESTAMPTZ;
    END IF;

    -- compute_trigger
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='avatars' AND column_name='compute_trigger') THEN
        ALTER TABLE avatars ADD COLUMN compute_trigger TEXT;
    END IF;
END $$;

-- ============================================================================
-- STEP 3: Add indices for performance
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_avatars_status ON avatars(owner_id, relationship_status);
CREATE INDEX IF NOT EXISTS idx_avatars_score ON avatars(owner_id, relationship_score DESC);
CREATE INDEX IF NOT EXISTS idx_avatars_last_computed ON avatars(last_computed);

-- Vector similarity search index (ivfflat for pg_vector)
-- Only create if there are rows (empty tables cause ivfflat to fail)
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM avatars) > 0 THEN
        CREATE INDEX IF NOT EXISTS idx_avatars_embedding ON avatars
            USING ivfflat (profile_embedding vector_cosine_ops)
            WITH (lists = 100);
    ELSE
        RAISE NOTICE 'Skipping vector index creation - avatars table is empty';
    END IF;
END $$;

-- ============================================================================
-- STEP 4: Create identifier_map table (Multi-identifier person resolution)
-- ============================================================================

CREATE TABLE IF NOT EXISTS identifier_map (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,                   -- Firebase UID (TEXT, not UUID)
    identifier TEXT NOT NULL,                 -- Normalized email/phone/name
    identifier_type TEXT NOT NULL,            -- 'email', 'phone', 'name'
    contact_id TEXT NOT NULL,                 -- Links to avatars.contact_id
    confidence REAL DEFAULT 1.0,              -- Merging confidence (for fuzzy matching)
    source TEXT,                              -- "manual", "email_from", "calendar_attendee"
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, identifier)
);

-- Indices for fast lookups
CREATE INDEX IF NOT EXISTS idx_identifier_map_lookup ON identifier_map(owner_id, identifier);
CREATE INDEX IF NOT EXISTS idx_identifier_map_contact ON identifier_map(owner_id, contact_id);

-- Enable RLS
ALTER TABLE identifier_map ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only access their own identifiers
DROP POLICY IF EXISTS "Users can only access own identifiers" ON identifier_map;
CREATE POLICY "Users can only access own identifiers" ON identifier_map
    FOR ALL
    USING (owner_id = current_setting('request.jwt.claims', true)::json->>'sub')
    WITH CHECK (owner_id = current_setting('request.jwt.claims', true)::json->>'sub');

-- ============================================================================
-- STEP 5: Create avatar_compute_queue table (Background job processing)
-- ============================================================================

CREATE TABLE IF NOT EXISTS avatar_compute_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,                   -- Firebase UID (TEXT, not UUID)
    contact_id TEXT NOT NULL,
    trigger_type TEXT NOT NULL,               -- "new_email", "scheduled", "manual", "backfill"
    priority INTEGER DEFAULT 5,                -- 1-10 (higher = more urgent)
    retry_count INTEGER DEFAULT 0,
    scheduled_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(owner_id, contact_id)              -- Prevent duplicate queue entries
);

-- Index for efficient queue processing (without WHERE clause to avoid immutability issue)
CREATE INDEX IF NOT EXISTS idx_queue_scheduled ON avatar_compute_queue(scheduled_at);

CREATE INDEX IF NOT EXISTS idx_queue_priority ON avatar_compute_queue(owner_id, priority DESC, scheduled_at ASC);

-- Enable RLS
ALTER TABLE avatar_compute_queue ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only access their own queue items
DROP POLICY IF EXISTS "Users can only access own queue items" ON avatar_compute_queue;
CREATE POLICY "Users can only access own queue items" ON avatar_compute_queue
    FOR ALL
    USING (owner_id = current_setting('request.jwt.claims', true)::json->>'sub')
    WITH CHECK (owner_id = current_setting('request.jwt.claims', true)::json->>'sub');

-- ============================================================================
-- STEP 6: Helper functions
-- ============================================================================

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
    -- Insert or update queue entry
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

-- ============================================================================
-- STEP 7: Add comments for documentation
-- ============================================================================

COMMENT ON TABLE identifier_map IS 'Maps multiple identifiers (emails, phones) to a single contact_id for person resolution';
COMMENT ON TABLE avatar_compute_queue IS 'Queue for background avatar computation jobs, processed by Railway cron worker';

COMMENT ON COLUMN avatars.relationship_summary IS 'LLM-generated narrative of relationship context (replaces per-request LLM calls)';
COMMENT ON COLUMN avatars.relationship_status IS 'Current conversation state: open (needs action), waiting (waiting for them), closed';
COMMENT ON COLUMN avatars.relationship_score IS 'Priority score 1-10 for task ranking';
COMMENT ON COLUMN avatars.suggested_action IS 'Next step recommendation from LLM';
COMMENT ON COLUMN avatars.profile_embedding IS '384-dimensional vector for semantic search on relationship summaries';
COMMENT ON COLUMN avatars.last_computed IS 'Timestamp of last avatar recomputation (for staleness detection)';
COMMENT ON COLUMN avatars.compute_trigger IS 'What triggered last computation: new_email, scheduled, manual';

-- ============================================================================
-- STEP 8: Verify migration
-- ============================================================================

DO $$
DECLARE
    v_avatar_columns INTEGER;
    v_identifier_map_exists BOOLEAN;
    v_queue_exists BOOLEAN;
BEGIN
    -- Count new avatar columns
    SELECT COUNT(*) INTO v_avatar_columns
    FROM information_schema.columns
    WHERE table_name = 'avatars'
      AND column_name IN ('relationship_summary', 'relationship_status', 'relationship_score',
                          'suggested_action', 'profile_embedding', 'last_computed');

    -- Check table existence
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'identifier_map') INTO v_identifier_map_exists;
    SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'avatar_compute_queue') INTO v_queue_exists;

    RAISE NOTICE '=== Migration Verification ===';
    RAISE NOTICE 'Avatar columns added: % of 6', v_avatar_columns;
    RAISE NOTICE 'identifier_map table: %', CASE WHEN v_identifier_map_exists THEN 'EXISTS' ELSE 'MISSING' END;
    RAISE NOTICE 'avatar_compute_queue table: %', CASE WHEN v_queue_exists THEN 'EXISTS' ELSE 'MISSING' END;

    IF v_avatar_columns = 6 AND v_identifier_map_exists AND v_queue_exists THEN
        RAISE NOTICE '✓ Migration successful!';
    ELSE
        RAISE WARNING 'Migration incomplete - check logs';
    END IF;
END $$;
