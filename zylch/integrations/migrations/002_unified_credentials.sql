-- Migration: Unified JSONB credentials storage for all providers
-- Purpose: Eliminate provider-specific columns, enable dynamic provider additions
-- Date: 2025-12-10
-- Pattern: Similar to StarChat business variables (database-driven instead of CSV)

-- Add unified credentials column
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS credentials JSONB;

-- Add GIN index for efficient JSONB queries
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_credentials
ON oauth_tokens USING GIN (credentials);

-- Add index for provider + credentials queries
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_provider_credentials
ON oauth_tokens(owner_id, provider) WHERE credentials IS NOT NULL;

-- Update integration_providers with complete config_fields (including encryption flags)

-- Google OAuth (OAuth 2.0 with refresh tokens)
UPDATE integration_providers
SET config_fields = '{
  "access_token": {
    "type": "string",
    "label": "Access Token",
    "required": true,
    "encrypted": true,
    "description": "OAuth 2.0 access token"
  },
  "refresh_token": {
    "type": "string",
    "label": "Refresh Token",
    "required": true,
    "encrypted": true,
    "description": "OAuth 2.0 refresh token for automatic renewal"
  },
  "token_uri": {
    "type": "string",
    "label": "Token URI",
    "required": true,
    "encrypted": false,
    "description": "OAuth 2.0 token refresh endpoint"
  },
  "expires_at": {
    "type": "datetime",
    "label": "Token Expiry",
    "required": true,
    "encrypted": false,
    "description": "Timestamp when access token expires"
  },
  "scopes": {
    "type": "array",
    "label": "OAuth Scopes",
    "required": true,
    "encrypted": false,
    "description": "List of granted OAuth scopes"
  }
}'::jsonb
WHERE provider_key = 'google';

-- Microsoft OAuth (OAuth 2.0 with refresh tokens)
UPDATE integration_providers
SET config_fields = '{
  "access_token": {
    "type": "string",
    "label": "Access Token",
    "required": true,
    "encrypted": true,
    "description": "Microsoft Graph access token"
  },
  "refresh_token": {
    "type": "string",
    "label": "Refresh Token",
    "required": true,
    "encrypted": true,
    "description": "Microsoft Graph refresh token"
  },
  "expires_at": {
    "type": "datetime",
    "label": "Token Expiry",
    "required": true,
    "encrypted": false,
    "description": "Timestamp when access token expires"
  },
  "scopes": {
    "type": "array",
    "label": "OAuth Scopes",
    "required": true,
    "encrypted": false,
    "description": "List of granted Microsoft Graph scopes"
  }
}'::jsonb
WHERE provider_key = 'microsoft';

-- Anthropic API (API key)
UPDATE integration_providers
SET config_fields = '{
  "api_key": {
    "type": "string",
    "label": "Anthropic API Key",
    "required": true,
    "encrypted": true,
    "description": "Your Anthropic API key (starts with sk-ant-)",
    "placeholder": "sk-ant-api03-..."
  }
}'::jsonb
WHERE provider_key = 'anthropic';

-- Pipedrive CRM (API token)
UPDATE integration_providers
SET config_fields = '{
  "api_token": {
    "type": "string",
    "label": "API Token",
    "required": true,
    "encrypted": true,
    "description": "Your Pipedrive API token",
    "placeholder": "abc123xyz..."
  }
}'::jsonb
WHERE provider_key = 'pipedrive';

-- Vonage SMS (API credentials)
UPDATE integration_providers
SET config_fields = '{
  "api_key": {
    "type": "string",
    "label": "API Key",
    "required": true,
    "encrypted": true,
    "description": "Your Vonage API key"
  },
  "api_secret": {
    "type": "string",
    "label": "API Secret",
    "required": true,
    "encrypted": true,
    "description": "Your Vonage API secret"
  },
  "from_number": {
    "type": "string",
    "label": "From Number",
    "required": true,
    "encrypted": false,
    "description": "Phone number to send SMS from (with country code)",
    "placeholder": "+1234567890"
  }
}'::jsonb
WHERE provider_key = 'vonage';

-- MrCall (Business ID)
UPDATE integration_providers
SET config_fields = '{
  "business_id": {
    "type": "string",
    "label": "MrCall Business ID",
    "required": true,
    "encrypted": false,
    "description": "Your MrCall business identifier"
  }
}'::jsonb
WHERE provider_key = 'mrcall';

-- Add comments documenting the new pattern
COMMENT ON COLUMN oauth_tokens.credentials IS
'Unified JSONB storage for all provider credentials. Format: {"provider_key": {"field_name": "value", ...}}. Sensitive fields are encrypted before storage.';

COMMENT ON INDEX idx_oauth_tokens_credentials IS
'GIN index for efficient JSONB queries on credentials column';

-- Create helper function to check if credentials exist for a provider
CREATE OR REPLACE FUNCTION has_credentials(creds JSONB, provider_key TEXT)
RETURNS BOOLEAN AS $$
BEGIN
  RETURN creds ? provider_key AND jsonb_typeof(creds -> provider_key) = 'object';
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Example usage:
-- SELECT * FROM oauth_tokens WHERE has_credentials(credentials, 'google');
