-- Scheduled Jobs table for Supabase-based scheduler
-- Replaces local SQLite APScheduler storage

CREATE TABLE scheduled_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id TEXT NOT NULL,

    -- Job definition
    job_type TEXT NOT NULL,  -- 'reminder', 'recurring', 'conditional'
    message TEXT NOT NULL,
    callback_type TEXT NOT NULL DEFAULT 'notification',
    metadata JSONB DEFAULT '{}',

    -- Scheduling
    run_at TIMESTAMPTZ,           -- For one-time jobs
    cron_expression TEXT,         -- For recurring jobs (e.g., "0 9 * * 1-5")
    interval_seconds INTEGER,     -- For interval jobs
    condition_key TEXT,           -- For conditional timeouts
    timeout_seconds INTEGER,      -- For conditional timeouts

    -- Status
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, cancelled, failed
    last_run_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0,
    last_error TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_scheduled_jobs_owner ON scheduled_jobs(owner_id);
CREATE INDEX idx_scheduled_jobs_status ON scheduled_jobs(status);
CREATE INDEX idx_scheduled_jobs_next_run ON scheduled_jobs(next_run_at) WHERE status = 'pending';
CREATE INDEX idx_scheduled_jobs_condition ON scheduled_jobs(owner_id, condition_key) WHERE condition_key IS NOT NULL;

-- RLS
ALTER TABLE scheduled_jobs ENABLE ROW LEVEL SECURITY;
