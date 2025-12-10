-- Migration: Create integration_providers table for unified connections system
-- Purpose: Centralized registry of all available integrations (email, CRM, messaging, etc.)
-- Date: 2025-12-10

-- Create integration_providers table
CREATE TABLE IF NOT EXISTS integration_providers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider_key TEXT UNIQUE NOT NULL,        -- Unique identifier: 'google', 'microsoft', 'pipedrive', 'slack'
    display_name TEXT NOT NULL,               -- User-friendly name: 'Google Workspace', 'Pipedrive CRM'
    category TEXT NOT NULL,                   -- Category: 'email', 'calendar', 'crm', 'messaging', 'telephony', 'video'
    icon_url TEXT,                            -- URL to provider icon/logo
    description TEXT,                         -- Short description of the integration
    requires_oauth BOOLEAN DEFAULT true,      -- true = OAuth flow, false = API key/manual config
    oauth_url TEXT,                           -- OAuth initiation endpoint (e.g., '/api/auth/google/authorize')
    config_fields JSONB,                      -- Required fields for API key auth: {"api_key": "string", "api_secret": "string"}
    is_available BOOLEAN DEFAULT true,        -- Can users currently connect to this provider?
    documentation_url TEXT,                   -- Link to setup docs
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create index on provider_key for fast lookups
CREATE INDEX IF NOT EXISTS idx_integration_providers_key ON integration_providers(provider_key);
CREATE INDEX IF NOT EXISTS idx_integration_providers_category ON integration_providers(category);
CREATE INDEX IF NOT EXISTS idx_integration_providers_available ON integration_providers(is_available);

-- Seed with current and planned providers
INSERT INTO integration_providers (provider_key, display_name, category, requires_oauth, oauth_url, is_available, description) VALUES

-- Email & Calendar (Currently Available)
('google', 'Google (Gmail & Calendar)', 'email', true, '/api/auth/google/authorize', true, 'Access Gmail emails and Google Calendar events'),
('microsoft', 'Microsoft (Outlook & Calendar)', 'email', true, '/api/auth/microsoft-login', true, 'Access Outlook emails and Microsoft Calendar events'),

-- Telephony & SMS
('mrcall', 'MrCall (Phone & SMS)', 'telephony', false, null, false, 'AI-powered phone calls and SMS via MrCall/StarChat'),
('vonage', 'Vonage SMS', 'messaging', false, null, true, 'Send and receive SMS messages via Vonage API'),

-- CRM (Currently Available)
('pipedrive', 'Pipedrive CRM', 'crm', false, null, true, 'Sync contacts, deals, and pipeline data from Pipedrive'),

-- AI Services (Currently Available)
('anthropic', 'Anthropic API (BYOK)', 'ai', false, null, true, 'Use your own Anthropic API key for Claude access'),

-- Messaging (Planned)
('whatsapp', 'WhatsApp Business', 'messaging', true, '/api/auth/whatsapp/authorize', false, 'Send and receive WhatsApp messages via Business API'),
('slack', 'Slack', 'messaging', true, '/api/auth/slack/authorize', false, 'Integrate with Slack workspaces for team communication'),
('teams', 'Microsoft Teams', 'messaging', true, '/api/auth/teams/authorize', false, 'Integrate with Microsoft Teams for team collaboration'),

-- Video Conferencing (Planned)
('zoom', 'Zoom', 'video', true, '/api/auth/zoom/authorize', false, 'Schedule and manage Zoom meetings')

ON CONFLICT (provider_key) DO NOTHING;

-- Add connection tracking columns to oauth_tokens table
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS connection_status TEXT DEFAULT 'connected';
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS last_sync TIMESTAMPTZ;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS display_name TEXT;

-- Add API key storage columns for non-OAuth integrations
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS pipedrive_api_token TEXT;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS vonage_api_key TEXT;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS vonage_api_secret TEXT;
ALTER TABLE oauth_tokens ADD COLUMN IF NOT EXISTS vonage_from_number TEXT;

-- Create index on connection_status for filtering
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_status ON oauth_tokens(owner_id, connection_status);

-- Add comment to document the table
COMMENT ON TABLE integration_providers IS 'Master registry of all available integration providers (email, CRM, messaging, etc.)';
COMMENT ON COLUMN integration_providers.provider_key IS 'Unique identifier for the provider (used in oauth_tokens.provider)';
COMMENT ON COLUMN integration_providers.requires_oauth IS 'true = OAuth flow required, false = API key/manual configuration';
COMMENT ON COLUMN integration_providers.is_available IS 'false = Coming soon (show in UI but disable connection)';
COMMENT ON COLUMN integration_providers.config_fields IS 'JSON schema for API key fields: {"api_key": "string", "api_secret": "string"}';

-- Seed config_fields for API key providers
UPDATE integration_providers SET config_fields = '{"api_token": {"type": "string", "label": "API Token", "required": true}}'::jsonb WHERE provider_key = 'pipedrive';
UPDATE integration_providers SET config_fields = '{"api_key": {"type": "string", "label": "API Key", "required": true}, "api_secret": {"type": "string", "label": "API Secret", "required": true}, "from_number": {"type": "string", "label": "From Number", "required": true}}'::jsonb WHERE provider_key = 'vonage';
UPDATE integration_providers SET config_fields = '{"api_key": {"type": "string", "label": "Anthropic API Key", "required": true}}'::jsonb WHERE provider_key = 'anthropic';
UPDATE integration_providers SET config_fields = '{"business_id": {"type": "string", "label": "MrCall Business ID", "required": true}}'::jsonb WHERE provider_key = 'mrcall';
