"""SQLAlchemy ORM models for Zylch database.

Maps all 25+ tables from the PostgreSQL schema. Each model includes a
to_dict() method (via DictMixin) that serializes to the same dict format
the Supabase REST API returned, so callers don't need to change.

Schema source of truth: docs/DB_SCHEMA.sql + zylch/storage/migrations/*.sql
"""

import uuid as _uuid
from datetime import datetime, date
from typing import Any, Dict, Optional, Set

import numpy as np
from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Float, ForeignKey,
    Integer, Numeric, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID

from .database import Base

# pgvector column type — optional import with fallback
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # Allow models to be imported even without pgvector installed
    # (e.g. for alembic autogenerate on a machine without pgvector)
    Vector = None  # type: ignore


# ---------------------------------------------------------------------------
# DictMixin — shared to_dict() for all models
# ---------------------------------------------------------------------------

class DictMixin:
    """Mixin providing to_dict() serialization matching Supabase REST output.

    By default, skips large columns (tsv, embedding, fts_document) unless
    include_vectors=True is passed.
    """

    _EXCLUDE_FROM_DICT: Set[str] = {"tsv", "embedding", "fts_document"}

    def to_dict(self, include_vectors: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for col in self.__table__.columns:  # type: ignore[attr-defined]
            if not include_vectors and col.name in self._EXCLUDE_FROM_DICT:
                continue
            val = getattr(self, col.name)
            # Serialize types that aren't JSON-native
            if isinstance(val, datetime):
                d[col.name] = val.isoformat()
            elif isinstance(val, date):
                d[col.name] = val.isoformat()
            elif isinstance(val, _uuid.UUID):
                d[col.name] = str(val)
            elif isinstance(val, np.ndarray):
                d[col.name] = val.tolist()
            elif hasattr(val, "tolist"):  # pgvector arrays
                d[col.name] = val.tolist()
            else:
                d[col.name] = val
        return d


# ---------------------------------------------------------------------------
# EMAILS
# ---------------------------------------------------------------------------

class Email(DictMixin, Base):
    __tablename__ = "emails"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    gmail_id = Column(Text, nullable=False)
    thread_id = Column(Text, nullable=False)
    from_email = Column(Text)
    from_name = Column(Text)
    to_email = Column(Text)
    cc_email = Column(Text)
    subject = Column(Text)
    date = Column(DateTime(timezone=True), nullable=False)
    date_timestamp = Column(Integer)  # bigint in PG, Integer in SA handles it
    snippet = Column(Text)
    body_plain = Column(Text)
    body_html = Column(Text)
    labels = Column(Text)
    message_id_header = Column(Text)
    in_reply_to = Column(Text)
    references = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    fts_document = Column(TSVECTOR)  # server-managed generated column
    read_events = Column(JSONB, server_default=text("'[]'::jsonb"))
    memory_processed_at = Column(DateTime(timezone=True))
    embedding = Column(Vector(384) if Vector else Text)  # pgvector VECTOR(384)
    tsv = Column(TSVECTOR)  # server-managed generated column
    task_processed_at = Column(DateTime(timezone=True))
    is_auto_reply = Column(Boolean, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("owner_id", "gmail_id", name="emails_owner_gmail_unique"),
    )


# ---------------------------------------------------------------------------
# CALENDAR EVENTS
# ---------------------------------------------------------------------------

class CalendarEvent(DictMixin, Base):
    __tablename__ = "calendar_events"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    google_event_id = Column(Text, nullable=False)
    summary = Column(Text)
    description = Column(Text)
    start_time = Column(DateTime(timezone=True))
    end_time = Column(DateTime(timezone=True))
    location = Column(Text)
    attendees = Column(JSONB)
    organizer_email = Column(Text)
    is_external = Column(Boolean, server_default=text("false"))
    meet_link = Column(Text)
    calendar_id = Column(Text, server_default=text("'primary'"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    memory_processed_at = Column(DateTime(timezone=True))
    task_processed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("owner_id", "google_event_id", name="calendar_events_owner_gid_unique"),
    )


# ---------------------------------------------------------------------------
# BLOBS (entity memory)
# ---------------------------------------------------------------------------

class Blob(DictMixin, Base):
    __tablename__ = "blobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    owner_id = Column(Text, nullable=False, index=True)
    namespace = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(384) if Vector else Text)
    events = Column(JSONB, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    tsv = Column(TSVECTOR)  # GENERATED ALWAYS — created in Alembic migration


class BlobSentence(DictMixin, Base):
    __tablename__ = "blob_sentences"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    blob_id = Column(UUID(as_uuid=True), ForeignKey("blobs.id", ondelete="CASCADE"), nullable=False)
    owner_id = Column(Text, nullable=False, index=True)
    sentence_text = Column(Text, nullable=False)
    embedding = Column(Vector(384) if Vector else Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# OAUTH TOKENS
# ---------------------------------------------------------------------------

class OAuthToken(DictMixin, Base):
    __tablename__ = "oauth_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    scopes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    connection_status = Column(Text, server_default=text("'connected'"))
    last_sync = Column(DateTime(timezone=True))
    error_message = Column(Text)
    display_name = Column(Text)
    credentials = Column(JSONB)

    __table_args__ = (
        UniqueConstraint("owner_id", "provider", name="oauth_tokens_owner_provider_unique"),
    )


# ---------------------------------------------------------------------------
# OAUTH STATES
# ---------------------------------------------------------------------------

class OAuthState(DictMixin, Base):
    __tablename__ = "oauth_states"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    state = Column(Text, nullable=False, unique=True)
    owner_id = Column(Text, nullable=False)
    email = Column(Text)
    cli_callback = Column(Text)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    provider = Column(Text, server_default=text("'google'"))
    metadata_ = Column("metadata", JSONB)  # 'metadata' is reserved in SA


# ---------------------------------------------------------------------------
# TRIGGERS
# ---------------------------------------------------------------------------

class Trigger(DictMixin, Base):
    __tablename__ = "triggers"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    trigger_type = Column(Text, nullable=False)
    instruction = Column(Text, nullable=False)
    active = Column(Boolean, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ('session_start', 'email_received', 'sms_received', 'call_received')",
            name="triggers_type_check",
        ),
    )


# ---------------------------------------------------------------------------
# TRIGGER EVENTS (queue)
# ---------------------------------------------------------------------------

class TriggerEvent(DictMixin, Base):
    __tablename__ = "trigger_events"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    event_type = Column(Text, nullable=False)
    event_data = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(Text, server_default=text("'pending'"))
    trigger_id = Column(UUID(as_uuid=True), ForeignKey("triggers.id"))
    result = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    processed_at = Column(DateTime(timezone=True))
    attempts = Column(Integer, server_default=text("0"))
    last_error = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('email_received', 'sms_received', 'call_received')",
            name="trigger_events_type_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="trigger_events_status_check",
        ),
    )


# ---------------------------------------------------------------------------
# SHARING
# ---------------------------------------------------------------------------

class SharingAuth(DictMixin, Base):
    __tablename__ = "sharing_auth"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    sender_id = Column(Text, nullable=False)
    sender_email = Column(Text, nullable=False)
    recipient_email = Column(Text, nullable=False)
    status = Column(Text, server_default=text("'pending'"))
    pending_intel = Column(JSONB, server_default=text("'[]'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    authorized_at = Column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("sender_id", "recipient_email", name="sharing_auth_sender_recipient_unique"),
        CheckConstraint(
            "status IN ('pending', 'authorized', 'revoked')",
            name="sharing_auth_status_check",
        ),
    )


# ---------------------------------------------------------------------------
# DRAFTS
# ---------------------------------------------------------------------------

class Draft(DictMixin, Base):
    __tablename__ = "drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    to_addresses = Column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    cc_addresses = Column(ARRAY(Text), server_default=text("'{}'::text[]"))
    bcc_addresses = Column(ARRAY(Text), server_default=text("'{}'::text[]"))
    subject = Column(Text)
    body = Column(Text)
    body_format = Column(Text, server_default=text("'html'"))
    in_reply_to = Column(Text)
    references = Column("references", ARRAY(Text))  # 'references' is a reserved word in PG
    thread_id = Column(Text)
    original_message_id = Column(Text)
    status = Column(Text, server_default=text("'draft'"))
    provider = Column(Text)
    sent_at = Column(DateTime(timezone=True))
    sent_message_id = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "body_format IN ('html', 'plain')",
            name="drafts_body_format_check",
        ),
        CheckConstraint(
            "status IN ('draft', 'sending', 'sent', 'failed')",
            name="drafts_status_check",
        ),
        CheckConstraint(
            "provider IN ('google', 'microsoft')",
            name="drafts_provider_check",
        ),
    )


# ---------------------------------------------------------------------------
# TASK ITEMS
# ---------------------------------------------------------------------------

class TaskItem(DictMixin, Base):
    __tablename__ = "task_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    owner_id = Column(Text, nullable=False, index=True)
    event_type = Column(Text, nullable=False)
    event_id = Column(Text, nullable=False)
    contact_email = Column(Text)
    contact_name = Column(Text)
    action_required = Column(Boolean, nullable=False, server_default=text("false"))
    urgency = Column(Text)
    reason = Column(Text)
    suggested_action = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    analyzed_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    sources = Column(JSONB, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        UniqueConstraint("owner_id", "event_type", "event_id", name="task_items_owner_event_unique"),
    )


# ---------------------------------------------------------------------------
# BACKGROUND JOBS
# ---------------------------------------------------------------------------

class BackgroundJob(DictMixin, Base):
    __tablename__ = "background_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    business_id = Column(Text, nullable=True, index=True)
    job_type = Column(Text, nullable=False)
    channel = Column(Text)
    status = Column(Text, nullable=False, server_default=text("'pending'"))
    progress_pct = Column(Integer, server_default=text("0"))
    items_processed = Column(Integer, server_default=text("0"))
    total_items = Column(Integer)
    status_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    retry_count = Column(Integer, server_default=text("0"))
    result = Column(JSONB, server_default=text("'{}'::jsonb"))
    params = Column(JSONB, server_default=text("'{}'::jsonb"))

    # Note: partial unique index (owner_id, job_type, channel WHERE status IN ('pending','running'))
    # is created in Alembic migration, not expressible as __table_args__


# ---------------------------------------------------------------------------
# AGENT PROMPTS
# ---------------------------------------------------------------------------

class AgentPrompt(DictMixin, Base):
    __tablename__ = "agent_prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False)
    agent_type = Column(Text, nullable=False)
    agent_prompt = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("owner_id", "agent_type", name="agent_prompts_owner_type_unique"),
    )


# ---------------------------------------------------------------------------
# PIPEDRIVE DEALS
# ---------------------------------------------------------------------------

class PipedriveDeal(DictMixin, Base):
    __tablename__ = "pipedrive_deals"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    deal_id = Column(Text, nullable=False)
    title = Column(Text)
    person_name = Column(Text)
    org_name = Column(Text)
    value = Column(Numeric)
    currency = Column(Text, server_default=text("'USD'"))
    status = Column(Text)
    stage_name = Column(Text)
    pipeline_name = Column(Text)
    expected_close_date = Column(Date)
    deal_data = Column(JSONB)
    memory_processed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("owner_id", "deal_id", name="pipedrive_deals_owner_deal_unique"),
    )


# ---------------------------------------------------------------------------
# USER NOTIFICATIONS
# ---------------------------------------------------------------------------

class UserNotification(DictMixin, Base):
    __tablename__ = "user_notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    message = Column(Text, nullable=False)
    notification_type = Column(Text, server_default=text("'warning'"))
    read = Column(Boolean, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# EMAIL READ EVENTS (tracking)
# ---------------------------------------------------------------------------

class EmailReadEvent(DictMixin, Base):
    __tablename__ = "email_read_events"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tracking_id = Column(Text)
    sendgrid_message_id = Column(Text)
    owner_id = Column(Text, nullable=False)
    message_id = Column(Text, nullable=False)
    recipient_email = Column(Text, nullable=False)
    tracking_source = Column(Text, nullable=False)
    read_count = Column(Integer, server_default=text("0"))
    first_read_at = Column(DateTime(timezone=True))
    last_read_at = Column(DateTime(timezone=True))
    user_agents = Column(ARRAY(Text))
    ip_addresses = Column(ARRAY(Text))
    sendgrid_event_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "tracking_source IN ('sendgrid_webhook', 'custom_pixel')",
            name="email_read_events_source_check",
        ),
    )


# ---------------------------------------------------------------------------
# SENDGRID MESSAGE MAPPING
# ---------------------------------------------------------------------------

class SendgridMessageMapping(DictMixin, Base):
    __tablename__ = "sendgrid_message_mapping"

    sendgrid_message_id = Column(Text, primary_key=True)
    message_id = Column(Text, nullable=False)
    owner_id = Column(Text, nullable=False)
    recipient_email = Column(Text, nullable=False)
    campaign_id = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    expires_at = Column(DateTime(timezone=True), server_default=text("now() + interval '90 days'"))


# ---------------------------------------------------------------------------
# MRCALL CONVERSATIONS
# ---------------------------------------------------------------------------

class MrcallConversation(DictMixin, Base):
    __tablename__ = "mrcall_conversations"

    # NOTE: TEXT PK, not UUID
    id = Column(Text, primary_key=True)
    owner_id = Column(Text, nullable=False, index=True)
    business_id = Column(Text, nullable=False)
    contact_phone = Column(Text)
    contact_name = Column(Text)
    call_duration_ms = Column(Integer)
    call_started_at = Column(DateTime(timezone=True))
    subject = Column(Text)
    body = Column(JSONB)
    custom_values = Column(JSONB)
    memory_processed_at = Column(DateTime(timezone=True))
    raw_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# VERIFICATION CODES
# ---------------------------------------------------------------------------

class VerificationCode(DictMixin, Base):
    __tablename__ = "verification_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    owner_id = Column(Text, nullable=False)
    phone_number = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    context = Column(Text)
    expires_in_minutes = Column(Integer, server_default=text("15"))
    expires_at = Column(DateTime(timezone=True), nullable=False)
    verified = Column(Boolean, server_default=text("false"))
    verified_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# EMAIL TRIAGE
# ---------------------------------------------------------------------------

class EmailTriage(DictMixin, Base):
    __tablename__ = "email_triage"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False)
    thread_id = Column(Text, nullable=False)
    needs_human_attention = Column(Boolean, nullable=False, server_default=text("false"))
    triage_category = Column(Text)
    reason = Column(Text)
    is_real_customer = Column(Boolean)
    is_actionable = Column(Boolean)
    is_time_sensitive = Column(Boolean)
    is_resolved = Column(Boolean)
    is_cold_outreach = Column(Boolean)
    is_automated = Column(Boolean)
    suggested_action = Column(Text)
    deadline_detected = Column(Date)
    model_used = Column(Text)
    prompt_version = Column(Text)
    confidence_score = Column(Float)
    user_override = Column(Boolean, server_default=text("false"))
    user_override_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("owner_id", "thread_id", name="email_triage_owner_thread_unique"),
        CheckConstraint(
            "triage_category IN ('urgent', 'normal', 'low', 'noise')",
            name="email_triage_category_check",
        ),
    )


# ---------------------------------------------------------------------------
# TRAINING SAMPLES
# ---------------------------------------------------------------------------

class TrainingSample(DictMixin, Base):
    __tablename__ = "training_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False)
    sample_hash = Column(Text, nullable=False, unique=True)
    question_type = Column(Text, nullable=False)
    anonymized_input = Column(Text, nullable=False)
    model_answer = Column(JSONB, nullable=False)
    thread_length = Column(Integer)
    has_attachments = Column(Boolean)
    email_domain_category = Column(Text)
    importance_rule_matched = Column(Text)
    used_in_training = Column(Boolean, server_default=text("false"))
    training_batch_id = Column(Text)
    model_version_trained = Column(Text)
    user_override = Column(Boolean, server_default=text("false"))
    user_override_reason = Column(Text)
    confidence_score = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "question_type IN ('triage', 'classification', 'action')",
            name="training_samples_type_check",
        ),
    )


# ---------------------------------------------------------------------------
# IMPORTANCE RULES
# ---------------------------------------------------------------------------

class ImportanceRule(DictMixin, Base):
    __tablename__ = "importance_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False)
    account_id = Column(UUID(as_uuid=True))
    name = Column(Text, nullable=False)
    condition = Column(Text, nullable=False)
    importance = Column(Text, nullable=False)
    reason = Column(Text)
    priority = Column(Integer, server_default=text("0"))
    enabled = Column(Boolean, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("owner_id", "account_id", "name", name="importance_rules_owner_account_name_unique"),
        CheckConstraint(
            "importance IN ('high', 'normal', 'low')",
            name="importance_rules_importance_check",
        ),
    )


# ---------------------------------------------------------------------------
# INTEGRATION PROVIDERS (registry)
# ---------------------------------------------------------------------------

class IntegrationProvider(DictMixin, Base):
    __tablename__ = "integration_providers"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    provider_key = Column(Text, nullable=False, unique=True)
    display_name = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    icon_url = Column(Text)
    description = Column(Text)
    requires_oauth = Column(Boolean, server_default=text("true"))
    oauth_url = Column(Text)
    config_fields = Column(JSONB)
    is_available = Column(Boolean, server_default=text("true"))
    documentation_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# TRIAGE TRAINING SAMPLES (user feedback)
# ---------------------------------------------------------------------------

class TriageTrainingSample(DictMixin, Base):
    __tablename__ = "triage_training_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False)
    thread_id = Column(Text, nullable=False)
    email_data = Column(JSONB, nullable=False)
    predicted_verdict = Column(JSONB, nullable=False)
    actual_verdict = Column(JSONB)
    feedback_type = Column(Text)
    used_for_training = Column(Boolean, server_default=text("false"))
    training_batch_id = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "feedback_type IN ('correction', 'confirmation')",
            name="triage_training_feedback_check",
        ),
    )


# ---------------------------------------------------------------------------
# PATTERNS (entity behavioral patterns)
# ---------------------------------------------------------------------------

class Pattern(DictMixin, Base):
    __tablename__ = "patterns"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    namespace = Column(Text, nullable=False)
    skill = Column(Text, nullable=False)
    intent = Column(Text, nullable=False)
    context = Column(JSONB)
    action = Column(JSONB)
    outcome = Column(Text)
    contact_id = Column(Text)
    confidence = Column(Float, server_default=text("0.5"))
    times_applied = Column(Integer, server_default=text("0"))
    times_successful = Column(Integer, server_default=text("0"))
    state = Column(Text, server_default=text("'active'"))
    embedding = Column(Vector(384) if Vector else Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
    last_accessed = Column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# SYNC STATE
# ---------------------------------------------------------------------------

class SyncState(DictMixin, Base):
    __tablename__ = "sync_state"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, unique=True)
    history_id = Column(Text)
    last_sync = Column(DateTime(timezone=True))
    full_sync_completed = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# SCHEDULED JOBS (legacy — may be unused)
# ---------------------------------------------------------------------------

class ScheduledJob(DictMixin, Base):
    __tablename__ = "scheduled_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    job_type = Column(Text, nullable=False)
    message = Column(Text, nullable=False)
    callback_type = Column(Text, nullable=False, server_default=text("'notification'"))
    metadata_ = Column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    run_at = Column(DateTime(timezone=True))
    cron_expression = Column(Text)
    interval_seconds = Column(Integer)
    condition_key = Column(Text)
    timeout_seconds = Column(Integer)
    status = Column(Text, nullable=False, server_default=text("'pending'"))
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    run_count = Column(Integer, server_default=text("0"))
    last_error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# THREAD ANALYSIS (legacy — may be unused)
# ---------------------------------------------------------------------------

class ThreadAnalysis(DictMixin, Base):
    __tablename__ = "thread_analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    thread_id = Column(Text, nullable=False)
    contact_email = Column(Text)
    contact_name = Column(Text)
    last_email_date = Column(DateTime(timezone=True))
    last_email_direction = Column(Text)
    analysis = Column(JSONB)
    needs_action = Column(Boolean, server_default=text("false"))
    task_description = Column(Text)
    priority = Column(Integer)
    manually_closed = Column(Boolean, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))


# ---------------------------------------------------------------------------
# CONTACTS
# ---------------------------------------------------------------------------

class Contact(DictMixin, Base):
    __tablename__ = "contacts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    owner_id = Column(Text, nullable=False, index=True)
    email = Column(Text)
    name = Column(Text)
    phone = Column(Text)
    metadata_ = Column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), server_default=text("now()"))
