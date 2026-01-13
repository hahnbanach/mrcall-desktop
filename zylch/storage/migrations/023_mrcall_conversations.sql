-- MrCall phone call conversations storage
-- Stores transcriptions and metadata from MrCall phone calls

CREATE TABLE IF NOT EXISTS mrcall_conversations (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    business_id TEXT NOT NULL,

    -- Call metadata (from API camelCase → snake_case)
    contact_phone TEXT,           -- from contactNumber
    contact_name TEXT,            -- from contactName
    call_duration_ms INTEGER,     -- from duration (milliseconds)
    call_started_at TIMESTAMPTZ,  -- from startTimestamp

    -- Content
    subject TEXT,
    body JSONB,                   -- JSON with conversation, variables (audio stripped)
    custom_values JSONB,          -- from 'values' field

    -- Processing flag (memory agent)
    memory_processed_at TIMESTAMPTZ,

    -- Metadata
    raw_data JSONB,               -- Full response minus audio
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for owner queries
CREATE INDEX IF NOT EXISTS idx_mrcall_conversations_owner
    ON mrcall_conversations(owner_id);

-- Index for unprocessed conversations (memory agent)
CREATE INDEX IF NOT EXISTS idx_mrcall_conversations_unprocessed
    ON mrcall_conversations(owner_id)
    WHERE memory_processed_at IS NULL;

-- Index for recent conversations (trainer, sync)
CREATE INDEX IF NOT EXISTS idx_mrcall_conversations_started
    ON mrcall_conversations(owner_id, call_started_at DESC);

-- Index for business-scoped queries
CREATE INDEX IF NOT EXISTS idx_mrcall_conversations_business
    ON mrcall_conversations(owner_id, business_id);
