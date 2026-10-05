"""Profile-only persistence with immutable connection snapshots."""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from zylch.qonto.identity import Authority
from zylch.qonto.models import QontoConnection
from zylch.storage.database import get_engine


@contextmanager
def profile_transaction():
    with Session(get_engine(), expire_on_commit=False) as session:
        with session.begin():
            yield session


@dataclass(frozen=True)
class Binding:
    uid: str
    generation: int
    host_id: str | None
    company_scope: str | None = field(repr=False)
    organization_id: str | None
    dataset_id: str | None
    account_ids: tuple[str, ...]
    status: str
    encrypted_credentials: str | None = field(repr=False)

    def matches(self, authority: Authority) -> bool:
        return (
            self.uid == authority.uid
            and self.host_id == authority.host_id
            and self.company_scope == authority.company_scope
        )


def snapshot(row: QontoConnection) -> Binding:
    return Binding(
        row.uid,
        row.generation,
        row.host_id,
        row.company_scope,
        row.organization_id,
        row.dataset_id,
        tuple(row.selected_account_ids or []),
        row.status,
        row.encrypted_credentials,
    )


def connection(session: Session, uid: str, *, create: bool = False) -> QontoConnection | None:
    row = session.get(QontoConnection, uid)
    if row is None and create:
        row = QontoConnection(uid=uid, status="disconnected", generation=0, changed_at=time.time())
        session.add(row)
        session.flush()
    return row


def read_binding(uid: str) -> Binding | None:
    with profile_transaction() as session:
        row = connection(session, uid)
        return snapshot(row) if row is not None else None


def dataset_id(authority: Authority, organization_id: str) -> str:
    data = [authority.uid, authority.host_id, authority.company_scope, organization_id]
    return hashlib.sha256(b"mrcall:qonto:dataset:v1\0" + json.dumps(data).encode()).hexdigest()


def source_id(dataset: str, organization_id: str, account_id: str, transaction_id: str) -> str:
    ids = json.dumps([dataset, organization_id, account_id, transaction_id]).encode()
    return "qonto:" + hashlib.sha256(b"mrcall:qonto:source:v1\0" + ids).hexdigest()
