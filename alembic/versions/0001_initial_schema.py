"""Initial Zylch database schema.

Creates all tables, indexes, functions, triggers, and stored procedures
from scratch.

Revision ID: 0001
Revises: (none)
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extensions
    # ------------------------------------------------------------------
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # ------------------------------------------------------------------
    # 2. Helper function (must exist BEFORE blobs table for GENERATED col)
    # ------------------------------------------------------------------
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION extract_identifiers(content TEXT)
        RETURNS TEXT AS $$
        BEGIN
            RETURN COALESCE(
                substring(content FROM '#IDENTIFIERS(.*?)#ABOUT'),
                ''
            );
        END;
        $$ LANGUAGE plpgsql IMMUTABLE
    """))

    # ------------------------------------------------------------------
    # 3. Tables WITHOUT foreign keys
    # ------------------------------------------------------------------

    # --- emails ---
    op.create_table(
        "emails",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("gmail_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("from_email", sa.Text),
        sa.Column("from_name", sa.Text),
        sa.Column("to_email", sa.Text),
        sa.Column("cc_email", sa.Text),
        sa.Column("subject", sa.Text),
        sa.Column("date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("date_timestamp", sa.Integer),
        sa.Column("snippet", sa.Text),
        sa.Column("body_plain", sa.Text),
        sa.Column("body_html", sa.Text),
        sa.Column("labels", sa.Text),
        sa.Column("message_id_header", sa.Text),
        sa.Column("in_reply_to", sa.Text),
        sa.Column("references", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # fts_document, tsv, embedding added later via raw SQL
        sa.Column("read_events", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("memory_processed_at", sa.DateTime(timezone=True)),
        sa.Column("task_processed_at", sa.DateTime(timezone=True)),
        sa.Column("is_auto_reply", sa.Boolean, server_default=sa.text("false")),
        sa.UniqueConstraint("owner_id", "gmail_id", name="emails_owner_gmail_unique"),
    )

    # --- calendar_events ---
    op.create_table(
        "calendar_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("google_event_id", sa.Text, nullable=False),
        sa.Column("summary", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("location", sa.Text),
        sa.Column("attendees", JSONB),
        sa.Column("organizer_email", sa.Text),
        sa.Column("is_external", sa.Boolean, server_default=sa.text("false")),
        sa.Column("meet_link", sa.Text),
        sa.Column("calendar_id", sa.Text, server_default=sa.text("'primary'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("memory_processed_at", sa.DateTime(timezone=True)),
        sa.Column("task_processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("owner_id", "google_event_id", name="calendar_events_owner_gid_unique"),
    )

    # --- blobs ---
    op.create_table(
        "blobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("namespace", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        # embedding added via raw SQL (pgvector type)
        sa.Column("events", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        # tsv added later as GENERATED ALWAYS column via raw SQL
    )

    # --- oauth_tokens ---
    op.create_table(
        "oauth_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("scopes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("connection_status", sa.Text, server_default=sa.text("'connected'")),
        sa.Column("last_sync", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("display_name", sa.Text),
        sa.Column("credentials", JSONB),
        sa.UniqueConstraint("owner_id", "provider", name="oauth_tokens_owner_provider_unique"),
    )

    # --- oauth_states ---
    op.create_table(
        "oauth_states",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("state", sa.Text, nullable=False, unique=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("email", sa.Text),
        sa.Column("cli_callback", sa.Text),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("provider", sa.Text, server_default=sa.text("'google'")),
        sa.Column("metadata", JSONB),
    )

    # --- triggers ---
    op.create_table(
        "triggers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("trigger_type", sa.Text, nullable=False),
        sa.Column("instruction", sa.Text, nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "trigger_type IN ('session_start', 'email_received', 'sms_received', 'call_received')",
            name="triggers_type_check",
        ),
    )

    # --- sharing_auth ---
    op.create_table(
        "sharing_auth",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("sender_id", sa.Text, nullable=False),
        sa.Column("sender_email", sa.Text, nullable=False),
        sa.Column("recipient_email", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default=sa.text("'pending'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("authorized_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("sender_id", "recipient_email", name="sharing_auth_sender_recipient_unique"),
        sa.CheckConstraint(
            "status IN ('pending', 'authorized', 'revoked')",
            name="sharing_auth_status_check",
        ),
    )

    # --- drafts ---
    op.create_table(
        "drafts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("to_addresses", ARRAY(sa.Text), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("cc_addresses", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("bcc_addresses", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("subject", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("body_format", sa.Text, server_default=sa.text("'html'")),
        sa.Column("in_reply_to", sa.Text),
        sa.Column("references", ARRAY(sa.Text)),
        sa.Column("thread_id", sa.Text),
        sa.Column("original_message_id", sa.Text),
        sa.Column("status", sa.Text, server_default=sa.text("'draft'")),
        sa.Column("provider", sa.Text),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("sent_message_id", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "body_format IN ('html', 'plain')",
            name="drafts_body_format_check",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'sending', 'sent', 'failed')",
            name="drafts_status_check",
        ),
        sa.CheckConstraint(
            "provider IN ('google', 'microsoft')",
            name="drafts_provider_check",
        ),
    )

    # --- task_items ---
    op.create_table(
        "task_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("contact_email", sa.Text),
        sa.Column("contact_name", sa.Text),
        sa.Column("action_required", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("urgency", sa.Text),
        sa.Column("reason", sa.Text),
        sa.Column("suggested_action", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("sources", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("owner_id", "event_type", "event_id", name="task_items_owner_event_unique"),
    )

    # --- background_jobs ---
    op.create_table(
        "background_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column("channel", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("progress_pct", sa.Integer, server_default=sa.text("0")),
        sa.Column("items_processed", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_items", sa.Integer),
        sa.Column("status_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("retry_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("result", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("params", JSONB, server_default=sa.text("'{}'::jsonb")),
    )

    # --- agent_prompts ---
    op.create_table(
        "agent_prompts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("agent_type", sa.Text, nullable=False),
        sa.Column("agent_prompt", sa.Text, nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("owner_id", "agent_type", name="agent_prompts_owner_type_unique"),
    )

    # --- pipedrive_deals ---
    op.create_table(
        "pipedrive_deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("deal_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("person_name", sa.Text),
        sa.Column("org_name", sa.Text),
        sa.Column("value", sa.Numeric),
        sa.Column("currency", sa.Text, server_default=sa.text("'USD'")),
        sa.Column("status", sa.Text),
        sa.Column("stage_name", sa.Text),
        sa.Column("pipeline_name", sa.Text),
        sa.Column("expected_close_date", sa.Date),
        sa.Column("deal_data", JSONB),
        sa.Column("memory_processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("owner_id", "deal_id", name="pipedrive_deals_owner_deal_unique"),
    )

    # --- user_notifications ---
    op.create_table(
        "user_notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("notification_type", sa.Text, server_default=sa.text("'warning'")),
        sa.Column("read", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- email_read_events ---
    op.create_table(
        "email_read_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tracking_id", sa.Text),
        sa.Column("sendgrid_message_id", sa.Text),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("message_id", sa.Text, nullable=False),
        sa.Column("recipient_email", sa.Text, nullable=False),
        sa.Column("tracking_source", sa.Text, nullable=False),
        sa.Column("read_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("first_read_at", sa.DateTime(timezone=True)),
        sa.Column("last_read_at", sa.DateTime(timezone=True)),
        sa.Column("user_agents", ARRAY(sa.Text)),
        sa.Column("ip_addresses", ARRAY(sa.Text)),
        sa.Column("sendgrid_event_data", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "tracking_source IN ('sendgrid_webhook', 'custom_pixel')",
            name="email_read_events_source_check",
        ),
    )

    # --- sendgrid_message_mapping ---
    op.create_table(
        "sendgrid_message_mapping",
        sa.Column("sendgrid_message_id", sa.Text, primary_key=True),
        sa.Column("message_id", sa.Text, nullable=False),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("recipient_email", sa.Text, nullable=False),
        sa.Column("campaign_id", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), server_default=sa.text("now() + interval '90 days'")),
    )

    # --- mrcall_conversations ---
    op.create_table(
        "mrcall_conversations",
        sa.Column("id", sa.Text, primary_key=True),  # TEXT PK, not UUID
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("business_id", sa.Text, nullable=False),
        sa.Column("contact_phone", sa.Text),
        sa.Column("contact_name", sa.Text),
        sa.Column("call_duration_ms", sa.Integer),
        sa.Column("call_started_at", sa.DateTime(timezone=True)),
        sa.Column("subject", sa.Text),
        sa.Column("body", JSONB),
        sa.Column("custom_values", JSONB),
        sa.Column("memory_processed_at", sa.DateTime(timezone=True)),
        sa.Column("raw_data", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- verification_codes ---
    op.create_table(
        "verification_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("phone_number", sa.Text, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("context", sa.Text),
        sa.Column("expires_in_minutes", sa.Integer, server_default=sa.text("15")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified", sa.Boolean, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- email_triage ---
    op.create_table(
        "email_triage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("needs_human_attention", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("triage_category", sa.Text),
        sa.Column("reason", sa.Text),
        sa.Column("is_real_customer", sa.Boolean),
        sa.Column("is_actionable", sa.Boolean),
        sa.Column("is_time_sensitive", sa.Boolean),
        sa.Column("is_resolved", sa.Boolean),
        sa.Column("is_cold_outreach", sa.Boolean),
        sa.Column("is_automated", sa.Boolean),
        sa.Column("suggested_action", sa.Text),
        sa.Column("deadline_detected", sa.Date),
        sa.Column("model_used", sa.Text),
        sa.Column("prompt_version", sa.Text),
        sa.Column("confidence_score", sa.Float),
        sa.Column("user_override", sa.Boolean, server_default=sa.text("false")),
        sa.Column("user_override_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("owner_id", "thread_id", name="email_triage_owner_thread_unique"),
        sa.CheckConstraint(
            "triage_category IN ('urgent', 'normal', 'low', 'noise')",
            name="email_triage_category_check",
        ),
    )

    # --- training_samples ---
    op.create_table(
        "training_samples",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("sample_hash", sa.Text, nullable=False, unique=True),
        sa.Column("question_type", sa.Text, nullable=False),
        sa.Column("anonymized_input", sa.Text, nullable=False),
        sa.Column("model_answer", JSONB, nullable=False),
        sa.Column("thread_length", sa.Integer),
        sa.Column("has_attachments", sa.Boolean),
        sa.Column("email_domain_category", sa.Text),
        sa.Column("importance_rule_matched", sa.Text),
        sa.Column("used_in_training", sa.Boolean, server_default=sa.text("false")),
        sa.Column("training_batch_id", sa.Text),
        sa.Column("model_version_trained", sa.Text),
        sa.Column("user_override", sa.Boolean, server_default=sa.text("false")),
        sa.Column("user_override_reason", sa.Text),
        sa.Column("confidence_score", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "question_type IN ('triage', 'classification', 'action')",
            name="training_samples_type_check",
        ),
    )

    # --- importance_rules ---
    op.create_table(
        "importance_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("account_id", UUID(as_uuid=True)),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("condition", sa.Text, nullable=False),
        sa.Column("importance", sa.Text, nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("priority", sa.Integer, server_default=sa.text("0")),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("owner_id", "account_id", "name", name="importance_rules_owner_account_name_unique"),
        sa.CheckConstraint(
            "importance IN ('high', 'normal', 'low')",
            name="importance_rules_importance_check",
        ),
    )

    # --- integration_providers ---
    op.create_table(
        "integration_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("provider_key", sa.Text, nullable=False, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("icon_url", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("requires_oauth", sa.Boolean, server_default=sa.text("true")),
        sa.Column("oauth_url", sa.Text),
        sa.Column("config_fields", JSONB),
        sa.Column("is_available", sa.Boolean, server_default=sa.text("true")),
        sa.Column("documentation_url", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- triage_training_samples ---
    op.create_table(
        "triage_training_samples",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("email_data", JSONB, nullable=False),
        sa.Column("predicted_verdict", JSONB, nullable=False),
        sa.Column("actual_verdict", JSONB),
        sa.Column("feedback_type", sa.Text),
        sa.Column("used_for_training", sa.Boolean, server_default=sa.text("false")),
        sa.Column("training_batch_id", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "feedback_type IN ('correction', 'confirmation')",
            name="triage_training_feedback_check",
        ),
    )

    # --- patterns ---
    op.create_table(
        "patterns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("namespace", sa.Text, nullable=False),
        sa.Column("skill", sa.Text, nullable=False),
        sa.Column("intent", sa.Text, nullable=False),
        sa.Column("context", JSONB),
        sa.Column("action", JSONB),
        sa.Column("outcome", sa.Text),
        sa.Column("contact_id", sa.Text),
        sa.Column("confidence", sa.Float, server_default=sa.text("0.5")),
        sa.Column("times_applied", sa.Integer, server_default=sa.text("0")),
        sa.Column("times_successful", sa.Integer, server_default=sa.text("0")),
        sa.Column("state", sa.Text, server_default=sa.text("'active'")),
        # embedding added via raw SQL (pgvector type)
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_accessed", sa.DateTime(timezone=True)),
    )

    # --- sync_state ---
    op.create_table(
        "sync_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, unique=True),
        sa.Column("history_id", sa.Text),
        sa.Column("last_sync", sa.DateTime(timezone=True)),
        sa.Column("full_sync_completed", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- scheduled_jobs ---
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("callback_type", sa.Text, nullable=False, server_default=sa.text("'notification'")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("run_at", sa.DateTime(timezone=True)),
        sa.Column("cron_expression", sa.Text),
        sa.Column("interval_seconds", sa.Integer),
        sa.Column("condition_key", sa.Text),
        sa.Column("timeout_seconds", sa.Integer),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("run_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- contacts ---
    op.create_table(
        "contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("email", sa.Text),
        sa.Column("name", sa.Text),
        sa.Column("phone", sa.Text),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- thread_analysis ---
    op.create_table(
        "thread_analysis",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("contact_email", sa.Text),
        sa.Column("contact_name", sa.Text),
        sa.Column("last_email_date", sa.DateTime(timezone=True)),
        sa.Column("last_email_direction", sa.Text),
        sa.Column("analysis", JSONB),
        sa.Column("needs_action", sa.Boolean, server_default=sa.text("false")),
        sa.Column("task_description", sa.Text),
        sa.Column("priority", sa.Integer),
        sa.Column("manually_closed", sa.Boolean, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ------------------------------------------------------------------
    # Tables WITH foreign keys
    # ------------------------------------------------------------------

    # --- blob_sentences (FK to blobs.id) ---
    op.create_table(
        "blob_sentences",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("blob_id", UUID(as_uuid=True), sa.ForeignKey("blobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("sentence_text", sa.Text, nullable=False),
        # embedding added via raw SQL (pgvector type)
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # --- trigger_events (FK to triggers.id) ---
    op.create_table(
        "trigger_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text, nullable=False, index=True),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("event_data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text, server_default=sa.text("'pending'")),
        sa.Column("trigger_id", UUID(as_uuid=True), sa.ForeignKey("triggers.id")),
        sa.Column("result", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text),
        sa.CheckConstraint(
            "event_type IN ('email_received', 'sms_received', 'call_received')",
            name="trigger_events_type_check",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="trigger_events_status_check",
        ),
    )

    # ------------------------------------------------------------------
    # 4. pgvector columns (raw SQL — Alembic doesn't know about vector type)
    # ------------------------------------------------------------------
    op.execute(sa.text("ALTER TABLE blobs ADD COLUMN embedding vector(384)"))
    op.execute(sa.text("ALTER TABLE emails ADD COLUMN embedding vector(384)"))
    op.execute(sa.text("ALTER TABLE blob_sentences ADD COLUMN embedding vector(384) NOT NULL"))
    op.execute(sa.text("ALTER TABLE patterns ADD COLUMN embedding vector(384)"))

    # ------------------------------------------------------------------
    # 4b. GENERATED ALWAYS columns (raw SQL)
    # ------------------------------------------------------------------

    # blobs.tsv — GENERATED ALWAYS from extract_identifiers(content)
    op.execute(sa.text("""
        ALTER TABLE blobs ADD COLUMN tsv TSVECTOR
        GENERATED ALWAYS AS (to_tsvector('simple', extract_identifiers(content))) STORED
    """))

    # emails.tsv — GENERATED ALWAYS from subject + body_plain
    op.execute(sa.text("""
        ALTER TABLE emails ADD COLUMN tsv TSVECTOR
        GENERATED ALWAYS AS (
            to_tsvector('simple', COALESCE(subject, '') || ' ' || COALESCE(body_plain, ''))
        ) STORED
    """))

    # emails.fts_document — GENERATED ALWAYS weighted FTS
    op.execute(sa.text("""
        ALTER TABLE emails ADD COLUMN fts_document TSVECTOR
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', COALESCE(subject, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(body_plain, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(from_email, '')), 'C')
        ) STORED
    """))

    # ------------------------------------------------------------------
    # 5. Trigger functions and triggers
    # ------------------------------------------------------------------

    # Blob updated_at
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION update_blob_timestamp()
        RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER blobs_updated_at BEFORE UPDATE ON blobs
        FOR EACH ROW EXECUTE FUNCTION update_blob_timestamp()
    """))

    # Drafts updated_at
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION update_drafts_updated_at()
        RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER drafts_updated_at BEFORE UPDATE ON drafts
        FOR EACH ROW EXECUTE FUNCTION update_drafts_updated_at()
    """))

    # Email read events updated_at
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION update_email_read_events_timestamp()
        RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trigger_email_read_events_updated_at BEFORE UPDATE ON email_read_events
        FOR EACH ROW EXECUTE FUNCTION update_email_read_events_timestamp()
    """))

    # ------------------------------------------------------------------
    # 6. RPC / stored procedure functions
    # ------------------------------------------------------------------

    # 6a. hybrid_search_blobs
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hybrid_search_blobs(
            p_owner_id TEXT,
            p_query TEXT,
            p_query_embedding VECTOR(384),
            p_namespace TEXT DEFAULT NULL,
            p_fts_weight FLOAT DEFAULT 0.5,
            p_limit INT DEFAULT 10,
            p_exact_pattern TEXT DEFAULT NULL
        )
        RETURNS TABLE (
            blob_id UUID, content TEXT, namespace TEXT,
            fts_score FLOAT, semantic_score FLOAT, exact_score FLOAT,
            hybrid_score FLOAT, events JSONB
        ) AS $$
        BEGIN
            RETURN QUERY
            WITH all_blobs AS (
                SELECT b.id, b.content, b.namespace, b.events,
                    ts_rank(b.tsv, plainto_tsquery('simple', p_query)) AS fts_score,
                    CASE WHEN p_exact_pattern IS NOT NULL
                        AND substring(b.content FROM '#IDENTIFIERS(.*?)#ABOUT')
                            ILIKE '%' || p_exact_pattern || '%'
                        THEN 1.0 ELSE 0.0
                    END AS exact_score
                FROM blobs b
                WHERE b.owner_id = p_owner_id
                  AND (p_namespace IS NULL OR b.namespace = p_namespace)
            ),
            semantic_results AS (
                SELECT bs.blob_id,
                    MAX(1 - (bs.embedding <=> p_query_embedding)) AS max_semantic_score
                FROM blob_sentences bs
                WHERE bs.owner_id = p_owner_id
                GROUP BY bs.blob_id
            )
            SELECT a.id AS blob_id, a.content, a.namespace,
                COALESCE(a.fts_score, 0)::FLOAT AS fts_score,
                COALESCE(s.max_semantic_score, 0)::FLOAT AS semantic_score,
                a.exact_score::FLOAT AS exact_score,
                CASE WHEN a.exact_score > 0 THEN
                    (0.8 * a.exact_score + 0.1 * COALESCE(a.fts_score, 0) + 0.1 * COALESCE(s.max_semantic_score, 0))::FLOAT
                ELSE
                    (p_fts_weight * COALESCE(a.fts_score, 0) + (1 - p_fts_weight) * COALESCE(s.max_semantic_score, 0))::FLOAT
                END AS hybrid_score,
                a.events
            FROM all_blobs a
            LEFT JOIN semantic_results s ON a.id = s.blob_id
            ORDER BY hybrid_score DESC
            LIMIT p_limit;
        END;
        $$ LANGUAGE plpgsql
    """))

    # 6b. hybrid_search_emails
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION hybrid_search_emails(
            p_owner_id TEXT,
            p_query TEXT,
            p_query_embedding VECTOR(384),
            p_fts_weight FLOAT DEFAULT 0.5,
            p_limit INT DEFAULT 20,
            p_exact_pattern TEXT DEFAULT NULL
        )
        RETURNS TABLE (
            email_id UUID, gmail_id TEXT, thread_id TEXT, subject TEXT,
            from_email TEXT, from_name TEXT, to_email JSONB,
            date_timestamp BIGINT, body_plain TEXT, snippet TEXT,
            fts_score FLOAT, semantic_score FLOAT, exact_score FLOAT,
            hybrid_score FLOAT
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT
                e.id AS email_id, e.gmail_id, e.thread_id, e.subject,
                e.from_email, e.from_name, e.to_email::jsonb,
                e.date_timestamp, e.body_plain, e.snippet,
                COALESCE(ts_rank(e.tsv, plainto_tsquery('simple', p_query)), 0)::FLOAT AS fts_score,
                CASE WHEN e.embedding IS NOT NULL
                    THEN (1 - (e.embedding <=> p_query_embedding))::FLOAT
                    ELSE 0::FLOAT
                END AS semantic_score,
                CASE WHEN p_exact_pattern IS NOT NULL AND (
                    e.from_email ILIKE '%' || p_exact_pattern || '%' OR
                    e.to_email::TEXT ILIKE '%' || p_exact_pattern || '%'
                ) THEN 1.0::FLOAT ELSE 0.0::FLOAT
                END AS exact_score,
                CASE WHEN p_exact_pattern IS NOT NULL AND (
                    e.from_email ILIKE '%' || p_exact_pattern || '%' OR
                    e.to_email::TEXT ILIKE '%' || p_exact_pattern || '%'
                ) THEN (0.8 + 0.1 * COALESCE(ts_rank(e.tsv, plainto_tsquery('simple', p_query)), 0) +
                      0.1 * CASE WHEN e.embedding IS NOT NULL THEN (1 - (e.embedding <=> p_query_embedding)) ELSE 0 END)::FLOAT
                ELSE (p_fts_weight * COALESCE(ts_rank(e.tsv, plainto_tsquery('simple', p_query)), 0) +
                      (1 - p_fts_weight) * CASE WHEN e.embedding IS NOT NULL THEN (1 - (e.embedding <=> p_query_embedding)) ELSE 0 END)::FLOAT
                END AS hybrid_score
            FROM emails e
            WHERE e.owner_id = p_owner_id
            ORDER BY hybrid_score DESC
            LIMIT p_limit;
        END;
        $$ LANGUAGE plpgsql
    """))

    # 6c. get_events_by_attendee
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION get_events_by_attendee(
            p_owner_id TEXT,
            p_attendee_email TEXT,
            p_start_time TIMESTAMPTZ,
            p_end_time TIMESTAMPTZ
        ) RETURNS SETOF calendar_events AS $$
            SELECT * FROM calendar_events
            WHERE owner_id = p_owner_id
              AND start_time >= p_start_time
              AND start_time <= p_end_time
              AND (
                  attendees @> to_jsonb(ARRAY[LOWER(p_attendee_email)])
                  OR
                  EXISTS (
                      SELECT 1 FROM jsonb_array_elements(attendees) elem
                      WHERE LOWER(elem->>'email') = LOWER(p_attendee_email)
                  )
              )
            ORDER BY start_time;
        $$ LANGUAGE sql STABLE
    """))

    # ------------------------------------------------------------------
    # 7. Helper functions from read tracking
    # ------------------------------------------------------------------

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION get_message_read_stats(p_message_id TEXT)
        RETURNS TABLE (total_recipients BIGINT, total_reads BIGINT, unique_reads BIGINT, read_rate NUMERIC) AS $$
        BEGIN
            RETURN QUERY
            SELECT
                jsonb_array_length(m.read_events)::BIGINT as total_recipients,
                COALESCE(SUM((event->>'read_count')::INT), 0)::BIGINT as total_reads,
                COUNT(DISTINCT event->>'recipient')::BIGINT as unique_reads,
                CASE WHEN jsonb_array_length(m.read_events) > 0
                    THEN ROUND(COUNT(DISTINCT event->>'recipient')::NUMERIC / jsonb_array_length(m.read_events)::NUMERIC, 2)
                    ELSE 0
                END as read_rate
            FROM emails m
            CROSS JOIN LATERAL jsonb_array_elements(m.read_events) as event
            WHERE m.id = p_message_id::uuid
            GROUP BY m.id, m.read_events;
        END;
        $$ LANGUAGE plpgsql
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION cleanup_expired_sendgrid_mappings()
        RETURNS INTEGER AS $$
        DECLARE deleted_count INTEGER;
        BEGIN
            DELETE FROM sendgrid_message_mapping WHERE expires_at IS NOT NULL AND expires_at < NOW();
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$ LANGUAGE plpgsql
    """))

    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION cleanup_old_read_events(retention_days INTEGER DEFAULT 90)
        RETURNS INTEGER AS $$
        DECLARE deleted_count INTEGER;
        BEGIN
            DELETE FROM email_read_events WHERE created_at < NOW() - (retention_days || ' days')::INTERVAL;
            GET DIAGNOSTICS deleted_count = ROW_COUNT;
            RETURN deleted_count;
        END;
        $$ LANGUAGE plpgsql
    """))

    # ------------------------------------------------------------------
    # 8. Indexes
    # ------------------------------------------------------------------

    # --- Vector indexes ---
    op.execute(sa.text(
        "CREATE INDEX idx_blobs_embedding ON blobs USING hnsw(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_sentences_embedding ON blob_sentences USING hnsw(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_emails_embedding ON emails USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100)"
    ))

    # --- TSVECTOR / GIN indexes ---
    op.execute(sa.text("CREATE INDEX idx_blobs_tsv ON blobs USING GIN(tsv)"))
    op.execute(sa.text("CREATE INDEX idx_emails_tsv ON emails USING gin(tsv)"))
    op.execute(sa.text("CREATE INDEX idx_emails_fts_document ON emails USING GIN(fts_document)"))

    # --- Regular indexes ---

    # Blobs
    op.execute(sa.text("CREATE INDEX idx_blobs_namespace ON blobs(owner_id, namespace)"))
    op.execute(sa.text("CREATE INDEX idx_blobs_updated ON blobs(updated_at DESC)"))

    # Blob sentences
    op.execute(sa.text("CREATE INDEX idx_sentences_blob_id ON blob_sentences(blob_id)"))

    # Calendar events
    op.execute(sa.text("CREATE INDEX idx_calendar_events_owner ON calendar_events(owner_id)"))
    op.execute(sa.text("CREATE INDEX idx_calendar_events_time ON calendar_events(owner_id, start_time)"))
    op.execute(sa.text("CREATE INDEX idx_calendar_events_attendees_gin ON calendar_events USING GIN(attendees)"))

    # Emails
    op.execute(sa.text("CREATE INDEX idx_emails_thread ON emails(owner_id, thread_id)"))
    op.execute(sa.text("CREATE INDEX idx_emails_date ON emails(owner_id, date_timestamp DESC)"))
    op.execute(sa.text("CREATE INDEX idx_emails_read_events ON emails USING GIN(read_events)"))

    # Email read events
    op.execute(sa.text("CREATE INDEX idx_email_read_events_message_id ON email_read_events(message_id)"))
    op.execute(sa.text("CREATE INDEX idx_email_read_events_tracking_id ON email_read_events(tracking_id) WHERE tracking_id IS NOT NULL"))
    op.execute(sa.text("CREATE INDEX idx_email_read_events_sendgrid_msg_id ON email_read_events(sendgrid_message_id) WHERE sendgrid_message_id IS NOT NULL"))
    op.execute(sa.text("CREATE INDEX idx_email_read_events_owner_message ON email_read_events(owner_id, message_id)"))

    # SendGrid mapping
    op.execute(sa.text("CREATE INDEX idx_sendgrid_mapping_message_id ON sendgrid_message_mapping(message_id)"))
    op.execute(sa.text("CREATE INDEX idx_sendgrid_mapping_expires ON sendgrid_message_mapping(expires_at) WHERE expires_at IS NOT NULL"))

    # Background jobs
    op.execute(sa.text("CREATE UNIQUE INDEX idx_bg_jobs_no_duplicates ON background_jobs(owner_id, job_type, channel) WHERE status IN ('pending', 'running')"))
    op.execute(sa.text("CREATE INDEX idx_bg_jobs_pending ON background_jobs(status, created_at) WHERE status = 'pending'"))

    # Drafts
    op.execute(sa.text("CREATE INDEX idx_drafts_status ON drafts(owner_id, status)"))
    op.execute(sa.text("CREATE INDEX idx_drafts_thread ON drafts(thread_id)"))
    op.execute(sa.text("CREATE INDEX idx_drafts_created ON drafts(owner_id, created_at DESC)"))

    # Task items
    op.execute(sa.text("CREATE INDEX idx_task_items_contact ON task_items(owner_id, contact_email)"))

    # MrCall
    op.execute(sa.text("CREATE INDEX idx_mrcall_conversations_unprocessed ON mrcall_conversations(owner_id) WHERE memory_processed_at IS NULL"))
    op.execute(sa.text("CREATE INDEX idx_mrcall_conversations_started ON mrcall_conversations(owner_id, call_started_at DESC)"))
    op.execute(sa.text("CREATE INDEX idx_mrcall_conversations_business ON mrcall_conversations(owner_id, business_id)"))

    # Verification codes
    op.execute(sa.text("CREATE INDEX idx_verification_codes_lookup ON verification_codes(owner_id, phone_number, code) WHERE verified = FALSE"))

    # Triggers
    op.execute(sa.text("CREATE INDEX idx_triggers_owner ON triggers(owner_id)"))

    # Trigger events
    op.execute(sa.text("CREATE INDEX idx_trigger_events_status ON trigger_events(status, created_at)"))


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop indexes (most will cascade with tables, but explicit is safer)
    # ------------------------------------------------------------------

    # Trigger events
    op.execute(sa.text("DROP INDEX IF EXISTS idx_trigger_events_status"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_triggers_owner"))

    # Verification codes
    op.execute(sa.text("DROP INDEX IF EXISTS idx_verification_codes_lookup"))

    # MrCall
    op.execute(sa.text("DROP INDEX IF EXISTS idx_mrcall_conversations_business"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_mrcall_conversations_started"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_mrcall_conversations_unprocessed"))

    # Task items
    op.execute(sa.text("DROP INDEX IF EXISTS idx_task_items_contact"))

    # Drafts
    op.execute(sa.text("DROP INDEX IF EXISTS idx_drafts_created"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_drafts_thread"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_drafts_status"))

    # Background jobs
    op.execute(sa.text("DROP INDEX IF EXISTS idx_bg_jobs_pending"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_bg_jobs_no_duplicates"))

    # SendGrid mapping
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sendgrid_mapping_expires"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sendgrid_mapping_message_id"))

    # Email read events
    op.execute(sa.text("DROP INDEX IF EXISTS idx_email_read_events_owner_message"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_email_read_events_sendgrid_msg_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_email_read_events_tracking_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_email_read_events_message_id"))

    # Emails
    op.execute(sa.text("DROP INDEX IF EXISTS idx_emails_read_events"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_emails_date"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_emails_thread"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_emails_fts_document"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_emails_tsv"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_emails_embedding"))

    # Calendar events
    op.execute(sa.text("DROP INDEX IF EXISTS idx_calendar_events_attendees_gin"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_calendar_events_time"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_calendar_events_owner"))

    # Blob sentences
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sentences_blob_id"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_sentences_embedding"))

    # Blobs
    op.execute(sa.text("DROP INDEX IF EXISTS idx_blobs_updated"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_blobs_namespace"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_blobs_tsv"))
    op.execute(sa.text("DROP INDEX IF EXISTS idx_blobs_embedding"))

    # ------------------------------------------------------------------
    # Drop triggers
    # ------------------------------------------------------------------
    op.execute(sa.text("DROP TRIGGER IF EXISTS trigger_email_read_events_updated_at ON email_read_events"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS drafts_updated_at ON drafts"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS blobs_updated_at ON blobs"))

    # ------------------------------------------------------------------
    # Drop functions (reverse order of creation)
    # ------------------------------------------------------------------
    op.execute(sa.text("DROP FUNCTION IF EXISTS cleanup_old_read_events(INTEGER)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS cleanup_expired_sendgrid_mappings()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS get_message_read_stats(TEXT)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS get_events_by_attendee(TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS hybrid_search_emails(TEXT, TEXT, VECTOR, FLOAT, INT, TEXT)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS hybrid_search_blobs(TEXT, TEXT, VECTOR, TEXT, FLOAT, INT, TEXT)"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS update_email_read_events_timestamp()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS update_drafts_updated_at()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS update_blob_timestamp()"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS extract_identifiers(TEXT)"))

    # ------------------------------------------------------------------
    # Drop tables (FK-dependent tables first)
    # ------------------------------------------------------------------
    op.drop_table("trigger_events")
    op.drop_table("blob_sentences")

    # Tables without FKs (any order is fine)
    op.drop_table("contacts")
    op.drop_table("thread_analysis")
    op.drop_table("scheduled_jobs")
    op.drop_table("sync_state")
    op.drop_table("patterns")
    op.drop_table("triage_training_samples")
    op.drop_table("integration_providers")
    op.drop_table("importance_rules")
    op.drop_table("training_samples")
    op.drop_table("email_triage")
    op.drop_table("verification_codes")
    op.drop_table("mrcall_conversations")
    op.drop_table("sendgrid_message_mapping")
    op.drop_table("email_read_events")
    op.drop_table("user_notifications")
    op.drop_table("pipedrive_deals")
    op.drop_table("agent_prompts")
    op.drop_table("background_jobs")
    op.drop_table("task_items")
    op.drop_table("drafts")
    op.drop_table("sharing_auth")
    op.drop_table("triggers")
    op.drop_table("oauth_states")
    op.drop_table("oauth_tokens")
    op.drop_table("blobs")
    op.drop_table("calendar_events")
    op.drop_table("emails")

    # ------------------------------------------------------------------
    # Drop extensions
    # ------------------------------------------------------------------
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))
    op.execute(sa.text('DROP EXTENSION IF EXISTS "uuid-ossp"'))
