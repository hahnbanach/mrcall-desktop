-- Migration: Add exact pattern matching on #IDENTIFIERS section to hybrid search
-- This adds a third scoring component for exact matches (email, phone, URL)
-- that only looks at the #IDENTIFIERS section of blob content.

CREATE OR REPLACE FUNCTION hybrid_search_blobs(
    p_owner_id TEXT,
    p_query TEXT,
    p_query_embedding VECTOR(384),
    p_namespace TEXT DEFAULT NULL,
    p_fts_weight FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 10,
    p_exact_pattern TEXT DEFAULT NULL  -- Pattern for ILIKE matching on #IDENTIFIERS
)
RETURNS TABLE (
    blob_id UUID,
    content TEXT,
    namespace TEXT,
    fts_score FLOAT,
    semantic_score FLOAT,
    exact_score FLOAT,
    hybrid_score FLOAT,
    events JSONB
) AS $$
BEGIN
    RETURN QUERY
    WITH all_blobs AS (
        SELECT
            b.id,
            b.content,
            b.namespace,
            b.events,
            ts_rank(b.tsv, plainto_tsquery('english', p_query)) AS fts_score,
            -- Exact pattern match on #IDENTIFIERS section only
            CASE
                WHEN p_exact_pattern IS NOT NULL
                     AND substring(b.content FROM '#IDENTIFIERS(.*?)#ABOUT')
                         ILIKE '%' || p_exact_pattern || '%'
                THEN 1.0
                ELSE 0.0
            END AS exact_score
        FROM blobs b
        WHERE b.owner_id = p_owner_id
          AND (p_namespace IS NULL OR b.namespace = p_namespace)
    ),
    semantic_results AS (
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
        a.exact_score::FLOAT AS exact_score,
        -- Hybrid score with exact match boost
        CASE
            WHEN a.exact_score > 0 THEN
                (0.8 * a.exact_score +
                 0.1 * COALESCE(a.fts_score, 0) +
                 0.1 * COALESCE(s.max_semantic_score, 0))::FLOAT
            ELSE
                (p_fts_weight * COALESCE(a.fts_score, 0) +
                 (1 - p_fts_weight) * COALESCE(s.max_semantic_score, 0))::FLOAT
        END AS hybrid_score,
        a.events
    FROM all_blobs a
    LEFT JOIN semantic_results s ON a.id = s.blob_id
    ORDER BY hybrid_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
