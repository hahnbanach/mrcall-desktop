"""Profile-owned M2 settings and immutable snapshots; no provider activation."""

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import insert, select, update

from zylch.memory.company_key import current_company_key
from zylch.memory.scope import blob_visible, sentences_in_scope
from zylch.storage import database
from zylch.storage.models import Blob, BlobSentence, ProjectSpace, VoiceAgentConfig

logger = logging.getLogger(__name__)
T = VoiceAgentConfig.__table__
Identifier = Annotated[str, Field(strict=True, min_length=1, max_length=100)]


class VoiceError(Exception):
    """Only fixed, non-sensitive messages cross the RPC boundary."""

    def __init__(self, code: int, message: str):
        self.code = code
        super().__init__(message)


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CustomerFacts(FrozenModel):
    blob_id: Identifier
    sentence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=32)


class Limits(FrozenModel):
    duration_seconds: int = Field(default=120, strict=True, ge=1, le=180)
    max_calls: int = Field(default=2, strict=True, ge=1, le=6)
    budget_microusd: int = Field(default=2_000_000, strict=True, ge=1, le=5_000_000)


class AgentConfig(FrozenModel):
    enabled: bool = Field(default=False, strict=True)
    called_number: str = Field(default="", strict=True, pattern=r"^(?:\+[1-9][0-9]{7,14})?$")
    instructions: str = Field(default="", strict=True, max_length=8000)
    caller_context_policy: Literal["selected_facts_only"] = "selected_facts_only"
    tools: tuple[Literal["caller_memory"], ...] = Field(default=(), max_length=1)
    limits: Limits = Limits()
    customers: tuple[CustomerFacts, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def valid_selection(self):
        if self.enabled and (not self.called_number or not self.instructions.strip()):
            raise ValueError("Enabled agents require a number and instructions")
        blobs = [c.blob_id for c in self.customers]
        sentences = [s for c in self.customers for s in c.sentence_ids]
        if len(set(blobs)) != len(blobs) or len(set(sentences)) != len(sentences):
            raise ValueError("Duplicate selection")
        return self


def parse_config(value: dict) -> AgentConfig:
    try:
        return AgentConfig.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise VoiceError(-32602, "Invalid voice configuration") from None


@dataclass(frozen=True)
class Binding:
    owner_uid: str
    space_id: str
    company_key: str = field(repr=False)


@dataclass(frozen=True)
class Snapshot:
    binding: Binding
    revision: int
    config: AgentConfig
    # (blob, sentence, fingerprint); never sentence text or memory capability.
    pins: tuple[tuple[str, str, str], ...] = ()


def binding() -> Binding:
    owner = os.environ.get("OWNER_ID", "")
    key = current_company_key()
    engine = database.current_memory_engine()
    if not owner or not key or engine is None:
        raise VoiceError(-32063, "Voice requires a bound profile and company memory")
    with engine.connect() as conn:
        space = conn.execute(select(ProjectSpace.space_id)).scalar_one()
    return Binding(owner, space, key)


def require_binding(expected: Binding) -> None:
    if binding() != expected:
        raise VoiceError(-32061, "Voice company or profile binding changed")


def selected_rows(session, bound: Binding, customer: CustomerFacts):
    """Select approved sentence columns only; never materialize a complete blob."""
    return session.execute(
        select(BlobSentence.id, BlobSentence.sentence_text, BlobSentence.created_at)
        .join(Blob, Blob.id == BlobSentence.blob_id)
        .where(
            blob_visible(bound.owner_uid, bound.company_key),
            Blob.namespace == f"user:{bound.company_key}",
            Blob.id == customer.blob_id,
            sentences_in_scope(bound.company_key),
            BlobSentence.id.in_(customer.sentence_ids),
        )
    ).all()


def fingerprint(row) -> str:
    # Detect replacement even when a fixture writer reuses a sentence ID.
    return hashlib.sha256(f"{row.created_at}\0{row.sentence_text}".encode()).hexdigest()


def _read(conn, bound: Binding) -> tuple[Snapshot, bool]:
    row = conn.execute(select(T).where(T.c.id == 1)).mappings().one_or_none()
    if row is None:
        return Snapshot(bound, 0, AgentConfig()), True
    valid = row["owner_uid"] == bound.owner_uid and row["space_id"] == bound.space_id
    if not valid:
        return Snapshot(bound, row["revision"], AgentConfig()), False
    return (
        Snapshot(
            bound,
            row["revision"],
            parse_config(row["config"]),
            tuple(tuple(p) for p in row["sentence_pins"]),
        ),
        True,
    )


def public(snapshot: Snapshot, binding_valid: bool = True) -> dict:
    return {
        "owner_uid": snapshot.binding.owner_uid,
        "space_id": snapshot.binding.space_id,
        "revision": snapshot.revision,
        "binding_valid": binding_valid,
        "config": snapshot.config.model_dump(mode="json"),
    }


def get_config() -> dict:
    bound = binding()
    with database.get_engine().connect() as conn:
        snap, valid = _read(conn, bound)
    require_binding(bound)
    logger.debug("[voice] config.get revision=%s binding_valid=%s", snap.revision, valid)
    return public(snap, valid)


def update_config(owner_uid: str, space_id: str, expected_revision: int, config: dict) -> dict:
    bound = binding()
    if (owner_uid, space_id) != (bound.owner_uid, bound.space_id):
        raise VoiceError(-32061, "Voice company or profile binding changed")
    if type(expected_revision) is not int or expected_revision < 0:
        raise VoiceError(-32602, "Invalid voice revision")
    parsed = parse_config(config)
    pins = []
    with database.get_session() as session:
        for customer in parsed.customers:
            rows = selected_rows(session, bound, customer)
            if len(rows) != len(customer.sentence_ids):
                raise VoiceError(-32602, "Selected facts are missing or outside the customer")
            pins.extend((customer.blob_id, r.id, fingerprint(r)) for r in rows)
    with database.get_engine().begin() as conn:
        # Take the writer lock before reading, including the first-ever update.
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        previous, _ = _read(conn, bound)
        if previous.revision != expected_revision:
            raise VoiceError(-32060, "Voice configuration changed; read it again")
        require_binding(bound)
        values = dict(
            owner_uid=bound.owner_uid,
            space_id=bound.space_id,
            revision=expected_revision + 1,
            config=parsed.model_dump(mode="json"),
            sentence_pins=pins,
        )
        if previous.revision:
            conn.execute(update(T).where(T.c.id == 1).values(**values))
        else:
            conn.execute(insert(T).values(id=1, **values))
    snap = Snapshot(bound, expected_revision + 1, parsed, tuple(pins))
    logger.debug("[voice] config.update revision=%s", snap.revision)
    return public(snap)


def snapshot_for_call(called_number: str) -> Snapshot:
    """M3 seam: load once per call; updates apply to subsequent snapshots."""
    bound = binding()
    with database.get_engine().connect() as conn:
        snap, valid = _read(conn, bound)
    require_binding(bound)
    if not valid or not snap.config.enabled or snap.config.called_number != called_number:
        raise VoiceError(-32062, "Voice is disabled or the called number is not bound")
    return snap
