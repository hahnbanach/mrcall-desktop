"""Qonto tables belong exclusively to the immutable UID's profile database."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from zylch.storage.database import Base


class QontoConnection(Base):
    __tablename__ = "qonto_connections"

    uid = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="disconnected")
    generation = Column(Integer, nullable=False, default=0)
    host_id = Column(String, nullable=True)
    company_scope = Column(String, nullable=True)
    organization_id = Column(String, nullable=True)
    dataset_id = Column(String, nullable=True)
    selected_account_ids = Column(JSON, nullable=False, default=list)
    encrypted_credentials = Column(Text, nullable=True)
    consent_version = Column(Integer, nullable=True)
    consent_at = Column(Float, nullable=True)
    changed_at = Column(Float, nullable=False)
    last_error = Column(String, nullable=True)
    sync_token = Column(String, nullable=True)
    sync_expires_at = Column(Float, nullable=True)
    last_sync_at = Column(Float, nullable=True)
    provider_retry_at = Column(Float, nullable=True)


class QontoAccount(Base):
    __tablename__ = "qonto_accounts"

    dataset_id = Column(String, primary_key=True)
    account_id = Column(String, primary_key=True)
    uid = Column(String, nullable=False, index=True)
    organization_id = Column(String, nullable=False)
    host_id = Column(String, nullable=False)
    company_scope = Column(String, nullable=False)
    name = Column(Text, nullable=False)
    currency = Column(String, nullable=False)
    selected = Column(Boolean, nullable=False, default=False)
    balance_minor = Column(BigInteger, nullable=True)
    balance_scale = Column(Integer, nullable=True)
    balance_decimal = Column(String, nullable=True)
    balance_retrieved_at = Column(Float, nullable=True)
    balance_provider_at = Column(String, nullable=True)
    authorized_balance_minor = Column(BigInteger, nullable=True)
    authorized_balance_scale = Column(Integer, nullable=True)
    authorized_balance_decimal = Column(String, nullable=True)
    initial_from = Column(String, nullable=True)
    initial_to = Column(String, nullable=True)
    emitted_watermark = Column(String, nullable=True)
    updated_watermark = Column(String, nullable=True)
    pending_repair_cursor = Column(String, nullable=True)


class QontoTransaction(Base):
    __tablename__ = "qonto_transactions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "uid", "organization_id", "account_id", "transaction_id"),
    )

    source_id = Column(String, primary_key=True)
    dataset_id = Column(String, nullable=False, index=True)
    uid = Column(String, nullable=False, index=True)
    organization_id = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    transaction_id = Column(String, nullable=False)
    provider_id = Column(String, nullable=True)
    host_id = Column(String, nullable=False)
    company_scope = Column(String, nullable=False)
    source_revision = Column(String, nullable=False)
    retrieved_at = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    side = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    amount_minor = Column(BigInteger, nullable=False)
    amount_scale = Column(Integer, nullable=False)
    amount_decimal = Column(String, nullable=False)
    original_currency = Column(String, nullable=True)
    original_amount_minor = Column(BigInteger, nullable=True)
    original_amount_scale = Column(Integer, nullable=True)
    original_amount_decimal = Column(String, nullable=True)
    emitted_at = Column(String, nullable=True)
    settled_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
    label = Column(Text, nullable=True)
    reference = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    counterparty_name = Column(Text, nullable=True)


class QontoSyncWindow(Base):
    __tablename__ = "qonto_sync_windows"

    id = Column(String, primary_key=True)
    dataset_id = Column(String, nullable=False, index=True)
    uid = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    generation = Column(Integer, nullable=False)
    date_basis = Column(String, nullable=False)
    window_from = Column(String, nullable=False)
    window_to = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    next_page = Column(Integer, nullable=False, default=1)
    retrieved_at = Column(Float, nullable=True)
    completed_at = Column(Float, nullable=True)
    last_error = Column(String, nullable=True)
    observed_count = Column(Integer, nullable=False, default=0)
    total_count = Column(Integer, nullable=True)
    total_pages = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    retry_at = Column(Float, nullable=True)
    purpose = Column(String, nullable=False, default="initial")


class QontoCheckpoint(Base):
    __tablename__ = "qonto_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "uid", "dataset_id", "source_id", "source_revision", "rule_version", "stage"
        ),
    )

    id = Column(String, primary_key=True)
    uid = Column(String, nullable=False, index=True)
    dataset_id = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    source_revision = Column(String, nullable=False)
    rule_version = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    generation = Column(Integer, nullable=False)
    state = Column(String, nullable=False)
    attempted_at = Column(Float, nullable=True)
    processed_at = Column(Float, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String, nullable=True)


class QontoPublicationIntent(Base):
    __tablename__ = "qonto_publication_intents"

    id = Column(String, primary_key=True)
    uid = Column(String, nullable=False, index=True)
    dataset_id = Column(String, nullable=False)
    company_scope = Column(String, nullable=False)
    generation = Column(Integer, nullable=False)
    source_revision = Column(String, nullable=False)
    state = Column(String, nullable=False)
    created_at = Column(Float, nullable=False)
    consent_at = Column(Float, nullable=True)
    preview = Column(JSON, nullable=False)
    event_id = Column(String, nullable=True)
    committed_ids = Column(JSON, nullable=True)


class QontoConversation(Base):
    __tablename__ = "qonto_conversations"
    __table_args__ = (UniqueConstraint("uid", "conversation_id"),)

    handle = Column(String, primary_key=True)
    uid = Column(String, nullable=False)
    conversation_id = Column(String, nullable=False)
    host_id = Column(String, nullable=False)
    company_scope = Column(String, nullable=False)
    generation = Column(Integer, nullable=False)
    dataset_id = Column(String, nullable=False)
    revision = Column(Integer, nullable=False, default=0)
    canonical_history = Column(JSON, nullable=False, default=list)
    finance_marked = Column(Boolean, nullable=False, default=False)
    source_references = Column(JSON, nullable=False, default=list)
    tombstoned = Column(Boolean, nullable=False, default=False)
    turn_token = Column(String, nullable=True)
    turn_expires_at = Column(Float, nullable=True)
    changed_at = Column(Float, nullable=False)


class QontoEvidenceReceipt(Base):
    __tablename__ = "qonto_evidence_receipts"

    uid = Column(String, primary_key=True)
    digest = Column(String, primary_key=True)
    host_id = Column(String, nullable=False)
    company_scope = Column(String, nullable=False)
    generation = Column(Integer, nullable=False)
    text_length = Column(Integer, nullable=True)
    created_at = Column(Float, nullable=False)


TABLE_NAMES = frozenset(
    {
        model.__tablename__
        for model in (
            QontoConnection,
            QontoAccount,
            QontoTransaction,
            QontoSyncWindow,
            QontoCheckpoint,
            QontoPublicationIntent,
            QontoConversation,
            QontoEvidenceReceipt,
        )
    }
)
