-- Drop scheduled_jobs table (legacy trigger/reminder system)
-- Replaced by background_jobs table for async job execution

DROP TABLE IF EXISTS scheduled_jobs CASCADE;
