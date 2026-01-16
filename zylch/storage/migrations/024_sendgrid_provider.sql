-- Migration: Add SendGrid as BYOK provider
-- SendGrid API key should be per-user via /connect sendgrid

INSERT INTO integration_providers (provider_key, display_name, category, requires_oauth, is_available, config_fields)
VALUES (
    'sendgrid',
    'SendGrid Email',
    'email',
    false,
    true,
    '{
        "api_key": {
            "type": "string",
            "label": "API Key",
            "required": true,
            "encrypted": true
        },
        "from_email": {
            "type": "string",
            "label": "From Email",
            "required": false,
            "encrypted": false
        }
    }'::jsonb
)
ON CONFLICT (provider_key) DO UPDATE SET
    config_fields = EXCLUDED.config_fields,
    is_available = EXCLUDED.is_available;
