"""The ingestion test bench: a real worker on real split databases.

Shared by the replay suite and every worker suite it re-points: the worker is
the real ``MemoryWorker``, both of its clients are the real ``LLMClient`` with
only the transport scripted (extraction answers with entity blocks, the
mnemonic role with decisions), the reservation ledger is real, and a source
runs the way the pipeline runs it — inside an admitted preparation run. A
resume is a real restart on the same files after the backoff.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch


from zylch.services import preparation
from zylch.services.preparation import preparation_run
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import (
    Blob,
    CalendarEvent,
    Email,
    MemoryOperation,
    MrcallConversation,
    PersonIdentifier,
    WhatsAppMessage,
)
from zylch.storage.storage import Storage
from zylch.workers import memory as mem_mod

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    boot,
    clear_process_state,
    client,
    reboot,
    stub_embedder,
    text_response,
)

LUCA = (
    "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n"
    "Email: luca@alpha.example\n#ABOUT\nPurchasing at Alpha.\n#HISTORY\n- wrote about the order"
)
ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\n#ABOUT\nIndustrial supplier.\n#HISTORY\n- confirmed the order"
)
FACT_ENTITY = (
    "#IDENTIFIERS\nEntity type: FACT\nCategory: pricing\nKey: list\n"
    "#ABOUT\nValue: EUR 120 per unit\n#HISTORY\n- from the mail"
)
NAME_ONLY = "#IDENTIFIERS\nEntity type: COMPANY\nName: Example Ltd\n#ABOUT\nMentioned in passing."


class Crash(BaseException):
    """The process going away mid-source: not an Exception, so nothing catches it."""


def booted(tmp_path, monkeypatch, embedder):
    """One profile on real files, with a clock the backoff can be advanced on.

    Used by each suite's ``profile`` fixture: fixtures are discovered per
    module, so the generator lives here and the fixture line lives there.
    """
    stub_embedder(monkeypatch, embedder)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    clock = [1_800_000_000.0]
    monkeypatch.setattr(preparation.time, "time", lambda: clock[0])
    yield SimpleNamespace(owner=owner, clock=clock, embedder=embedder)
    dbm.dispose_engine()
    clear_process_state()


# ─── Sources, workers, runs ───────────────────────────────────────────


def seed_email(email_id="mail-1", body="Luca Bianchi will call; Acme confirms.", sender="mario@acme.test"):
    with get_session() as session:
        session.add(
            Email(
                id=email_id,
                owner_id=OWNER_A,
                gmail_id=email_id,
                thread_id=f"t-{email_id}",
                from_email=sender,
                subject="order",
                date=datetime.now(timezone.utc),
                body_plain=body,
            )
        )
    # The dict the storage hands the worker and the job alike, so a source
    # renders to one revision whichever entry takes it.
    return next(row for row in Storage().get_unprocessed_emails(OWNER_A) if row["id"] == email_id)


def extraction(*entities: str) -> str:
    return "\n---ENTITY---\n".join(entities)


def create_decision(content: str, entity_type: str) -> str:
    return json.dumps(
        {
            "action": "CREATE",
            "entity_type": entity_type,
            "scope": "entity" if entity_type in ("PERSON", "COMPANY") else "company",
            "content": content,
            "reason": "no visible candidate describes this subject",
        }
    )


def update_decision(blob_id: str, version: str, content: str, entity_type: str) -> str:
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": entity_type,
            "scope": "entity" if entity_type in ("PERSON", "COMPANY") else "company",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the same subject, updated",
        }
    )


def make_worker(extractions, decisions):
    """The real worker with both of its clients scripted at the transport."""
    with patch.object(mem_mod, "make_llm_client", return_value=MagicMock()):
        worker = mem_mod.MemoryWorker(storage=Storage(), owner_id=OWNER_A)
    worker._custom_prompt = "Extract entities with #IDENTIFIERS, #ABOUT, #HISTORY. SKIP if none."
    worker._custom_prompt_loaded = True
    worker.client = client(*extractions) if all(isinstance(e, str) for e in extractions) else scripted(extractions)
    worker.decision_client = client(*decisions) if all(isinstance(d, str) for d in decisions) else scripted(decisions)
    return worker


def scripted(items):
    """A real client whose transport answers with text, or raises the given exception."""
    from zylch.llm.client import LLMClient

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(
        side_effect=[text_response(i) if isinstance(i, str) else i for i in items]
    )
    return llm


def run(worker, method, item):
    """One source as the pipeline runs it: inside an admitted preparation run."""
    with preparation_run(OWNER_A):
        return asyncio.run(getattr(worker, method)(item))


def resume(profile):
    """A restart: engines disposed and reopened, the backoff elapsed."""
    reboot()
    profile.clock[0] += 1000


# ─── Reads ────────────────────────────────────────────────────────────


def blobs():
    with get_session() as session:
        return {str(b.id): b.content for b in session.query(Blob).all()}


def operations():
    with get_session() as session:
        return {r.event_id: r.to_dict() for r in session.query(MemoryOperation).all()}


def parent_of(source_id: str):
    """The parent operation of one source, whatever its channel."""
    return next(
        r
        for r in operations().values()
        if r["parent_event_id"] is None and f":{source_id}@" in r["source_ref"]
    )


def children_of(parent_id: str):
    return {k: v for k, v in operations().items() if v["parent_event_id"] == parent_id}


def email_processed(email_id: str) -> bool:
    with get_session() as session:
        return session.get(Email, email_id).memory_processed_at is not None


def links(model, column, source_id):
    with get_session() as session:
        return {r.blob_id for r in session.query(model).filter(getattr(model, column) == source_id).all()}


def identifiers():
    with get_session() as session:
        return {(r.blob_id, r.kind, r.value) for r in session.query(PersonIdentifier).all()}


def role_messages(worker):
    """What the role was shown, per decision call, as the JSON the prompt carries."""
    calls = worker.decision_client._client.messages.create.call_args_list
    return [json.loads(c.kwargs["messages"][0]["content"]) for c in calls]


def attempt_rows():
    with preparation._db() as conn:
        return [
            dict(r)
            for r in conn.exec_driver_sql(
                "SELECT stage, source, inflight, dispatched, failures FROM preparation_attempts"
            ).mappings()
        ]



# ─── Every channel, the same path ─────────────────────────────────────


def seed_whatsapp(text="Ciao, sono Luca di Alpha, ti scrivo per l'ordine."):
    with get_session() as session:
        session.add(
            WhatsAppMessage(
                id="wa-1",
                owner_id=OWNER_A,
                message_id="wa-1",
                chat_jid="393331200000@s.whatsapp.net",
                sender_jid="393331200000@s.whatsapp.net",
                sender_name="Luca",
                text=text,
                timestamp=datetime.now(timezone.utc),
                is_from_me=False,
                is_group=False,
            )
        )
    return {
        "id": "wa-1",
        "text": text,
        "sender_jid": "393331200000@s.whatsapp.net",
        "sender_name": "Luca",
        "timestamp": "2026-09-24T10:00:00+00:00",
        "is_from_me": False,
        "is_group": False,
    }


def seed_calendar():
    with get_session() as session:
        session.add(
            CalendarEvent(
                id="cal-1",
                owner_id=OWNER_A,
                google_event_id="g-1",
                summary="Sync with Acme",
                description="Marta Riva joins as finance lead",
                start_time=datetime.now(timezone.utc),
            )
        )
    return {"id": "cal-1", "summary": "Sync with Acme", "description": "Marta Riva joins as finance lead", "start_time": "2026-09-24T10:00", "attendees": ["marta@acme.test"]}


def seed_mrcall():
    Storage().store_agent_prompt(OWNER_A, "memory_mrcall", "Extract entities from {conversation}", {})
    with get_session() as session:
        session.add(
            MrcallConversation(
                id="call-1",
                owner_id=OWNER_A,
                business_id="biz",
                contact_phone="+393331200000",
                contact_name="Luca",
                body={"transcript": "Luca asks about the order."},
            )
        )
    return {"id": "call-1", "contact_phone": "+393331200000", "contact_name": "Luca", "body": {"transcript": "Luca asks about the order."}}


