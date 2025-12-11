-- Migration: Drop legacy credential columns from oauth_tokens
-- Date: 2025-12-11
-- Description: Remove deprecated columns that have been replaced by unified credentials JSONB storage
--
-- IMPORTANT: Run this migration ONLY after verifying all code has been updated to use
-- the unified credentials JSONB column instead of these legacy columns.

-- Drop Google OAuth legacy columns
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS google_token_data;

-- Drop Microsoft Graph legacy columns
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS graph_access_token;
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS graph_refresh_token;
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS graph_expires_at;

-- Drop Anthropic legacy column
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS anthropic_api_key;

-- Drop Pipedrive legacy column
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS pipedrive_api_token;

-- Drop Vonage legacy columns
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS vonage_api_key;
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS vonage_api_secret;
ALTER TABLE oauth_tokens DROP COLUMN IF EXISTS vonage_from_number;

-- Verify the credentials JSONB column exists (should already exist from migration 002)
-- If not, uncomment and run:
-- ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS credentials TEXT;

COMMENT ON TABLE oauth_tokens IS 'OAuth tokens and API credentials - all credentials now stored in unified credentials JSONB column (encrypted)';
