-- Migration: Add SendGrid provider for email campaigns
-- Purpose: Enable BYOK SendGrid API key storage via /connect sendgrid
-- Date: 2025-12-11

-- Add SendGrid provider
INSERT INTO integration_providers (
    provider_key,
    display_name,
    category,
    requires_oauth,
    oauth_url,
    is_available,
    description,
    config_fields
) VALUES (
    'sendgrid',
    'SendGrid Email',
    'email',
    false,  -- API key based, not OAuth
    null,
    true,   -- Available now
    'Send emails via SendGrid API for campaigns and notifications',
    '{
        "api_key": {"type": "string", "label": "SendGrid API Key", "required": true, "encrypted": true},
        "from_email": {"type": "string", "label": "From Email Address", "required": false},
        "from_name": {"type": "string", "label": "From Name", "required": false}
    }'::jsonb
)
ON CONFLICT (provider_key) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    config_fields = EXCLUDED.config_fields,
    is_available = EXCLUDED.is_available,
    updated_at = NOW();
