"""Company task assignments, immutable audit and operation acknowledgements."""

from sqlalchemy import JSON, Column, Integer, String, UniqueConstraint

from .database import Base


class AssignedTask(Base):
    __tablename__ = "assigned_tasks"

    id = Column(String(36), primary_key=True)
    space_id = Column(String(36), nullable=False)
    thread_key = Column(String(998), nullable=False)
    revision = Column(Integer, nullable=False)
    state = Column(String(16), nullable=False)
    assignee_uid = Column(String(128), nullable=False)
    creator_uid = Column(String(128), nullable=False)
    covered_inbound = Column(JSON, nullable=False, default=list)
    source_confirmation = Column(JSON, nullable=True)
    closed_at = Column(Integer, nullable=True)
    close_reason = Column(String(1000), nullable=True)
    handled_ref = Column(String(256), nullable=True)
    updated_at = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("space_id", "thread_key"),)


class AssignedTaskEvent(Base):
    __tablename__ = "assigned_task_events"

    operation_id = Column(String(36), primary_key=True)
    task_id = Column(String(36), nullable=False, index=True)
    space_id = Column(String(36), nullable=False)
    revision = Column(Integer, nullable=False)
    actor_uid = Column(String(128), nullable=False)
    approval_issuer = Column(String(64), nullable=False)
    approver_os_uid = Column(Integer, nullable=False)
    operation = Column(String(16), nullable=False)
    intent = Column(JSON, nullable=False)
    created_at = Column(Integer, nullable=False)


class AssignedTaskReceipt(Base):
    __tablename__ = "assigned_task_receipts"

    operation_id = Column(String(36), primary_key=True)
    nonce = Column(String(64), nullable=False, unique=True)
    payload_digest = Column(String(64), nullable=False)
    receipt = Column(JSON, nullable=False)
