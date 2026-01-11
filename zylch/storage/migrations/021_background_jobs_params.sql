-- Migration 021: Add params column to background_jobs
-- Purpose: Store job parameters (e.g., days_back for sync)

ALTER TABLE background_jobs
ADD COLUMN IF NOT EXISTS params JSONB DEFAULT '{}';

COMMENT ON COLUMN background_jobs.params IS 'Job input parameters (e.g., days_back for sync)';
