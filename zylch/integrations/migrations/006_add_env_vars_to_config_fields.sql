-- Migration: Add env_var to config_fields for all API-key providers
-- Purpose: CLI can check environment variables dynamically (no hardcoded list)
-- Date: 2026-01-16

-- Vonage: Add env_var and update format
UPDATE integration_providers
SET config_fields = '{
    "api_key": {"type": "string", "label": "API Key", "required": true, "encrypted": true, "env_var": "VONAGE_API_KEY"},
    "api_secret": {"type": "string", "label": "API Secret", "required": true, "encrypted": true, "env_var": "VONAGE_API_SECRET"},
    "from_number": {"type": "string", "label": "From Number", "required": true, "encrypted": false, "env_var": "VONAGE_FROM_NUMBER"}
}'::jsonb,
    documentation_url = 'https://dashboard.nexmo.com/'
WHERE provider_key = 'vonage';

-- Pipedrive: Add env_var
UPDATE integration_providers
SET config_fields = '{
    "api_token": {"type": "string", "label": "API Token", "required": true, "encrypted": true, "env_var": "PIPEDRIVE_API_TOKEN"}
}'::jsonb,
    documentation_url = 'https://app.pipedrive.com/settings/api'
WHERE provider_key = 'pipedrive';

-- Anthropic: Add env_var
UPDATE integration_providers
SET config_fields = '{
    "api_key": {"type": "string", "label": "Anthropic API Key", "required": true, "encrypted": true, "env_var": "ANTHROPIC_API_KEY", "description": "Your Anthropic API key (starts with sk-ant-)", "placeholder": "sk-ant-..."}
}'::jsonb,
    documentation_url = 'https://console.anthropic.com/settings/keys'
WHERE provider_key = 'anthropic';

-- OpenAI: Add env_var
UPDATE integration_providers
SET config_fields = '{
    "api_key": {"type": "string", "label": "OpenAI API Key", "required": true, "encrypted": true, "env_var": "OPENAI_API_KEY", "description": "Your OpenAI API key (starts with sk-)", "placeholder": "sk-proj-..."}
}'::jsonb,
    documentation_url = 'https://platform.openai.com/api-keys'
WHERE provider_key = 'openai';

-- Mistral: Add env_var
UPDATE integration_providers
SET config_fields = '{
    "api_key": {"type": "string", "label": "Mistral API Key", "required": true, "encrypted": true, "env_var": "MISTRAL_API_KEY", "description": "Your Mistral API key", "placeholder": "Enter your API key"}
}'::jsonb,
    documentation_url = 'https://console.mistral.ai/api-keys/'
WHERE provider_key = 'mistral';

-- SendGrid: Add env_var
UPDATE integration_providers
SET config_fields = '{
    "api_key": {"type": "string", "label": "API Key", "required": true, "encrypted": true, "env_var": "SENDGRID_API_KEY"},
    "from_email": {"type": "string", "label": "From Email (optional)", "required": false, "encrypted": false, "env_var": "SENDGRID_FROM_EMAIL"}
}'::jsonb,
    documentation_url = 'https://app.sendgrid.com/settings/api_keys'
WHERE provider_key = 'sendgrid';
