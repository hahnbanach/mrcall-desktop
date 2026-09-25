"""The join fence: one row per attempt to move a profile into another company memory.

It lives in the source company's store, beside the journal it fences. ``id``
is a fresh unguessable token per join attempt. ``owner_ids`` are both
identities of the joining profile. ``destination_digest`` is the sha256 of the
destination key: the key itself is never written into a store that other key
holders can open. ``phase`` moves ``fenced`` → ``accepted`` → ``completed``, or
``fenced`` → ``released``; only ``fenced`` and ``accepted`` are active, and the
partial unique index admits at most one active fence per company.
``snapshot_digest`` is the digest of what the import copied, and ``detail``
records what blocked a join or what its import counted.

A table of its own rather than a row of ``memory_operations``: an operation row
is an event, with an input digest, a caller class, a visibility and a place in
every journal scan, and a fence is none of those.
"""

from sqlalchemy import JSON, Column, DateTime, Index, String, Text, text

from .database import Base
from .models import DictMixin, _utcnow


class MemoryJoinFence(DictMixin, Base):
    __tablename__ = "memory_join_fences"

    id = Column(String(64), primary_key=True)
    company_key = Column(Text, nullable=False)
    owner_ids = Column(JSON, nullable=False, default=list)
    destination_digest = Column(Text, nullable=False)
    phase = Column(Text, nullable=False, default="fenced")
    snapshot_digest = Column(Text, nullable=True)
    detail = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index(
            "ux_memory_join_fences_active_company",
            "company_key",
            unique=True,
            sqlite_where=text("phase IN ('fenced', 'accepted')"),
        ),
    )
