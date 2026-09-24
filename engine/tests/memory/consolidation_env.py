"""What the consolidation suites share: a profile, seeded memories, a scripted role.

Everything is real except the provider transport: the split stores, the
preparation run every trigger opens, the harness, the validator and the commit.
The role's answers are scripted in call order. An answer may be a callable,
evaluated when the call is made, because a pair that follows a merge is formed
at a version no test can know in advance; an exception is raised as the
provider's own failure.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from sqlalchemy import text

from zylch.memory.blob_storage import BlobStorage
from zylch.storage import database as dbm
from zylch.storage.database import get_engine, get_session
from zylch.storage.models import BlobVersion, PersonIdentifier
from zylch.storage.storage import Storage

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    boot,
    clear_process_state,
    stub_embedder,
    text_response,
)

LUCA = "Luca Bianchi"
LUCA_EMAIL = "luca@alpha.example"


def person(
    name=LUCA,
    ids=f"Email: {LUCA_EMAIL}\n",
    about="Purchasing at Alpha.",
    *,
    entity_type="PERSON",
    history="ordered 40 units",
):
    """A memory in the shape the role writes: header, about, history."""
    return (
        f"#IDENTIFIERS\nEntity type: {entity_type}\nScope: entity\nName: {name}\n{ids}"
        f"#ABOUT\n{about}\n#HISTORY\n- {history}"
    )


def profile(tmp_path, monkeypatch, embedder):
    """The ``store`` fixture's body: one booted profile and its memory storage."""
    from zylch.workers import merge_canary_gate

    stub_embedder(monkeypatch, embedder)
    # The canary's "verified since start" flag is process state the policy
    # reads; a test that stores a verdict must not leak it to the next one.
    monkeypatch.setattr(merge_canary_gate, "_canary_verified_since_start", False)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    yield BlobStorage(get_session, embedder)
    dbm.dispose_engine()
    clear_process_state()


def seed(store, content, *identifiers, owner=OWNER_A):
    """A memory in the entity family, with identity-index rows when given."""
    blob_id = store.store_blob(owner, f"user:{COMPANY_A}", content, "seed")["id"]
    if identifiers:
        Storage().add_person_identifiers(owner, blob_id, list(identifiers))
    return blob_id


def scripted(monkeypatch, *answers):
    """Consolidation's merge-routed client, real except its transport, answering in order."""
    from zylch.llm.client import LLMClient
    from zylch.memory import llm_merge

    queue = list(answers)

    def respond(**_request):
        if not queue:
            raise AssertionError("a paid call nobody scripted")
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return text_response(answer() if callable(answer) else answer)

    transport = Mock(side_effect=respond)

    def factory(model=None):
        llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
        llm._client.messages.create = transport
        return llm

    monkeypatch.setattr(llm_merge, "make_llm_client", factory)
    return transport


def merge_answer(store, keeper_id, donor_id, *, entity_type="PERSON", owner=OWNER_A):
    """The role folding ``donor_id`` into ``keeper_id``, at their versions when it answers."""

    def answer():
        keeper, donor = store.get_blob(keeper_id, owner), store.get_blob(donor_id, owner)
        return json.dumps(
            {
                "action": "MERGE",
                "entity_type": entity_type,
                "scope": "entity",
                "content": keeper["content"] + f"\n- folded in {donor_id[:8]}",
                "write_set": [
                    {
                        "blob_id": keeper_id,
                        "expected_version": keeper["updated_at"],
                        "role": "keeper",
                    },
                    {
                        "blob_id": donor_id,
                        "expected_version": donor["updated_at"],
                        "role": "donor",
                    },
                ],
                "declared_effects": [f"alias:{donor_id}->{keeper_id}", f"delete:{donor_id}"],
                "reason": "both headers state the same identity",
            }
        )

    return answer


def skip_answer(reason="two different people who share a name"):
    return json.dumps({"action": "SKIP", "reason": reason})


def healthy(monkeypatch, owner=OWNER_A):
    """A stored healthy verdict: the canary reaches the transport only in its own cases.

    Storing one also sets the process flag the policy reads; registering it
    with ``monkeypatch`` first puts it back when the test ends.
    """
    from zylch.workers import merge_canary_gate

    monkeypatch.setattr(merge_canary_gate, "_canary_verified_since_start", False)
    merge_canary_gate.record_merge_canary(owner, True)


def sweep(owner=OWNER_A, **kwargs):
    """One run as the button and the CLI start it: forced, inside a preparation run."""
    from zylch.memory.consolidation import consolidate
    from zylch.services.preparation import preparation_run

    with preparation_run(owner):
        return asyncio.run(consolidate(owner, **{"force": True, **kwargs}))


def live(store, *blob_ids, owner=OWNER_A):
    """The ids among ``blob_ids`` whose memory still exists."""
    return {b for b in blob_ids if store.get_blob(b, owner) is not None}


def identifiers_of(blob_id):
    with get_session() as session:
        rows = session.query(PersonIdentifier).filter(PersonIdentifier.blob_id == blob_id).all()
        return {(r.kind, r.value) for r in rows}


def attempts():
    """What preparation recorded for this account's items: (stage, source, failures, inflight)."""
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT stage, source, failures, inflight FROM preparation_attempts "
                "WHERE owner = :owner ORDER BY source"
            ),
            {"owner": OWNER_A},
        ).all()
    return [tuple(r) for r in rows]


def seed_versions(blob_id, n, *, days_old=200):
    """``n`` old ``append`` versions of one blob: a count over the default threshold."""
    newest = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_old)
    with get_session() as session:
        for i in range(n):
            session.add(
                BlobVersion(
                    blob_id=blob_id,
                    company_key=COMPANY_A,
                    owner_id=OWNER_A,
                    namespace=f"user:{COMPANY_A}",
                    content=f"text {i}",
                    reason="append",
                    superseded_at=newest - timedelta(hours=i),
                )
            )


def version_count(blob_id):
    with get_session() as session:
        return session.query(BlobVersion).filter(BlobVersion.blob_id == blob_id).count()
