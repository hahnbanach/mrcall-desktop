-- Migration: Add memory_processed_at column to calendar_events table
-- Description: Tracks which calendar events have been processed by Memory Agent
-- Run in: Supabase SQL Editor

-- Add column (NULL = not processed, timestamp = when processed)
ALTER TABLE calendar_events
ADD COLUMN IF NOT EXISTS memory_processed_at TIMESTAMPTZ DEFAULT NULL;

-- Index for efficient queries on unprocessed events
CREATE INDEX IF NOT EXISTS idx_calendar_events_memory_unprocessed
ON calendar_events (owner_id, start_time DESC)
WHERE memory_processed_at IS NULL;
