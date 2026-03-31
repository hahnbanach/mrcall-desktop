"""Seed integration_providers table with all provider data.

Consolidates SQL migrations 001 (INSERTs + config_fields), 003 (sendgrid),
005 (openai + mistral), and 006 (env_var in config_fields) into a single
Alembic data migration.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-31
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

PROVIDER_KEYS = [
    "google",
    "microsoft",
    "mrcall",
    "vonage",
    "pipedrive",
    "anthropic",
    "whatsapp",
    "slack",
    "teams",
    "zoom",
    "sendgrid",
    "openai",
    "mistral",
]


def upgrade() -> None:
    # --- Base providers (from 001) ---
    op.execute("""
        INSERT INTO integration_providers
            (provider_key, display_name, category, requires_oauth, oauth_url,
             is_available, description)
        VALUES
            ('google', 'Google (Gmail & Calendar)', 'email', true,
             '/api/auth/google/authorize', true,
             'Access Gmail emails and Google Calendar events'),
            ('microsoft', 'Microsoft (Outlook & Calendar)', 'email', true,
             '/api/auth/microsoft-login', true,
             'Access Outlook emails and Microsoft Calendar events'),
            ('mrcall', 'MrCall (Phone & SMS)', 'telephony', false,
             null, false,
             'AI-powered phone calls and SMS via MrCall/StarChat'),
            ('vonage', 'Vonage SMS', 'messaging', false,
             null, true,
             'Send and receive SMS messages via Vonage API'),
            ('pipedrive', 'Pipedrive CRM', 'crm', false,
             null, true,
             'Sync contacts, deals, and pipeline data from Pipedrive'),
            ('anthropic', 'Anthropic API (BYOK)', 'ai', false,
             null, true,
             'Use your own Anthropic API key for Claude access'),
            ('whatsapp', 'WhatsApp Business', 'messaging', true,
             '/api/auth/whatsapp/authorize', false,
             'Send and receive WhatsApp messages via Business API'),
            ('slack', 'Slack', 'messaging', true,
             '/api/auth/slack/authorize', false,
             'Integrate with Slack workspaces for team communication'),
            ('teams', 'Microsoft Teams', 'messaging', true,
             '/api/auth/teams/authorize', false,
             'Integrate with Microsoft Teams for team collaboration'),
            ('zoom', 'Zoom', 'video', true,
             '/api/auth/zoom/authorize', false,
             'Schedule and manage Zoom meetings')
        ON CONFLICT (provider_key) DO NOTHING;
    """)

    # --- SendGrid (from 003) ---
    op.execute("""
        INSERT INTO integration_providers
            (provider_key, display_name, category, requires_oauth, oauth_url,
             is_available, description)
        VALUES
            ('sendgrid', 'SendGrid Email', 'email', false, null, true,
             'Send emails via SendGrid API for campaigns and notifications')
        ON CONFLICT (provider_key) DO NOTHING;
    """)

    # --- OpenAI + Mistral (from 005) ---
    op.execute("""
        INSERT INTO integration_providers
            (provider_key, display_name, category, requires_oauth, oauth_url,
             is_available, description)
        VALUES
            ('openai', 'OpenAI (GPT-4)', 'ai', false, null, true,
             'Use your own OpenAI API key for GPT-4 access'),
            ('mistral', 'Mistral AI (EU)', 'ai', false, null, true,
             'Use your own Mistral API key - EU-based for GDPR compliance')
        ON CONFLICT (provider_key) DO NOTHING;
    """)

    # --- Anthropic description update (from 005) ---
    op.execute("""
        UPDATE integration_providers
        SET description =
            'Use your own Anthropic API key - includes web search and prompt caching'
        WHERE provider_key = 'anthropic';
    """)

    # --- Final config_fields with env_var + documentation_url (001 + 006 merged) ---
    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "api_key": {"type": "string", "label": "API Key", "required": true,
                        "encrypted": true, "env_var": "VONAGE_API_KEY"},
            "api_secret": {"type": "string", "label": "API Secret", "required": true,
                           "encrypted": true, "env_var": "VONAGE_API_SECRET"},
            "from_number": {"type": "string", "label": "From Number", "required": true,
                            "encrypted": false, "env_var": "VONAGE_FROM_NUMBER"}
        }'::jsonb, documentation_url = 'https://dashboard.nexmo.com/'
        WHERE provider_key = 'vonage';
    """)

    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "api_token": {"type": "string", "label": "API Token", "required": true,
                          "encrypted": true, "env_var": "PIPEDRIVE_API_TOKEN"}
        }'::jsonb, documentation_url = 'https://app.pipedrive.com/settings/api'
        WHERE provider_key = 'pipedrive';
    """)

    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "api_key": {"type": "string", "label": "Anthropic API Key", "required": true,
                        "encrypted": true, "env_var": "ANTHROPIC_API_KEY",
                        "description": "Your Anthropic API key (starts with sk-ant-)",
                        "placeholder": "sk-ant-..."}
        }'::jsonb, documentation_url = 'https://console.anthropic.com/settings/keys'
        WHERE provider_key = 'anthropic';
    """)

    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "api_key": {"type": "string", "label": "OpenAI API Key", "required": true,
                        "encrypted": true, "env_var": "OPENAI_API_KEY",
                        "description": "Your OpenAI API key (starts with sk-)",
                        "placeholder": "sk-proj-..."}
        }'::jsonb, documentation_url = 'https://platform.openai.com/api-keys'
        WHERE provider_key = 'openai';
    """)

    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "api_key": {"type": "string", "label": "Mistral API Key", "required": true,
                        "encrypted": true, "env_var": "MISTRAL_API_KEY",
                        "description": "Your Mistral API key",
                        "placeholder": "Enter your API key"}
        }'::jsonb, documentation_url = 'https://console.mistral.ai/api-keys/'
        WHERE provider_key = 'mistral';
    """)

    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "api_key": {"type": "string", "label": "API Key", "required": true,
                        "encrypted": true, "env_var": "SENDGRID_API_KEY"},
            "from_email": {"type": "string", "label": "From Email (optional)",
                           "required": false, "encrypted": false,
                           "env_var": "SENDGRID_FROM_EMAIL"}
        }'::jsonb, documentation_url = 'https://app.sendgrid.com/settings/api_keys'
        WHERE provider_key = 'sendgrid';
    """)

    op.execute("""
        UPDATE integration_providers SET config_fields = '{
            "business_id": {"type": "string", "label": "MrCall Business ID",
                            "required": true}
        }'::jsonb
        WHERE provider_key = 'mrcall';
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM integration_providers
        WHERE provider_key IN (
            'google', 'microsoft', 'mrcall', 'vonage', 'pipedrive',
            'anthropic', 'whatsapp', 'slack', 'teams', 'zoom',
            'sendgrid', 'openai', 'mistral'
        );
    """)
