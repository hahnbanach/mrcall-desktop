-- Migration: Add task_processed_at column to emails and calendar_events
-- Description: Tracks which items have been processed by Task Agent
-- Run in: Supabase SQL Editor

-- Add to emails table (NULL = not processed, timestamp = when processed)
ALTER TABLE emails
ADD COLUMN IF NOT EXISTS task_processed_at TIMESTAMPTZ DEFAULT NULL;

-- Index for efficient queries on unprocessed emails for task agent
CREATE INDEX IF NOT EXISTS idx_emails_task_unprocessed
ON emails (owner_id, date_timestamp DESC)
WHERE task_processed_at IS NULL;

-- Add to calendar_events table
ALTER TABLE calendar_events
ADD COLUMN IF NOT EXISTS task_processed_at TIMESTAMPTZ DEFAULT NULL;

-- Index for efficient queries on unprocessed calendar events for task agent
CREATE INDEX IF NOT EXISTS idx_calendar_task_unprocessed
ON calendar_events (owner_id, start_time DESC)
WHERE task_processed_at IS NULL;
