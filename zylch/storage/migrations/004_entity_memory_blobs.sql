-- Enable extensions (if not already enabled)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ===========================================
-- Table: blobs (main entity memory storage)
-- ===========================================
CREATE TABLE blobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_id TEXT NOT NULL,  -- Firebase UID for multi-tenancy
    namespace TEXT NOT NULL,  -- e.g., "user:{uid}", "org:{org_id}", "shared:{recipient}:{sender}"
    content TEXT NOT NULL,
    embedding VECTOR(384),  -- blob-level embedding (optional, for pre-filter)
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    events JSONB DEFAULT '[]'::jsonb,  -- [{timestamp, description, source}]
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_blobs_owner ON blobs(owner_id);
CREATE INDEX idx_blobs_namespace ON blobs(owner_id, namespace);
CREATE INDEX idx_blobs_tsv ON blobs USING GIN(tsv);
CREATE INDEX idx_blobs_embedding ON blobs USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
CREATE INDEX idx_blobs_updated ON blobs(updated_at DESC);

-- RLS
ALTER TABLE blobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY blobs_owner_policy ON blobs
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- ===========================================
-- Table: blob_sentences (sentence-level granularity)
-- ===========================================
CREATE TABLE blob_sentences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    blob_id UUID NOT NULL REFERENCES blobs(id) ON DELETE CASCADE,
    owner_id TEXT NOT NULL,  -- Denormalized for RLS
    sentence_text TEXT NOT NULL,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_sentences_blob_id ON blob_sentences(blob_id);
CREATE INDEX idx_sentences_owner ON blob_sentences(owner_id);
CREATE INDEX idx_sentences_embedding ON blob_sentences USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- RLS
ALTER TABLE blob_sentences ENABLE ROW LEVEL SECURITY;
CREATE POLICY sentences_owner_policy ON blob_sentences
    FOR ALL USING (owner_id = current_setting('app.current_user_id', true));

-- ===========================================
-- Helper functions
-- ===========================================

-- Hybrid search function
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
    WITH fts_results AS (
        SELECT
            b.id,
            b.content,
            b.namespace,
            b.events,
            ts_rank(b.tsv, plainto_tsquery('english', p_query)) AS fts_score
        FROM blobs b
        WHERE b.owner_id = p_owner_id
          AND (p_namespace IS NULL OR b.namespace = p_namespace)
          AND b.tsv @@ plainto_tsquery('english', p_query)
    ),
    semantic_results AS (
        SELECT
            bs.blob_id,
            MAX(1 - (bs.embedding <=> p_query_embedding)) AS max_semantic_score
        FROM blob_sentences bs
        WHERE bs.owner_id = p_owner_id
          AND bs.blob_id IN (SELECT id FROM fts_results)
        GROUP BY bs.blob_id
    )
    SELECT
        f.id AS blob_id,
        f.content,
        f.namespace,
        COALESCE(f.fts_score, 0)::FLOAT AS fts_score,
        COALESCE(s.max_semantic_score, 0)::FLOAT AS semantic_score,
        (p_fts_weight * COALESCE(f.fts_score, 0) +
         (1 - p_fts_weight) * COALESCE(s.max_semantic_score, 0))::FLOAT AS hybrid_score,
        f.events
    FROM fts_results f
    LEFT JOIN semantic_results s ON f.id = s.blob_id
    ORDER BY hybrid_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_blob_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER blobs_updated_at
    BEFORE UPDATE ON blobs
    FOR EACH ROW
    EXECUTE FUNCTION update_blob_timestamp();
