"""Mailbox preparation evidence through dispatch against an isolated SQLite DB."""

from contextlib import contextmanager
from datetime import datetime
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from zylch.rpc.dispatch import dispatch_raw
from zylch.rpc import setup
from zylch.storage import database
from zylch.storage.models import Email, WhatsAppMessage
from zylch.storage.storage import Storage


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'setup.db'}")
    Email.__table__.create(engine)
    WhatsAppMessage.__table__.create(engine)
    sessions = sessionmaker(bind=engine)

    @contextmanager
    def session_scope():
        with sessions() as session:
            yield session
            session.commit()

    monkeypatch.setattr(database, "get_session", session_scope)
    monkeypatch.setattr(setup, "_owner_id", lambda: "setup-owner")

    def stats(owner):
        with session_scope() as session:
            return {"total_emails": session.query(Email).filter(Email.owner_id == owner).count()}

    store = SimpleNamespace(get_email_stats=stats, get_agent_prompt=lambda *_: None)
    monkeypatch.setattr(Storage, "get_instance", lambda: store)
    try:
        yield session_scope
    finally:
        engine.dispose()


async def snapshot():
    response = await dispatch_raw(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "setup.state", "params": {}}),
        lambda *_: None,
    )
    assert "error" not in response
    return response["result"]


@pytest.mark.asyncio
async def test_counts_only_own_processed_mail_and_reports_pending(mailbox):
    stamp = datetime(2026, 9, 10, 8, 0, 0)
    with mailbox() as session:
        for number, owner, processed in [
            (1, "setup-owner", stamp),
            (2, "setup-owner", None),
            (3, "colleague", datetime(2026, 9, 10, 9, 0, 0)),
        ]:
            session.add(
                Email(
                    owner_id=owner,
                    gmail_id=str(number),
                    thread_id=str(number),
                    date=stamp,
                    memory_processed_at=processed,
                )
            )
    result = await snapshot()
    assert result["emails_count"] == 2
    assert result["emails_analyzed_count"] == 1
    assert result["emails_pending_analysis"] == 1
    assert result["last_email_analyzed_at"] == stamp.isoformat()
    assert result["has_synced"] is True
    assert result["has_trained"] is False


@pytest.mark.asyncio
async def test_empty_mailbox_is_zero_evidence_not_successful_analysis(mailbox):
    result = await snapshot()
    assert result["emails_analyzed_count"] == 0
    assert result["emails_pending_analysis"] == 0
    assert result["last_email_analyzed_at"] is None
    assert result["has_synced"] is False


@pytest.mark.asyncio
async def test_unreadable_evidence_is_unknown_not_ready(mailbox):
    with mailbox() as session:
        session.connection().exec_driver_sql("DROP TABLE emails")
    result = await snapshot()
    assert result["emails_analyzed_count"] is None
    assert result["emails_pending_analysis"] is None
    assert result["last_email_analyzed_at"] is None
