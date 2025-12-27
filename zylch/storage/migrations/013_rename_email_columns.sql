-- Migration: Rename to_emails -> to_email and cc_emails -> cc_email
-- Run via Supabase SQL Editor

-- Rename columns
ALTER TABLE emails RENAME COLUMN to_emails TO to_email;
ALTER TABLE emails RENAME COLUMN cc_emails TO cc_email;

-- Update the hybrid_search_emails function to use new column names
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
    to_email JSONB,
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
        e.to_email,
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
        -- Exact match on from_email or to_email (header fields)
        CASE
            WHEN p_exact_pattern IS NOT NULL AND (
                e.from_email ILIKE '%' || p_exact_pattern || '%' OR
                e.to_email::TEXT ILIKE '%' || p_exact_pattern || '%'
            )
            THEN 1.0::FLOAT
            ELSE 0.0::FLOAT
        END AS exact_score,
        -- Hybrid score calculation
        CASE
            WHEN p_exact_pattern IS NOT NULL AND (
                e.from_email ILIKE '%' || p_exact_pattern || '%' OR
                e.to_email::TEXT ILIKE '%' || p_exact_pattern || '%'
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
