-- Migration: FTS on #IDENTIFIERS section only with simple (language-agnostic) config
-- This fixes reconsolidation ranking where wrong blobs matched due to content in #ABOUT

-- 1. Helper function to extract #IDENTIFIERS section
CREATE OR REPLACE FUNCTION extract_identifiers(content TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN COALESCE(
        substring(content FROM '#IDENTIFIERS(.*?)#ABOUT'),
        ''
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 2. Drop old tsv column and index
DROP INDEX IF EXISTS idx_blobs_tsv;
ALTER TABLE blobs DROP COLUMN IF EXISTS tsv;

-- 3. Add new tsv column with simple config on #IDENTIFIERS only
ALTER TABLE blobs ADD COLUMN tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('simple', extract_identifiers(content))) STORED;

-- 4. Recreate GIN index
CREATE INDEX idx_blobs_tsv ON blobs USING GIN(tsv);

-- 5. Drop old function signature to avoid ambiguity
DROP FUNCTION IF EXISTS hybrid_search_blobs(TEXT, TEXT, VECTOR(384), TEXT, FLOAT, INT);

-- 6. Update search function to use simple config
CREATE OR REPLACE FUNCTION hybrid_search_blobs(
    p_owner_id TEXT,
    p_query TEXT,
    p_query_embedding VECTOR(384),
    p_namespace TEXT DEFAULT NULL,
    p_fts_weight FLOAT DEFAULT 0.5,
    p_limit INT DEFAULT 10,
    p_exact_pattern TEXT DEFAULT NULL
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
            ts_rank(b.tsv, plainto_tsquery('simple', p_query)) AS fts_score,
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
