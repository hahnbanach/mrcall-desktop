"""SQLAlchemy ORM models for Zylch standalone (SQLite).

13 models. SQLite-compatible column types only.
"""

import uuid as _uuid
from datetime import datetime, date
from typing import Any, Dict, Set

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
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
    return datetime.utcnow()


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
    has_attachments = Column(Boolean, default=False, nullable=False, index=True)
    attachment_filenames = Column(JSON, default=list)
    # 2026-04-17: per-row pin/read flags backing the desktop Email tab.
    # `pinned_at` is non-NULL when the thread is pinned by the user; the
    # `emails.pin` RPC sets/clears it on ALL rows of a thread at once.
    # `read_at` is a lightweight "opened in UI" marker (fire-and-forget
    # from the renderer). Both have indexes so thread-grouped queries can
    # filter/sort efficiently.
    pinned_at = Column(DateTime, nullable=True, index=True)
    read_at = Column(DateTime, nullable=True, index=True)
    # 2026-04-21: thread-level archive / local soft-delete flags backing the
    # desktop Inbox "Archive" and "Delete" buttons.
    #   archived_at: non-NULL once the user archived the thread. The RPC
    #     additionally performs an IMAP MOVE to the provider's archive folder.
    #   deleted_at: non-NULL once the user soft-deleted locally. Unlike
    #     archive, delete NEVER touches IMAP — the server copy is preserved
    #     so task provenance / linked references survive.
    # Both hide the row from inbox/sent list views. Per-row (not per-thread)
    # so an archive of thread X doesn't mask a brand-new reply that arrives
    # after the fact; list queries apply the filter at the row level before
    # thread grouping.
    archived_at = Column(DateTime, nullable=True, index=True)
    deleted_at = Column(DateTime, nullable=True, index=True)

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
# EMAIL ↔ BLOB / CALENDAR ↔ BLOB ASSOCIATION TABLES
# -------------------------------------------------------------------
#
# 2026-05-06 (Fase 3.1): replace the F7 hybrid_search bridge with a
# deterministic index of "which blobs were extracted from which
# email/event". The memory worker writes these on every successful
# upsert. The task worker reads them in _collect to find topical
# siblings without similarity search — exact lookup, no thresholds,
# no notification-anchor noise.
#
# The pair (email_id, blob_id) is the natural key; same for
# (event_id, blob_id). A single blob may be linked to many emails
# (the canonical "Carmine Salamone PERSON" blob is referenced by
# every email Salamone wrote) and vice-versa (one email can extract
# multiple entities).


class EmailBlob(Base):
    __tablename__ = "email_blobs"

    email_id = Column(
        String(36),
        ForeignKey("emails.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blob_id = Column(
        String(36),
        ForeignKey("blobs.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    owner_id = Column(Text, nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)


class CalendarBlob(Base):
    __tablename__ = "calendar_blobs"

    event_id = Column(
        String(36),
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    blob_id = Column(
        String(36),
        ForeignKey("blobs.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    owner_id = Column(Text, nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)


# -------------------------------------------------------------------
# PERSON IDENTIFIERS — cross-channel identity index
# -------------------------------------------------------------------
#
# 2026-05-07 (whatsapp-pipeline-parity, Phase 1a): structured index of
# identifiers (email / phone / lid) extracted from each PERSON-blob's
# `#IDENTIFIERS` block. Queried by future cross-channel match logic so
# a WhatsApp message from +393395... merges into the same blob already
# carrying that phone from a prior email signature.
#
# Phase 1a is additive only: rows are written by the memory worker on
# every successful upsert; nothing reads them yet. Phase 1b switches
# `_upsert_entity` to query this index before falling back to cosine.
#
# kind ∈ {'email', 'phone', 'lid'}. Names are NOT indexed here in v1
# (false-merge risk on common names: two distinct "Mario Rossi"). Names
# may be added later as a weak-confidence kind requiring embedding
# co-confirmation.


class PersonIdentifier(Base):
    __tablename__ = "person_identifiers"

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    blob_id = Column(
        String(36),
        ForeignKey("blobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(Text, nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "kind",
            "value",
            "blob_id",
            name="person_identifiers_owner_kind_value_blob_unique",
        ),
    )


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
    attachment_paths = Column(JSON, default=list)
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
    close_note = Column(Text)
    sources = Column(JSON, default=dict)
    pinned = Column(Boolean, default=False, nullable=False, index=True)
    # 2026-05-06: epoch-seconds (UTC) until which the dedup sweep should
    # ignore this task. Set to now+7d when the user reopens a task, so a
    # subsequent dedup sweep does not immediately re-close it. Compared
    # against time.time() — NULL means no skip. Worker:
    # zylch.workers.task_dedup_sweep.
    dedup_skip_until = Column(BigInteger)
    # 2026-05-06 (Fase 3.2): semantic channel the task originated
    # from. Distinct from event_type — `event_type` is the technical
    # event we built the task off (always "email" or "calendar"
    # today), while `channel` is the conceptual surface ("phone" for
    # missed-call notifications routed via email,
    # "whatsapp" once the WA pipeline writes tasks). NULL = unknown,
    # treated as 'email' by the UI filter for backward compat. Index
    # used by the renderer's channel filter and by the age-based
    # auto-close (3.3) which only sweeps `channel='phone'`.
    channel = Column(Text, index=True)

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
    last_dream_at = Column(DateTime)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


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
# WHATSAPP MESSAGES (neonize / whatsmeow)
# -------------------------------------------------------------------


class WhatsAppMessage(DictMixin, Base):
    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "message_id",
            name="uq_wa_owner_message",
        ),
    )

    id = Column(
        String(36),
        primary_key=True,
        default=_new_uuid,
    )
    owner_id = Column(Text, nullable=False, index=True)
    message_id = Column(Text, nullable=False)
    chat_jid = Column(Text, nullable=False, index=True)
    sender_jid = Column(Text, nullable=False)
    sender_name = Column(Text)
    text = Column(Text)
    timestamp = Column(
        DateTime,
        nullable=False,
        index=True,
    )
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
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "jid",
            name="wa_contact_owner_jid_unique",
        ),
    )

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
