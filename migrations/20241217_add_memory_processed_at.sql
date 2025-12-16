-- Migration: Add memory_processed_at column to emails table
-- Description: Tracks which emails have been processed by Memory Agent
-- Run in: Supabase SQL Editor

-- Add column (NULL = not processed, timestamp = when processed)
ALTER TABLE emails
ADD COLUMN IF NOT EXISTS memory_processed_at TIMESTAMPTZ DEFAULT NULL;

-- Index for efficient queries on unprocessed emails
CREATE INDEX IF NOT EXISTS idx_emails_memory_unprocessed
ON emails (owner_id, date DESC)
WHERE memory_processed_at IS NULL;

-- Drop the old RPC function (no longer needed)
DROP FUNCTION IF EXISTS get_unprocessed_emails(TEXT, INT);
