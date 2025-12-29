-- Migration: Add OpenAI and Mistral LLM providers
-- Purpose: Support alternative LLM providers via LiteLLM abstraction
-- Date: 2025-12-28

-- Add OpenAI provider
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
    'openai',
    'OpenAI (GPT-4)',
    'ai',
    false,
    null,
    true,
    'Use your own OpenAI API key for GPT-4 access',
    '{"api_key": {"type": "string", "label": "OpenAI API Key", "required": true, "encrypted": true, "description": "Your OpenAI API key (starts with sk-)", "placeholder": "sk-proj-..."}}'::jsonb
) ON CONFLICT (provider_key) DO NOTHING;

-- Add Mistral provider (EU-based for GDPR compliance)
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
    'mistral',
    'Mistral AI (EU)',
    'ai',
    false,
    null,
    true,
    'Use your own Mistral API key - EU-based for GDPR compliance',
    '{"api_key": {"type": "string", "label": "Mistral API Key", "required": true, "encrypted": true, "description": "Your Mistral API key", "placeholder": "Enter your API key"}}'::jsonb
) ON CONFLICT (provider_key) DO NOTHING;

-- Update Anthropic description to clarify feature advantages
UPDATE integration_providers
SET description = 'Use your own Anthropic API key - includes web search and prompt caching'
WHERE provider_key = 'anthropic';
