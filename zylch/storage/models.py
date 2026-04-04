"""SQLAlchemy ORM models for Zylch standalone (SQLite).

Standalone-only models using SQLite-compatible column types.
All PostgreSQL-specific types (UUID, JSONB, TSVECTOR, ARRAY, Vector)
are replaced with SQLite equivalents.
"""

import uuid as _uuid
from datetime import datetime, date, timezone
from typing import Any, Dict, Set

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base

# -------------------------------------------------------------------
# DictMixin — shared to_dict() for all models
# -------------------------------------------------------------------


class DictMixin:
    """Mixin providing to_dict() serialization.

    By default, skips large columns (embedding) unless
    include_vectors=True is passed.
    """

    _EXCLUDE_FROM_DICT: Set[str] = {"embedding"}

    def to_dict(self, include_vectors: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for col in self.__table__.columns:
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
            elif isinstance(val, bytes):
                # Skip raw embedding bytes in dict output
                continue
            else:
                d[col.name] = val
        return d


def _new_uuid() -> str:
    """Generate a new UUID4 string for primary keys."""
    return str(_uuid.uuid4())


def _utcnow() -> datetime:
    """Return current UTC datetime for column defaults."""
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------
# EMAILS
# -------------------------------------------------------------------


class Email(DictMixin, Base):
    __tablename__ = "emails"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    gmail_id = Column(Text, nullable=False)
    thread_id = Column(Text, nullable=False)
    from_email = Column(Text)
    from_name = Column(Text)
    to_email = Column(Text)
    cc_email = Column(Text)
    subject = Column(Text)
    date = Column(DateTime, nullable=False)
    date_timestamp = Column(Integer)
    snippet = Column(Text)
    body_plain = Column(Text)
    body_html = Column(Text)
    labels = Column(Text)
    message_id_header = Column(Text)
    in_reply_to = Column(Text)
    references = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    read_events = Column(JSON, default=list)
    memory_processed_at = Column(DateTime)
    embedding = Column(LargeBinary)
    task_processed_at = Column(DateTime)
    is_auto_reply = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "gmail_id",
            name="emails_owner_gmail_unique",
        ),
    )


# -------------------------------------------------------------------
# CALENDAR EVENTS
# -------------------------------------------------------------------


class CalendarEvent(DictMixin, Base):
    __tablename__ = "calendar_events"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    google_event_id = Column(Text, nullable=False)
    summary = Column(Text)
    description = Column(Text)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    location = Column(Text)
    attendees = Column(JSON)
    organizer_email = Column(Text)
    is_external = Column(Boolean, default=False)
    meet_link = Column(Text)
    calendar_id = Column(Text, default="primary")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    memory_processed_at = Column(DateTime)
    task_processed_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "google_event_id",
            name="calendar_events_owner_gid_unique",
        ),
    )


# -------------------------------------------------------------------
# BLOBS (entity memory)
# -------------------------------------------------------------------


class Blob(DictMixin, Base):
    __tablename__ = "blobs"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    namespace = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(LargeBinary)
    events = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class BlobSentence(DictMixin, Base):
    __tablename__ = "blob_sentences"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    blob_id = Column(
        String(36),
        ForeignKey("blobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id = Column(Text, nullable=False, index=True)
    sentence_text = Column(Text, nullable=False)
    embedding = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


# -------------------------------------------------------------------
# OAUTH TOKENS
# -------------------------------------------------------------------


class OAuthToken(DictMixin, Base):
    __tablename__ = "oauth_tokens"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False)
    provider = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    scopes = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    connection_status = Column(Text, default="connected")
    last_sync = Column(DateTime)
    error_message = Column(Text)
    display_name = Column(Text)
    credentials = Column(JSON)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "provider",
            name="oauth_tokens_owner_provider_unique",
        ),
    )


# -------------------------------------------------------------------
# OAUTH STATES
# -------------------------------------------------------------------


class OAuthState(DictMixin, Base):
    __tablename__ = "oauth_states"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    state = Column(Text, nullable=False, unique=True)
    owner_id = Column(Text, nullable=False)
    email = Column(Text)
    cli_callback = Column(Text)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    provider = Column(Text, default="google")
    metadata_ = Column("metadata", JSON)


# -------------------------------------------------------------------
# TRIGGERS
# -------------------------------------------------------------------


class Trigger(DictMixin, Base):
    __tablename__ = "triggers"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    trigger_type = Column(Text, nullable=False)
    instruction = Column(Text, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "trigger_type IN ("
            "'session_start', 'email_received', "
            "'sms_received', 'call_received', "
            "'whatsapp_received')",
            name="triggers_type_check",
        ),
    )


# -------------------------------------------------------------------
# TRIGGER EVENTS (queue)
# -------------------------------------------------------------------


class TriggerEvent(DictMixin, Base):
    __tablename__ = "trigger_events"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    event_type = Column(Text, nullable=False)
    event_data = Column(JSON, nullable=False, default=dict)
    status = Column(Text, default="pending")
    trigger_id = Column(
        String(36),
        ForeignKey("triggers.id"),
    )
    result = Column(JSON)
    created_at = Column(DateTime, default=_utcnow)
    processed_at = Column(DateTime)
    attempts = Column(Integer, default=0)
    last_error = Column(Text)

    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'email_received', 'sms_received', "
            "'call_received', 'whatsapp_received')",
            name="trigger_events_type_check",
        ),
        CheckConstraint(
            "status IN (" "'pending', 'processing', " "'completed', 'failed')",
            name="trigger_events_status_check",
        ),
    )


# -------------------------------------------------------------------
# SHARING
# -------------------------------------------------------------------


class SharingAuth(DictMixin, Base):
    __tablename__ = "sharing_auth"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    sender_id = Column(Text, nullable=False)
    sender_email = Column(Text, nullable=False)
    recipient_email = Column(Text, nullable=False)
    status = Column(Text, default="pending")
    pending_intel = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)
    authorized_at = Column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "sender_id",
            "recipient_email",
            name="sharing_auth_sender_recipient_unique",
        ),
        CheckConstraint(
            "status IN ('pending', 'authorized', 'revoked')",
            name="sharing_auth_status_check",
        ),
    )


# -------------------------------------------------------------------
# DRAFTS
# -------------------------------------------------------------------


class Draft(DictMixin, Base):
    __tablename__ = "drafts"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    to_addresses = Column(JSON, default=list)
    cc_addresses = Column(JSON, default=list)
    bcc_addresses = Column(JSON, default=list)
    subject = Column(Text)
    body = Column(Text)
    body_format = Column(Text, default="html")
    in_reply_to = Column(Text)
    references = Column("references", JSON)
    thread_id = Column(Text)
    original_message_id = Column(Text)
    status = Column(Text, default="draft")
    provider = Column(Text)
    sent_at = Column(DateTime)
    sent_message_id = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)

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


# -------------------------------------------------------------------
# TASK ITEMS
# -------------------------------------------------------------------


class TaskItem(DictMixin, Base):
    __tablename__ = "task_items"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    event_type = Column(Text, nullable=False)
    event_id = Column(Text, nullable=False)
    contact_email = Column(Text)
    contact_name = Column(Text)
    action_required = Column(Boolean, default=False)
    urgency = Column(Text)
    reason = Column(Text)
    suggested_action = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    analyzed_at = Column(DateTime)
    completed_at = Column(DateTime)
    sources = Column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "event_type",
            "event_id",
            name="task_items_owner_event_unique",
        ),
    )


# -------------------------------------------------------------------
# BACKGROUND JOBS
# -------------------------------------------------------------------


class BackgroundJob(DictMixin, Base):
    __tablename__ = "background_jobs"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    business_id = Column(Text, nullable=True, index=True)
    job_type = Column(Text, nullable=False)
    channel = Column(Text)
    status = Column(Text, nullable=False, default="pending")
    progress_pct = Column(Integer, default=0)
    items_processed = Column(Integer, default=0)
    total_items = Column(Integer)
    status_message = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    last_error = Column(Text)
    retry_count = Column(Integer, default=0)
    result = Column(JSON, default=dict)
    params = Column(JSON, default=dict)


# -------------------------------------------------------------------
# AGENT PROMPTS
# -------------------------------------------------------------------


class AgentPrompt(DictMixin, Base):
    __tablename__ = "agent_prompts"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False)
    agent_type = Column(Text, nullable=False)
    agent_prompt = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "agent_type",
            name="agent_prompts_owner_type_unique",
        ),
    )


# -------------------------------------------------------------------
# USER NOTIFICATIONS
# -------------------------------------------------------------------


class UserNotification(DictMixin, Base):
    __tablename__ = "user_notifications"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    message = Column(Text, nullable=False)
    notification_type = Column(Text, default="warning")
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)


# -------------------------------------------------------------------
# EMAIL READ EVENTS (tracking)
# -------------------------------------------------------------------


class EmailReadEvent(DictMixin, Base):
    __tablename__ = "email_read_events"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    tracking_id = Column(Text)
    sendgrid_message_id = Column(Text)
    owner_id = Column(Text, nullable=False)
    message_id = Column(Text, nullable=False)
    recipient_email = Column(Text, nullable=False)
    tracking_source = Column(Text, nullable=False)
    read_count = Column(Integer, default=0)
    first_read_at = Column(DateTime)
    last_read_at = Column(DateTime)
    user_agents = Column(JSON)
    ip_addresses = Column(JSON)
    sendgrid_event_data = Column(JSON)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        CheckConstraint(
            "tracking_source IN (" "'sendgrid_webhook', 'custom_pixel')",
            name="email_read_events_source_check",
        ),
    )


# -------------------------------------------------------------------
# SENDGRID MESSAGE MAPPING
# -------------------------------------------------------------------


class SendgridMessageMapping(DictMixin, Base):
    __tablename__ = "sendgrid_message_mapping"

    sendgrid_message_id = Column(Text, primary_key=True)
    message_id = Column(Text, nullable=False)
    owner_id = Column(Text, nullable=False)
    recipient_email = Column(Text, nullable=False)
    campaign_id = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    expires_at = Column(DateTime)


# -------------------------------------------------------------------
# WHATSAPP MESSAGES (neonize / whatsmeow)
# -------------------------------------------------------------------


class WhatsAppMessage(DictMixin, Base):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (UniqueConstraint("owner_id", "message_id", name="uq_wa_owner_message"),)

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    message_id = Column(
        Text,
        nullable=False,
    )
    chat_jid = Column(Text, nullable=False, index=True)
    sender_jid = Column(Text, nullable=False)
    sender_name = Column(Text)
    text = Column(Text)
    timestamp = Column(DateTime, nullable=False, index=True)
    is_from_me = Column(Boolean, default=False)
    is_group = Column(Boolean, default=False)
    media_type = Column(Text)
    status = Column(Text)
    created_at = Column(DateTime, default=_utcnow)
    memory_processed_at = Column(DateTime)
    task_processed_at = Column(DateTime)


# -------------------------------------------------------------------
# WHATSAPP CONTACTS (neonize / whatsmeow)
# -------------------------------------------------------------------


class WhatsAppContact(DictMixin, Base):
    __tablename__ = "whatsapp_contacts"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    jid = Column(Text, nullable=False)
    phone_number = Column(Text)
    name = Column(Text)
    push_name = Column(Text)
    last_message_at = Column(DateTime)
    synced_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "jid",
            name="wa_contact_owner_jid_unique",
        ),
    )


# -------------------------------------------------------------------
# MRCALL CONVERSATIONS
# -------------------------------------------------------------------


class MrcallConversation(DictMixin, Base):
    __tablename__ = "mrcall_conversations"

    # NOTE: TEXT PK, not UUID
    id = Column(Text, primary_key=True)
    owner_id = Column(Text, nullable=False, index=True)
    business_id = Column(Text, nullable=False)
    contact_phone = Column(Text)
    contact_name = Column(Text)
    call_duration_ms = Column(Integer)
    call_started_at = Column(DateTime)
    subject = Column(Text)
    body = Column(JSON)
    custom_values = Column(JSON)
    memory_processed_at = Column(DateTime)
    raw_data = Column(JSON)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


# -------------------------------------------------------------------
# SYNC STATE
# -------------------------------------------------------------------


class SyncState(DictMixin, Base):
    __tablename__ = "sync_state"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, unique=True)
    history_id = Column(Text)
    last_sync = Column(DateTime)
    full_sync_completed = Column(DateTime)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


# -------------------------------------------------------------------
# PATTERNS (entity behavioral patterns)
# -------------------------------------------------------------------


class Pattern(DictMixin, Base):
    __tablename__ = "patterns"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    namespace = Column(Text, nullable=False)
    skill = Column(Text, nullable=False)
    intent = Column(Text, nullable=False)
    context = Column(JSON)
    action = Column(JSON)
    outcome = Column(Text)
    contact_id = Column(Text)
    confidence = Column(Float, default=0.5)
    times_applied = Column(Integer, default=0)
    times_successful = Column(Integer, default=0)
    state = Column(Text, default="active")
    embedding = Column(LargeBinary)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    last_accessed = Column(DateTime)


# -------------------------------------------------------------------
# CONTACTS
# -------------------------------------------------------------------


class Contact(DictMixin, Base):
    __tablename__ = "contacts"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    email = Column(Text)
    name = Column(Text)
    phone = Column(Text)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


# -------------------------------------------------------------------
# ERROR LOGS
# -------------------------------------------------------------------


class ErrorLog(DictMixin, Base):
    """Log of API errors for debugging and monitoring."""

    __tablename__ = "error_logs"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    business_id = Column(Text, index=True)
    session_id = Column(Text, index=True)
    error_type = Column(Text, nullable=False)
    error_code = Column(Integer)
    error_message = Column(Text, nullable=False)
    user_message = Column(Text)
    request_id = Column(Text)
    context = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
