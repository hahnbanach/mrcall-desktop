-- Migration: Add Anthropic API key column to oauth_tokens table
-- Run this in Supabase SQL Editor

-- Add the anthropic_api_key column
ALTER TABLE oauth_tokens
ADD COLUMN IF NOT EXISTS anthropic_api_key TEXT;

-- Verify the column was added
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'oauth_tokens'
AND column_name = 'anthropic_api_key';
