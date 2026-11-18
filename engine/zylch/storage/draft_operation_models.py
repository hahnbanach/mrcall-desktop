"""Private provider-operation journal; unrelated to delivery or assignment truth."""

from sqlalchemy import Boolean, CheckConstraint, Column, Index, Integer, JSON, String, text

from zylch.storage.database import Base
from zylch.storage.migrations import MigrationStep


class DraftOperation(Base):
    __tablename__ = "draft_provider_operations"
    __table_args__ = (
        Index(
            "uq_draft_operation_active_root",
            "owner_uid",
            "canonical_root",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
        CheckConstraint("operation_type IN ('publish', 'retire_sent_mirror', 'send')"),
        CheckConstraint(
            "stage IN ('reserved', 'inventoried', 'dispatch_possible', "
            "'acknowledged', 'completed', 'not_dispatched')"
        ),
        CheckConstraint(
            "(active = 0 AND stage IN ('completed', 'not_dispatched')) OR "
            "(active = 1 AND stage NOT IN ('completed', 'not_dispatched'))"
        ),
    )

    owner_uid = Column(String, primary_key=True)
    operation_id = Column(String, primary_key=True)
    canonical_root = Column(String, nullable=False)
    operation_type = Column(String, nullable=False)
    draft_id = Column(String, nullable=False)
    expected_snapshot = Column(String, nullable=False)
    binding = Column(JSON, nullable=False)
    output_mime_digest = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False)
    executor_token = Column(String, nullable=False)
    inventory = Column(JSON, nullable=True)
    acknowledgment = Column(JSON, nullable=True)
    verification = Column(JSON, nullable=True)


def apply(conn) -> None:
    DraftOperation.__table__.create(conn, checkfirst=True)


STEP = MigrationStep(
    id="0007_draft_provider_operations",
    apply=apply,
    description="private durable exact-draft provider operation reservations",
)
