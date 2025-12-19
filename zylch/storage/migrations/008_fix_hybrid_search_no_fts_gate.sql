-- Migration: Remove FTS hard gate from hybrid_search_blobs
--
-- Problem: The original function required FTS to match before semantic search was tried.
-- This caused reconsolidation to fail when entity descriptions differed (even with same email).
--
-- Fix: Get ALL blobs for owner/namespace, compute both FTS and semantic scores, combine.

CREATE OR REPLACE FUNCTION hybrid_search_blobs(
    p_owner_id TEXT,
    p_query TEXT,
    p_query_embedding VECTOR(384),
    p_namespace TEXT DEFAULT NULL,
    p_fts_weight FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 10
)
RETURNS TABLE (
    blob_id UUID,
    content TEXT,
    namespace TEXT,
    fts_score FLOAT,
    semantic_score FLOAT,
    hybrid_score FLOAT,
    events JSONB
) AS $$
BEGIN
    RETURN QUERY
    WITH all_blobs AS (
        -- Get ALL blobs for this owner/namespace (no FTS filter)
        SELECT
            b.id,
            b.content,
            b.namespace,
            b.events,
            ts_rank(b.tsv, plainto_tsquery('english', p_query)) AS fts_score
        FROM blobs b
        WHERE b.owner_id = p_owner_id
          AND (p_namespace IS NULL OR b.namespace = p_namespace)
    ),
    semantic_results AS (
        -- Compute semantic score for ALL blobs (not just FTS matches)
        SELECT
            bs.blob_id,
            MAX(1 - (bs.embedding <=> p_query_embedding)) AS max_semantic_score
        FROM blob_sentences bs
        WHERE bs.owner_id = p_owner_id
        GROUP BY bs.blob_id
    )
    SELECT
        a.id AS blob_id,
        a.content,
        a.namespace,
        COALESCE(a.fts_score, 0)::FLOAT AS fts_score,
        COALESCE(s.max_semantic_score, 0)::FLOAT AS semantic_score,
        (p_fts_weight * COALESCE(a.fts_score, 0) +
         (1 - p_fts_weight) * COALESCE(s.max_semantic_score, 0))::FLOAT AS hybrid_score,
        a.events
    FROM all_blobs a
    LEFT JOIN semantic_results s ON a.id = s.blob_id
    ORDER BY hybrid_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
