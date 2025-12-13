-- Migration: Enable MrCall OAuth 2.0 Integration
-- Purpose: Update mrcall provider to use OAuth authentication
-- Date: 2025-12-13

-- Update MrCall provider to enable OAuth
UPDATE integration_providers
SET
    requires_oauth = true,
    oauth_url = '/api/auth/mrcall/authorize',
    is_available = true,
    description = 'AI-powered phone calls and SMS via MrCall/StarChat (OAuth 2.0)',
    updated_at = NOW()
WHERE provider_key = 'mrcall';

-- Verify the update
SELECT provider_key, display_name, requires_oauth, oauth_url, is_available
FROM integration_providers
WHERE provider_key = 'mrcall';
