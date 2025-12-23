-- Migration: Add hybrid search (FTS + semantic + exact pattern) support for emails
-- Run via Supabase SQL Editor

-- 1. Add embedding column for semantic search
ALTER TABLE emails ADD COLUMN IF NOT EXISTS embedding vector(384);

-- 2. Add tsvector for FTS with 'simple' language config (language-agnostic)
-- Note: We need to drop and recreate if switching from 'english' to 'simple'
DO $$
BEGIN
    -- Check if column exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'emails' AND column_name = 'tsv'
    ) THEN
        ALTER TABLE emails ADD COLUMN tsv TSVECTOR
            GENERATED ALWAYS AS (
                to_tsvector('simple', COALESCE(subject, '') || ' ' || COALESCE(body_plain, ''))
            ) STORED;
    END IF;
END $$;

-- 3. Create indices for efficient search
CREATE INDEX IF NOT EXISTS emails_embedding_idx ON emails
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS emails_tsv_idx ON emails USING gin(tsv);

-- 4. Create hybrid search function for emails
-- Combines: FTS (language-agnostic) + semantic (embedding similarity) + exact pattern (ILIKE on headers)
CREATE OR REPLACE FUNCTION hybrid_search_emails(
    p_owner_id TEXT,
    p_query TEXT,
    p_query_embedding VECTOR(384),
    p_fts_weight FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 20,
    p_exact_pattern TEXT DEFAULT NULL  -- For email address ILIKE matching
)
RETURNS TABLE (
    email_id UUID,
    gmail_id TEXT,
    thread_id TEXT,
    subject TEXT,
    from_email TEXT,
    from_name TEXT,
    to_emails JSONB,
    date_timestamp BIGINT,
    body_plain TEXT,
    snippet TEXT,
    fts_score FLOAT,
    semantic_score FLOAT,
    exact_score FLOAT,
    hybrid_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id AS email_id,
        e.gmail_id,
        e.thread_id,
        e.subject,
        e.from_email,
        e.from_name,
        e.to_emails,
        e.date_timestamp,
        e.body_plain,
        e.snippet,
        -- FTS score using 'simple' config (language-agnostic)
        COALESCE(ts_rank(e.tsv, plainto_tsquery('simple', p_query)), 0)::FLOAT AS fts_score,
        -- Semantic score from embedding similarity
        CASE
            WHEN e.embedding IS NOT NULL
            THEN (1 - (e.embedding <=> p_query_embedding))::FLOAT
            ELSE 0::FLOAT
        END AS semantic_score,
        -- Exact match on from_email or to_emails (header fields)
        CASE
            WHEN p_exact_pattern IS NOT NULL AND (
                e.from_email ILIKE '%' || p_exact_pattern || '%' OR
                e.to_emails::TEXT ILIKE '%' || p_exact_pattern || '%'
            )
            THEN 1.0::FLOAT
            ELSE 0.0::FLOAT
        END AS exact_score,
        -- Hybrid score calculation
        CASE
            WHEN p_exact_pattern IS NOT NULL AND (
                e.from_email ILIKE '%' || p_exact_pattern || '%' OR
                e.to_emails::TEXT ILIKE '%' || p_exact_pattern || '%'
            )
            THEN (0.8 + 0.1 * COALESCE(ts_rank(e.tsv, plainto_tsquery('simple', p_query)), 0) +
                  0.1 * CASE WHEN e.embedding IS NOT NULL THEN (1 - (e.embedding <=> p_query_embedding)) ELSE 0 END)::FLOAT
            ELSE (p_fts_weight * COALESCE(ts_rank(e.tsv, plainto_tsquery('simple', p_query)), 0) +
                  (1 - p_fts_weight) * CASE WHEN e.embedding IS NOT NULL THEN (1 - (e.embedding <=> p_query_embedding)) ELSE 0 END)::FLOAT
        END AS hybrid_score
    FROM emails e
    WHERE e.owner_id = p_owner_id
    ORDER BY hybrid_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 5. Grant execute permission to authenticated users
GRANT EXECUTE ON FUNCTION hybrid_search_emails TO authenticated;
