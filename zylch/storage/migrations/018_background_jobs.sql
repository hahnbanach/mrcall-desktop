-- Migration 018: Background Jobs Table
-- Purpose: Postgres-based job queue for long-running operations
-- (memory processing, task processing, sync) without blocking other requests.

CREATE TABLE IF NOT EXISTS background_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,

    -- Job definition
    job_type TEXT NOT NULL,  -- 'memory_process', 'task_process', 'sync'
    channel TEXT,            -- 'email', 'calendar', 'all', NULL

    -- Status tracking
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed, cancelled
    progress_pct INTEGER DEFAULT 0,          -- 0-100
    items_processed INTEGER DEFAULT 0,
    total_items INTEGER,
    status_message TEXT,                     -- "Processing email 45/120..."

    -- Timing
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Error handling
    last_error TEXT,
    retry_count INTEGER DEFAULT 0,

    -- Results
    result JSONB DEFAULT '{}'   -- Summary stats on completion
);

-- Index for efficient job claiming (pending jobs, oldest first)
CREATE INDEX IF NOT EXISTS idx_bg_jobs_pending
    ON background_jobs(status, created_at)
    WHERE status = 'pending';

-- Index for status polling by user
CREATE INDEX IF NOT EXISTS idx_bg_jobs_owner
    ON background_jobs(owner_id, created_at DESC);

-- Prevent duplicate jobs (same user, same type, same channel while pending/running)
CREATE UNIQUE INDEX IF NOT EXISTS idx_bg_jobs_no_duplicates
    ON background_jobs(owner_id, job_type, channel)
    WHERE status IN ('pending', 'running');

-- RLS
ALTER TABLE background_jobs ENABLE ROW LEVEL SECURITY;

-- Users can only view their own jobs (for anon key access if needed)
CREATE POLICY "Users can view own jobs"
    ON background_jobs FOR SELECT
    USING (owner_id = current_setting('request.jwt.claims', true)::json->>'sub');

-- Service role has full access (backend uses service role key)
CREATE POLICY "Service role full access"
    ON background_jobs FOR ALL
    USING (true)
    WITH CHECK (true);

-- Comment for documentation
COMMENT ON TABLE background_jobs IS 'Postgres-based job queue for long-running background operations';
COMMENT ON COLUMN background_jobs.job_type IS 'Type of job: memory_process, task_process, sync';
COMMENT ON COLUMN background_jobs.channel IS 'Data channel: email, calendar, all, or NULL';
COMMENT ON COLUMN background_jobs.status IS 'Job status: pending, running, completed, failed, cancelled';
COMMENT ON COLUMN background_jobs.progress_pct IS 'Progress percentage 0-100 for frontend display';
