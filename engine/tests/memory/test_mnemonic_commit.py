"""Atomic commit, and the first real path through it.

Everything here runs against real split databases — a profile ``zylch.db`` and
a company store, booted through the real ``init_db`` — because what is being
proven is transactional: either a blob, its sentences, its identifier index,
its source link, the mutation sequence and the operation receipt all landed, or
none of them did. A mocked session cannot fail that assertion.

The vertical slice runs the whole path: the real ``create_memory`` tool, the
real mnemonic role, the real ``LLMClient``, the real durable reservation
ledger, the real commit. Only the provider transport is replaced. Nothing here
supplies a preparation context, stubs ``check_dispatch`` or fakes a
reservation — those are the guards under test, and a test that replaced them
would prove that the test works.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zylch.llm.client import LLMClient
from zylch.memory.blob_storage import BlobStorage
from zylch.memory.commit_permit import PermitError, issue_commit_permit
from zylch.memory.hybrid_search import HybridSearchEngine
from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.commit import CommitContext, submit
from zylch.memory.mnemonic.proposals import MnemonicResult
from zylch.memory.mnemonic.contracts import (
    CREATE,
    EVENT_DISPATCH_ALLOWANCE,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
)
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, BlobSentence, MemoryOperation, PersonIdentifier
from zylch.storage.storage import Storage

from .mnemonic_env import (
    COMPANY_A,
    COMPANY_B,
    OWNER_A,
    OWNER_B,
    boot,
    clear_process_state,
    reboot,
)

ENGINE_ROOT = Path(__file__).resolve().parents[2]

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\nPhone: +390212345678\n"
    "#ABOUT\nIndustrial supplier in Milan.\n#HISTORY\n- pays at 60 days"
)
ACME_CORRECTED = ACME.replace("info@acme.test", "orders@acme.test")


# ─── Wiring ───────────────────────────────────────────────────────────


@pytest.fixture
def profile_a(tmp_path, monkeypatch, embedder):
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)
    yield boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()
    clear_process_state()


@pytest.fixture
def context(embedder):
    return build_context(OWNER_A, embedder)


def build_context(owner: str, embedder) -> CommitContext:
    """The real storage surfaces, over the real split databases."""
    storage = BlobStorage(get_session, embedder)
    search = HybridSearchEngine(get_session, embedder)
    rows = Storage()
    return CommitContext(
        storage=storage,
        get_blob=lambda blob_id: storage.get_blob(blob_id, owner),
        search=lambda query, limit: search.search(owner, query, limit=limit),
        identifier_blob_ids=lambda ids: rows.find_blobs_by_identifiers(owner, list(ids)),
    )


def usage():
    return SimpleNamespace(input_tokens=400, output_tokens=120)


def text_response(body, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=body, refusal=None)],
        model="claude-haiku-4-5",
        stop_reason=stop_reason,
        usage=usage(),
        refusal=None,
    )


def client(*responses):
    """The real LLMClient with only the provider transport replaced."""
    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(side_effect=[text_response(r) for r in responses])
    return llm


def create_decision(content=ACME, entity_type="COMPANY"):
    return json.dumps(
        {
            "action": CREATE,
            "entity_type": entity_type,
            "scope": "entity",
            "content": content,
            "reason": "no visible candidate describes this company",
        }
    )


def update_decision(blob_id, version, content=ACME_CORRECTED):
    return json.dumps(
        {
            "action": UPDATE,
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the ordering address replaces the old one",
        }
    )


def asked_to_update(blob_id):
    """The baseline a caller declares when it asked to change exactly this blob.

    Milestone 4 measures the final proposal against what the calling tool asked
    for, and treats "nothing declared" as "everything changed" — so a direct
    `submit` in a test has to say what it asked for, or the acceptance gate fires
    before the transaction these tests are about. Declaring a faithful baseline
    keeps each test exercising its own subject: the CAS, the allowance, the
    cancellation.
    """
    from zylch.memory.mnemonic.approval import RequestedWrite

    return RequestedWrite(action=UPDATE, blob_id=blob_id, subject_is_authoritative=True)


def event(
    *,
    event_id="evt-1",
    owner=OWNER_A,
    company=COMPANY_A,
    observation="Acme Srl ordina da info@acme.test e paga a 60 giorni.",
    source_kind="chat",
    source_id="turn:abc",
    revision="rev-1",
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=owner,
        company_key=company,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind=source_kind,
        source_id=source_id,
        source_revision=revision,
        observation=observation,
    )


def stored_blobs(owner=OWNER_A):
    with get_session() as session:
        return [b.to_dict() for b in session.query(Blob).all()]


def operation(event_id="evt-1"):
    with get_session() as session:
        row = session.get(MemoryOperation, event_id)
        return None if row is None else row.to_dict()


def mutation_seq():
    """Read the sequence through the ORM: a raw ``text()`` names no table, so
    the per-table binds would send it to the profile file and miss."""
    from zylch.storage.models import MemoryMeta

    with get_session() as session:
        return session.query(MemoryMeta.mutation_seq).filter(MemoryMeta.id == 1).scalar()


# ─── The permit is the only way in ────────────────────────────────────


def test_only_the_commit_module_mints_a_permit():
    """Python privacy is not a sandbox, so this is checked statically.

    A runtime guard stops a caller that forges a permit. It cannot stop one
    that politely asks the factory for a real one, and that is exactly what a
    future adapter would do to "just write this one thing". The engine is
    scanned instead: the minting function may be imported by the commit module
    and by nothing else.
    """
    import ast

    engine = Path(__file__).resolve().parents[2] / "zylch"
    importers = []
    for path in sorted(engine.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            if "issue_commit_permit" in names:
                importers.append(path.relative_to(engine).as_posix())
                break
    assert importers == ["memory/mnemonic/commit.py"]


def test_a_semantic_write_without_a_permit_is_refused(profile_a, context):
    prepared = context.storage.prepare(ACME)
    with pytest.raises(PermitError, match="requires a commit permit"):
        with journal.company_transaction() as session:
            context.storage.semantic_create(
                session,
                None,
                owner_id=OWNER_A,
                namespace=f"user:{COMPANY_A}",
                prepared=prepared,
            )
    assert stored_blobs() == []


def test_a_forged_permit_is_refused_even_when_every_field_matches(profile_a, context):
    """Identity, not equality: a copy is not the permit that was issued."""
    import dataclasses

    real = issue_commit_permit(
        action=CREATE,
        company_key=COMPANY_A,
        owner_id=OWNER_A,
        event_id="evt-1",
        proposal_digest="d",
        content=ACME,
        namespace=f"user:{COMPANY_A}",
    )
    forged = dataclasses.replace(real)
    prepared = context.storage.prepare(ACME)

    with pytest.raises(PermitError, match="never issued"):
        with journal.company_transaction() as session:
            context.storage.semantic_create(
                session,
                forged,
                owner_id=OWNER_A,
                namespace=f"user:{COMPANY_A}",
                prepared=prepared,
            )
    assert stored_blobs() == []


def test_a_permit_cannot_be_spent_twice(profile_a, context):
    permit = issue_commit_permit(
        action=CREATE,
        company_key=COMPANY_A,
        owner_id=OWNER_A,
        event_id="evt-1",
        proposal_digest="d",
        content=ACME,
        namespace=f"user:{COMPANY_A}",
    )
    prepared = context.storage.prepare(ACME)
    with journal.company_transaction() as session:
        context.storage.semantic_create(
            session, permit, owner_id=OWNER_A, namespace=f"user:{COMPANY_A}", prepared=prepared
        )
    with pytest.raises(PermitError, match="already spent"):
        with journal.company_transaction() as session:
            context.storage.semantic_create(
                session,
                permit,
                owner_id=OWNER_A,
                namespace=f"user:{COMPANY_A}",
                prepared=prepared,
            )
    assert len(stored_blobs()) == 1


def test_a_permit_does_not_authorize_different_content_or_another_company(profile_a, context):
    permit = issue_commit_permit(
        action=CREATE,
        company_key=COMPANY_B,
        owner_id=OWNER_A,
        event_id="evt-1",
        proposal_digest="d",
        content=ACME,
        namespace=f"user:{COMPANY_A}",
    )
    prepared = context.storage.prepare(ACME)
    with pytest.raises(PermitError, match="another company"):
        with journal.company_transaction() as session:
            context.storage.semantic_create(
                session,
                permit,
                owner_id=OWNER_A,
                namespace=f"user:{COMPANY_A}",
                prepared=prepared,
            )

    same_company = issue_commit_permit(
        action=CREATE,
        company_key=COMPANY_A,
        owner_id=OWNER_A,
        event_id="evt-1",
        proposal_digest="d",
        content=ACME,
        namespace=f"user:{COMPANY_A}",
    )
    swapped = context.storage.prepare("something else entirely")
    with pytest.raises(PermitError, match="content differs"):
        with journal.company_transaction() as session:
            context.storage.semantic_create(
                session,
                same_company,
                owner_id=OWNER_A,
                namespace=f"user:{COMPANY_A}",
                prepared=swapped,
            )
    assert stored_blobs() == []


# ─── One transaction ──────────────────────────────────────────────────


def test_a_commit_writes_blob_sentences_index_link_sequence_and_receipt(profile_a, context):
    before = mutation_seq()
    result = submit(
        event(source_kind="email", source_id="msg-1"),
        client=client(create_decision()),
        context=context,
    )

    assert result.outcome == "committed"
    blob_id, _version = result.committed_ids[0]

    with get_session() as session:
        assert session.query(Blob).count() == 1
        assert session.query(BlobSentence).filter(BlobSentence.blob_id == blob_id).count() > 0
        kinds = {
            (row.kind, row.value)
            for row in session.query(PersonIdentifier).filter(PersonIdentifier.blob_id == blob_id)
        }
        assert ("email", "info@acme.test") in kinds
        from zylch.storage.models import EmailBlob

        assert session.query(EmailBlob).filter(EmailBlob.email_id == "msg-1").count() == 1
    assert mutation_seq() > before
    assert operation()["state"] == journal.COMMITTED


@pytest.mark.parametrize(
    "module,attr",
    [
        ("zylch.memory.associations", "add_identifiers"),
        ("zylch.memory.associations", "link_source"),
        ("zylch.memory.mnemonic.journal", "receipt"),
    ],
)
def test_a_failure_at_any_step_of_the_transaction_leaves_nothing_behind(
    profile_a, context, monkeypatch, module, attr
):
    """Not "mostly nothing": the receipt and the blob live or die together."""
    import importlib

    target = importlib.import_module(module)
    with monkeypatch.context() as patched:
        patched.setattr(target, attr, Mock(side_effect=RuntimeError(f"{attr} exploded")))
        result = submit(
            event(source_kind="email", source_id="msg-1"),
            client=client(create_decision()),
            context=context,
        )

    assert result.outcome == "retryable_failure"
    assert stored_blobs() == []
    with get_session() as session:
        assert session.query(BlobSentence).count() == 0
        assert session.query(PersonIdentifier).count() == 0
        from zylch.storage.models import EmailBlob

        assert session.query(EmailBlob).count() == 0


def test_a_failed_embedding_refuses_before_any_transaction_opens(profile_a, context):
    """Encoding is slow and can fail, so it happens before the write lock."""
    broken = SimpleNamespace(encode=Mock(side_effect=RuntimeError("model unavailable")))
    broken_context = CommitContext(
        storage=BlobStorage(get_session, broken),
        get_blob=context.get_blob,
        search=context.search,
        identifier_blob_ids=context.identifier_blob_ids,
    )
    result = submit(event(), client=client(create_decision()), context=broken_context)

    assert result.outcome == "retryable_failure"
    assert "model unavailable" in result.reason
    assert stored_blobs() == []
    assert operation()["state"] == journal.FAILED


def test_a_crash_before_the_commit_leaves_the_operation_resumable(profile_a, context, monkeypatch):
    with monkeypatch.context() as patched:
        patched.setattr(
            journal, "receipt", Mock(side_effect=KeyboardInterrupt("killed mid-transaction"))
        )
        with pytest.raises(KeyboardInterrupt):
            submit(event(), client=client(create_decision()), context=context)

    assert stored_blobs() == []
    assert operation()["state"] == journal.PENDING

    reboot()
    result = submit(
        event(),
        client=client(create_decision()),
        context=build_context(OWNER_A, context.storage.embeddings),
    )
    assert result.outcome == "committed"
    assert len(stored_blobs()) == 1


def test_a_crash_after_the_commit_replays_the_receipt_and_writes_nothing_twice(profile_a, context):
    first = submit(event(), client=client(create_decision()), context=context)
    assert first.outcome == "committed"

    reboot()
    again = submit(
        event(),
        client=client(create_decision()),
        context=build_context(OWNER_A, context.storage.embeddings),
    )

    assert again.outcome == "committed"
    assert again.committed_ids == first.committed_ids
    assert len(stored_blobs()) == 1


def test_a_replay_pays_for_no_model_call_at_all(profile_a, context):
    submit(event(), client=client(create_decision()), context=context)
    second = client()  # side_effect exhausted: any call raises StopIteration
    again = submit(event(), client=second, context=context)
    assert again.outcome == "committed"
    assert second._client.messages.create.call_count == 0


def test_an_event_id_reused_with_different_input_is_refused_not_rewritten(profile_a, context):
    submit(event(), client=client(create_decision()), context=context)
    result = submit(
        event(observation="a different sentence altogether"),
        client=client(create_decision()),
        context=context,
    )
    assert result.outcome == "review_needed"
    assert "different input" in result.reason
    assert len(stored_blobs()) == 1


def test_a_journal_that_cannot_answer_is_a_retryable_failure_never_a_write(
    profile_a, context, monkeypatch
):
    """Fails closed, and fails as itself.

    ``submit`` is the whole public surface, so it has to survive a broken
    journal by saying so. Raising out of it would leave a caller with an
    exception where a result belongs, and would say nothing about whether
    memory changed.
    """
    from zylch.memory.mnemonic import session as session_mod

    with monkeypatch.context() as patched:
        # Patched where it is *used*: `company_transaction` calls the name in
        # its own module, so patching an importer would leave it untouched.
        patched.setattr(
            session_mod,
            "session_factory",
            Mock(side_effect=journal.JournalError("company memory is unavailable")),
        )
        result = submit(event(), client=client(create_decision()), context=context)

    assert result.outcome == "retryable_failure"
    assert "unavailable" in result.reason
    assert stored_blobs() == []


def test_a_journal_failure_mid_dispatch_is_a_result_and_not_an_exception(
    profile_a, context, monkeypatch
):
    """``submit`` owes its caller an answer even when the store gives out.

    The durable allowance is spent at the client boundary, so a journal that
    stops answering surfaces from inside ``decide`` — past every handler the
    decision round has. The tool that called this is holding a half-finished
    turn; an exception there says nothing about whether memory changed.
    """
    from zylch.memory.mnemonic import journal as journal_mod

    real_spend = journal_mod.spend_allowance
    calls = {"n": 0}

    def fail_once(event_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise journal_mod.JournalError("database is locked")
        return real_spend(event_id)

    with monkeypatch.context() as patched:
        patched.setattr(journal_mod, "spend_allowance", fail_once)
        result = submit(event(), client=client(create_decision()), context=context)

    assert result.outcome == "retryable_failure"
    assert "locked" in result.reason
    assert stored_blobs() == []


def test_the_tool_reports_a_journal_failure_instead_of_raising(profile_a, monkeypatch, embedder):
    """The same failure, seen from the surface a human actually uses."""
    from zylch.memory.mnemonic import session as session_mod

    llm = client(create_decision())
    tool = tool_with(llm, monkeypatch)
    with monkeypatch.context() as patched:
        patched.setattr(
            session_mod,
            "session_factory",
            Mock(side_effect=session_mod.JournalError("database is locked")),
        )
        result = run_tool(tool, content="Acme pays at 60 days", entry_type="entity_fact")

    assert result.status.value == "error"
    assert "locked" in result.error
    assert stored_blobs() == []


def test_an_event_settled_between_opening_and_claiming_returns_that_answer(
    profile_a, context, monkeypatch
):
    """Two attempts race; the loser reports the winner's result, not its own."""
    real_claim = journal.claim

    def settle_then_claim(event_id):
        journal.record_result(
            event_id,
            MnemonicResult.skipped(event_id, "the other attempt got there first"),
            state=journal.SKIPPED,
        )
        return real_claim(event_id)

    llm = client(create_decision())
    with monkeypatch.context() as patched:
        patched.setattr(journal, "claim", settle_then_claim)
        result = submit(event(), client=llm, context=context)

    assert result.outcome == "skipped"
    assert result.reason == "the other attempt got there first"
    assert llm._client.messages.create.call_count == 0
    assert stored_blobs() == []


# ─── Compare and swap ─────────────────────────────────────────────────


def seed_blob(context, content=ACME):
    return context.storage.store_blob(
        owner_id=OWNER_A,
        namespace=f"user:{COMPANY_A}",
        content=content,
        event_description="seed",
    )


def test_an_update_at_the_read_version_rewrites_the_blob_and_its_index(profile_a, context):
    blob = seed_blob(context)
    result = submit(
        event(event_id="evt-upd"),
        client=client(update_decision(blob["id"], blob["updated_at"])),
        context=context,
        requested=asked_to_update(blob["id"]),
    )

    assert result.outcome == "committed"
    with get_session() as session:
        row = session.get(Blob, blob["id"])
        assert "orders@acme.test" in row.content
        values = {
            r.value
            for r in session.query(PersonIdentifier).filter(PersonIdentifier.blob_id == blob["id"])
        }
    # The old address is GONE: an update that only appended would leave the
    # corrected-away identifier matching future lookups.
    assert "orders@acme.test" in values
    assert "info@acme.test" not in values


def test_a_second_writer_changing_the_blob_first_wins_and_the_stale_one_refuses(profile_a, context):
    blob = seed_blob(context)
    stale_version = blob["updated_at"]
    context.storage.update_blob(
        blob_id=blob["id"],
        owner_id=OWNER_A,
        content=ACME + "\n- another writer got here first",
        event_description="concurrent write",
    )

    result = submit(
        event(event_id="evt-cas"),
        client=client(
            update_decision(blob["id"], stale_version),
            update_decision(blob["id"], stale_version),
            update_decision(blob["id"], stale_version),
        ),
        context=context,
        requested=asked_to_update(blob["id"]),
    )

    assert result.outcome == "review_needed"
    with get_session() as session:
        assert "another writer got here first" in session.get(Blob, blob["id"]).content
        assert "orders@acme.test" not in session.get(Blob, blob["id"]).content


def mnemonic_reservations():
    from zylch.memory.mnemonic.agent import CALL_SITE
    from zylch.storage.models import LlmReservation

    with get_session() as session:
        return session.query(LlmReservation).filter(LlmReservation.call_site == CALL_SITE).count()


def test_a_cas_redecision_pays_exactly_one_reservation_per_round(profile_a, context):
    """Each re-read is a fresh paid decision — one reservation, no more, no less.

    The event's durable allowance is what ends the loop, so the three numbers
    have to agree: provider calls, reservations taken, and allowance consumed.
    """
    blob = seed_blob(context)
    stale = blob["updated_at"]
    context.storage.update_blob(
        blob_id=blob["id"], owner_id=OWNER_A, content=ACME + "\n- moved", event_description="x"
    )

    before = mnemonic_reservations()
    llm = client(*[update_decision(blob["id"], stale) for _ in range(EVENT_DISPATCH_ALLOWANCE)])
    result = submit(
        event(event_id="evt-cas2"),
        client=llm,
        context=context,
        requested=asked_to_update(blob["id"]),
    )

    assert result.outcome == "review_needed"
    calls = llm._client.messages.create.call_count
    assert 1 <= calls <= EVENT_DISPATCH_ALLOWANCE
    assert mnemonic_reservations() - before == calls
    assert journal.allowance_for("evt-cas2") == EVENT_DISPATCH_ALLOWANCE - calls


def test_a_target_that_vanished_is_a_conflict_not_a_new_entity(profile_a, context):
    """The one thing a stale proposal must never do is fall through to CREATE."""
    blob = seed_blob(context)
    version = blob["updated_at"]
    context.storage.delete_blob(blob["id"], OWNER_A)

    result = submit(
        event(event_id="evt-gone"),
        client=client(*[update_decision(blob["id"], version) for _ in range(3)]),
        context=context,
        requested=asked_to_update(blob["id"]),
    )

    assert result.outcome == "review_needed"
    assert stored_blobs() == []


# ─── What this slice will not do yet ──────────────────────────────────


def test_a_merge_proposal_is_recorded_for_review_and_writes_nothing(profile_a, context):
    keeper = seed_blob(context)
    donor = seed_blob(context, content=ACME.replace("Acme Srl", "ACME S.r.l."))
    merge = json.dumps(
        {
            "action": "MERGE",
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": ACME,
            "write_set": [
                {
                    "blob_id": keeper["id"],
                    "expected_version": keeper["updated_at"],
                    "role": "keeper",
                },
                {"blob_id": donor["id"], "expected_version": donor["updated_at"], "role": "donor"},
            ],
            "declared_effects": [f"alias:{donor['id']}->{keeper['id']}", f"delete:{donor['id']}"],
            "reason": "same company, shared email address",
        }
    )
    result = submit(
        event(
            event_id="evt-merge",
            observation="Acme Srl e ACME S.r.l. sono la stessa azienda, info@acme.test",
        ),
        client=client(merge, merge, merge),
        context=context,
    )

    assert result.outcome == "review_needed"
    assert len(stored_blobs()) == 2
    assert operation("evt-merge")["state"] == journal.REVIEW


def test_a_create_slice_refuses_an_update_instead_of_writing_it_the_old_way(profile_a, context):
    """A path that admits CREATE only answers a proposed change to existing
    memory with review — never the legacy direct write."""
    blob = seed_blob(context)
    result = submit(
        event(event_id="evt-slice"),
        client=client(update_decision(blob["id"], blob["updated_at"])),
        context=context,
        allow_actions=(CREATE,),
        requested=asked_to_update(blob["id"]),
    )

    assert result.outcome == "review_needed"
    assert "admits CREATE only" in result.reason
    with get_session() as session:
        assert "orders@acme.test" not in session.get(Blob, blob["id"]).content


# ─── Authorization, cancellation and budget, at the real boundary ─────


def test_an_authorization_refusal_costs_zero_paid_calls_and_zero_reservations(profile_a, context):
    from zylch.llm.budget import budget_snapshot

    before = budget_snapshot(OWNER_A)["spent_usd"]
    llm = client(create_decision())
    result = submit(event(owner=OWNER_B), client=llm, context=context)

    assert result.outcome == "review_needed"
    assert llm._client.messages.create.call_count == 0
    assert budget_snapshot(OWNER_A)["spent_usd"] == before
    assert stored_blobs() == []


def test_a_read_only_request_never_reaches_a_provider(profile_a, context):
    from zylch.services import request_policy

    llm = client(create_decision())
    with request_policy.policy_scope(request_policy.READ_ONLY_POLICY):
        result = submit(event(), client=llm, context=context)

    assert result.outcome == "review_needed"
    assert llm._client.messages.create.call_count == 0
    assert stored_blobs() == []


def test_cancellation_before_the_reservation_dispatches_nothing(profile_a, context):
    llm = client(create_decision())
    submitted = event()
    submitted.cancellation.cancel("user hit stop")
    result = submit(submitted, client=llm, context=context)

    assert result.outcome == "review_needed"
    assert llm._client.messages.create.call_count == 0
    assert stored_blobs() == []


def test_a_call_cancelled_in_flight_settles_its_usage_but_commits_nothing(profile_a, context):
    """Cancelling after dispatch does not un-bill the call — and does not write.

    This is the cancelled SDK thread: the request already reached the provider,
    so its usage settles against the ledger. What cancellation revokes is
    everything after it — the commit, and any further dispatch.
    """
    from zylch.llm.budget import budget_snapshot

    before = budget_snapshot(OWNER_A)["spent_usd"]
    submitted = event()

    def dispatch_then_cancel(**kwargs):
        # The provider has been reached; the reservation is already held.
        submitted.cancellation.cancel("user hit stop mid-flight")
        return text_response(create_decision())

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(side_effect=dispatch_then_cancel)

    result = submit(submitted, client=llm, context=context)

    assert result.outcome in ("review_needed", "retryable_failure")
    assert stored_blobs() == []
    assert budget_snapshot(OWNER_A)["spent_usd"] > before  # settled, not refunded
    assert llm._client.messages.create.call_count == 1  # and never redispatched


def set_preparation_state(owner, **columns):
    """Write preparation's own row directly — the state another run would leave."""
    from zylch.services import preparation

    assignments = ", ".join(f"{name}=?" for name in columns)
    with preparation._db() as conn:
        conn.exec_driver_sql("INSERT OR IGNORE INTO preparation_state(owner) VALUES (?)", (owner,))
        conn.exec_driver_sql(
            f"UPDATE preparation_state SET {assignments} WHERE owner=?",
            (*columns.values(), owner),
        )


@pytest.mark.parametrize(
    "state,columns",
    [
        ("busy", {"running": 1, "run_id": "another-run", "pid": os.getpid()}),
        ("exhausted", {"running": 1, "run_id": "r", "pid": os.getpid(), "attempted": 25}),
    ],
)
def test_an_interactive_commit_runs_while_preparation_is_busy_or_exhausted(
    profile_a, context, state, columns
):
    """The interactive contract rides the caller's own turn, so neither blocks it.

    A busy run belongs to another process and an exhausted batch is an
    automatic-work limit. Both would refuse background analysis; neither has
    anything to say about a human asking to remember something now.
    """
    from zylch.services import preparation

    set_preparation_state(OWNER_A, **columns)
    before = preparation.status(OWNER_A)

    result = submit(event(), client=client(create_decision()), context=context)

    assert result.outcome == "committed", state
    after = preparation.status(OWNER_A)
    for field in ("paused", "running", "attempted", "completed", "failed", "limit"):
        assert after[field] == before[field], field


def test_zero_budget_refuses_the_decision_without_writing(profile_a, tmp_path, context):
    """The cap is the saved profile's, so it is changed where the engine reads it."""
    from .mnemonic_env import write_env

    write_env(tmp_path / f"profile-{OWNER_A}", OWNER_A, COMPANY_A, budget_usd="0")
    llm = client(create_decision())
    result = submit(event(), client=llm, context=context)

    assert result.outcome == "retryable_failure"
    assert stored_blobs() == []
    assert operation()["state"] == journal.FAILED


def test_an_interactive_commit_leaves_bounded_preparation_exactly_as_it_was(profile_a, context):
    """Paused, busy or exhausted: the caller's own turn pays, so none of it moves."""
    from zylch.services import preparation

    preparation.pause(OWNER_A)
    before = preparation.status(OWNER_A)

    result = submit(event(), client=client(create_decision()), context=context)

    assert result.outcome == "committed"
    after = preparation.status(OWNER_A)
    assert after["paused"] is True
    for field in ("paused", "running", "attempted", "completed", "failed"):
        assert after[field] == before[field]


def test_a_restart_does_not_reset_the_decision_cap(profile_a, context, monkeypatch):
    """A crash loop must converge, not buy the event a fresh budget each time.

    The operation never reaches a terminal state — the process dies inside the
    transaction every time — so nothing replays and every restart is a genuine
    fresh attempt. What stops it is the allowance in the journal, which is the
    whole point: the in-process table this replaced would have reset with the
    process and the event would have paid forever.
    """
    embedder = context.storage.embeddings
    spent = 0
    for _ in range(EVENT_DISPATCH_ALLOWANCE + 2):
        llm = client(create_decision())
        with monkeypatch.context() as patched:
            patched.setattr(journal, "receipt", Mock(side_effect=KeyboardInterrupt("killed")))
            with pytest.raises(KeyboardInterrupt):
                submit(event(event_id="evt-restart"), client=llm, context=context)
        spent += llm._client.messages.create.call_count
        reboot()
        context = build_context(OWNER_A, embedder)

    assert spent == EVENT_DISPATCH_ALLOWANCE
    assert journal.allowance_for("evt-restart") == 0
    assert stored_blobs() == []

    # And once it is spent, a further attempt buys nothing at all.
    exhausted = client(create_decision())
    result = submit(event(event_id="evt-restart"), client=exhausted, context=context)
    assert exhausted._client.messages.create.call_count == 0
    assert result.outcome == "review_needed"


def test_a_policy_flip_during_the_call_stops_the_write_under_the_lock(profile_a, context):
    """Authorization is re-checked at the write, not only at the door.

    The read-only policy is per request and the model call takes seconds. A
    turn that became read-only while the role was thinking must not commit —
    and the check that stops it is the one inside the transaction, after the
    write lock, which is the last moment anything can.
    """
    from zylch.services import request_policy

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    entered = []

    def flip_then_answer(**kwargs):
        entered.append(request_policy.policy_scope(request_policy.READ_ONLY_POLICY))
        entered[-1].__enter__()
        return text_response(create_decision())

    llm._client.messages.create = Mock(side_effect=flip_then_answer)
    try:
        result = submit(event(), client=llm, context=context)
    finally:
        for scope in entered:
            scope.__exit__(None, None, None)

    assert llm._client.messages.create.call_count == 1  # it was dispatched
    assert result.outcome == "review_needed"
    assert stored_blobs() == []
    assert operation()["state"] == journal.REVIEW


def test_a_permit_issued_for_another_account_is_refused(profile_a, context):
    permit = issue_commit_permit(
        action=CREATE,
        company_key=COMPANY_A,
        owner_id=OWNER_B,
        event_id="evt-1",
        proposal_digest="d",
        content=ACME,
        namespace=f"user:{COMPANY_A}",
    )
    prepared = context.storage.prepare(ACME)
    with pytest.raises(PermitError, match="another account"):
        with journal.company_transaction() as session:
            context.storage.semantic_create(
                session,
                permit,
                owner_id=OWNER_A,
                namespace=f"user:{COMPANY_A}",
                prepared=prepared,
            )
    assert stored_blobs() == []


def test_the_production_wiring_commits_without_a_test_supplied_context(
    profile_a, monkeypatch, embedder
):
    """``default_context`` is what production actually runs on.

    Every other test here hands ``submit`` a context assembled by the test. If
    the real one were wired wrongly — the wrong owner, the wrong session
    factory — none of them would notice and every real commit would fail.
    """
    from zylch.memory.mnemonic import commit as commit_mod

    result = commit_mod.submit(event(), client=client(create_decision()))

    assert result.outcome == "committed"
    blob_id, _ = result.committed_ids[0]
    assert BlobStorage(get_session, embedder).get_blob(blob_id, OWNER_A) is not None


# ─── Company and account isolation ────────────────────────────────────


def test_a_second_company_shares_neither_the_memory_nor_the_journal(
    tmp_path, monkeypatch, embedder
):
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)

    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    first = submit(
        event(), client=client(create_decision()), context=build_context(OWNER_A, embedder)
    )
    assert first.outcome == "committed"

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_B)
    assert stored_blobs() == []
    assert operation() is None

    # Same event id, other company: a fresh operation, not a replay.
    second = submit(
        event(owner=OWNER_B, company=COMPANY_B),
        client=client(create_decision()),
        context=build_context(OWNER_B, embedder),
    )
    assert second.outcome == "committed"
    assert second.committed_ids != first.committed_ids
    dbm.dispose_engine()


def test_two_owners_sharing_a_key_see_one_memory_and_one_operation_history(
    tmp_path, monkeypatch, embedder
):
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)

    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    committed = submit(
        event(), client=client(create_decision()), context=build_context(OWNER_A, embedder)
    )
    assert committed.outcome == "committed"

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)
    blob_id, _ = committed.committed_ids[0]
    assert BlobStorage(get_session, embedder).get_blob(blob_id, OWNER_B) is not None
    assert journal.read("evt-1", owner_id=OWNER_B, company_key=COMPANY_A) is not None
    dbm.dispose_engine()


def test_two_independent_processes_commit_one_event_once(tmp_path, monkeypatch, embedder):
    """Two OS processes racing for one event id on one company store — one blob.

    They start together and wait on a file barrier before submitting, so this
    is contention and not a sequence. The fenced claim and the journal's
    idempotency are what make the outcome one commit; an in-memory mutex in
    either process could not see the other at all.
    """
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    dbm.dispose_engine()

    barrier = tmp_path / "go"
    script = textwrap.dedent("""
        import json, os, sys, time
        sys.path.insert(0, %(engine)r)
        from tests.memory.test_mnemonic_commit import (
            build_context, client, create_decision, event,
        )
        from tests.memory.conftest import BagOfWordsEmbedder
        from zylch.storage import database as dbm
        from zylch.memory.mnemonic.commit import submit
        import zylch.memory as memory_pkg, zylch.memory.embeddings as emb_mod

        embedder = BagOfWordsEmbedder()
        memory_pkg.EmbeddingEngine = lambda *a, **k: embedder
        emb_mod.EmbeddingEngine = lambda *a, **k: embedder
        dbm.init_db()
        context = build_context(%(owner)r, embedder)

        # Everything expensive is done; now line up on the barrier.
        open(%(barrier)r + "." + str(os.getpid()), "w").close()
        deadline = time.monotonic() + 30
        while not os.path.exists(%(barrier)r):
            if time.monotonic() > deadline:
                raise SystemExit("barrier never opened")
            time.sleep(0.01)

        result = submit(event(), client=client(create_decision()), context=context)
        print(json.dumps({"outcome": result.outcome, "ids": list(result.committed_ids)}))
        """ % {"engine": str(ENGINE_ROOT), "owner": OWNER_A, "barrier": str(barrier)})
    path = tmp_path / "commit_once.py"
    path.write_text(script)

    env = {**os.environ, "PYTHONPATH": str(ENGINE_ROOT)}
    procs = [
        subprocess.Popen(
            [sys.executable, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for _ in range(2)
    ]
    deadline = time.monotonic() + 120
    while len(list(tmp_path.glob("go.*"))) < 2:
        assert time.monotonic() < deadline, "a worker never reached the barrier"
        assert all(p.poll() is None for p in procs), "a worker died before the barrier"
        time.sleep(0.05)
    barrier.write_text("go")

    outcomes = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err[-2000:]
        outcomes.append(json.loads(out.strip().splitlines()[-1]))

    # The invariant is one commit, and nobody claiming one that did not happen.
    # The loser either replays the winner's answer (the winner had finished) or
    # says it may retry (it had not) — never a second blob, never a silent
    # success with different ids.
    assert any(o["outcome"] == "committed" for o in outcomes)
    assert all(o["outcome"] in ("committed", "retryable_failure") for o in outcomes)
    committed_ids = {tuple(map(tuple, o["ids"])) for o in outcomes if o["outcome"] == "committed"}
    assert len(committed_ids) == 1

    dbm.init_db()
    assert len(stored_blobs()) == 1
    dbm.dispose_engine()


# ─── The vertical slice: the real tool, end to end ────────────────────


def run_tool(tool, **kwargs):
    return asyncio.run(tool.execute(**kwargs))


def tool_with(llm, monkeypatch):
    """The real ``create_memory`` tool, with the real client behind the seam."""
    from zylch.assistant.turn_context import set_turn_observation
    from zylch.memory.mnemonic import commit as commit_mod
    from zylch.tools.create_memory_tool import CreateMemoryTool

    set_turn_observation("Acme Srl ordina da info@acme.test e paga a 60 giorni.")
    real_submit = commit_mod.submit
    monkeypatch.setattr(
        commit_mod, "submit", lambda ev, **kw: real_submit(ev, **{**kw, "client": llm})
    )
    import zylch.memory.mnemonic as pkg

    monkeypatch.setattr(pkg, "submit", commit_mod.submit)
    return CreateMemoryTool(owner_id=OWNER_A)


def test_the_tool_reports_success_only_after_a_committed_receipt_and_a_read_back(
    profile_a, monkeypatch, embedder
):
    llm = client(create_decision())
    tool = tool_with(llm, monkeypatch)

    result = run_tool(tool, content="Acme pays at 60 days", entry_type="entity_fact")

    assert result.status.value == "success"
    blob_id = result.data["blob_id"]
    assert result.data["action"] == "created"
    # The message carries the COMMITTED text read back from the store, not the
    # model's argument.
    assert "Acme Srl" in result.message
    with get_session() as session:
        assert session.get(Blob, blob_id) is not None
    assert operation(result.data["event_id"])["state"] == journal.COMMITTED


def test_the_tool_submits_what_the_human_said_not_the_model_rewrite(
    profile_a, monkeypatch, embedder
):
    llm = client(create_decision())
    tool = tool_with(llm, monkeypatch)
    run_tool(tool, content="totally different words from the model", entry_type="entity_fact")

    payload = llm._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Acme Srl ordina da info@acme.test" in payload


def test_the_observation_is_captured_before_chat_service_rewrites_the_message(
    profile_a, monkeypatch
):
    """The capture has to beat every rewrite in the chat entry point.

    ``ChatService.process_message`` does two things to the message before the
    agent ever sees it: the semantic command matcher can replace it with a
    slash command, and a task conversation prefixes it with a TASK CONTEXT
    block. Capturing downstream of those would make a Desktop task turn decide
    against ``"[TASK CONTEXT: task_id=…] Use these identifiers DIRECTLY…"`` —
    and would digest that as the source revision, so the same human sentence
    would look like two different observations depending on where it was typed.
    """
    import asyncio

    from zylch.assistant.turn_context import get_turn_observation, set_turn_observation
    from zylch.services.chat_service import ChatService

    said = "Ricordati che Acme paga a 60 giorni."
    seen = {}

    async def fake_agent_turn(user_message, **kwargs):
        seen["message"] = user_message
        seen["observation"] = get_turn_observation()
        return "ok"

    set_turn_observation("a stale value from an earlier turn")
    service = ChatService()
    # The agent is lazily built from the whole tool factory; stand in for it so
    # this test is about the entry point's ordering and nothing else.
    service.agent = SimpleNamespace(
        process_message=fake_agent_turn,
        clear_history=lambda: None,
        set_history=lambda _h: None,
        tools=[],
        last_truncations=[],
    )
    service._initialized = True

    async def already_initialized(owner_id=None):
        return None

    monkeypatch.setattr(service, "_initialize_agent", already_initialized)

    asyncio.run(
        service.process_message(
            user_message=said,
            user_id=OWNER_A,
            context={"user_id": OWNER_A, "task_id": "task-42", "email_id": "msg-7"},
        )
    )

    assert "[TASK CONTEXT: task_id=task-42" in seen["message"]  # the rewrite happened
    assert seen["observation"] == said  # and the observation escaped it


def test_the_tool_refuses_when_no_turn_stands_behind_the_call(profile_a, monkeypatch, embedder):
    from zylch.assistant.turn_context import set_turn_observation
    from zylch.tools.create_memory_tool import CreateMemoryTool

    set_turn_observation("")
    result = run_tool(
        CreateMemoryTool(owner_id=OWNER_A), content="anything", entry_type="entity_fact"
    )

    assert result.status.value == "error"
    assert "needs the turn" in result.error
    assert stored_blobs() == []


def test_there_is_one_path_and_it_goes_through_the_journal(tmp_path, monkeypatch, embedder):
    """No setting selects a writer: `create_memory` submits, always.

    A create opens an operation, decides through the role and commits — the
    journal row is the proof that the harness served the call. There is no
    direct writer to fall back to (brief amendment, 2026-09-23).
    """
    from .mnemonic_env import stub_embedder

    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    try:
        tool = tool_with(client(create_decision()), monkeypatch)
        result = run_tool(tool, content=ACME, entry_type="entity_fact")
        assert result.status.value == "success", result.error
        assert len(stored_blobs()) == 1
        with get_session() as session:
            assert session.query(MemoryOperation).count() == 1
    finally:
        dbm.dispose_engine()


def test_a_chat_turn_reaches_the_identity_index_in_its_own_form(profile_a, embedder):
    """A dotted address typed in chat finds the row the index holds for it.

    The index stores an address as written and lowercased; the comparison
    tokens strip its dots. The lookup is built in the index's own form —
    proven end to end with the search switched off, so only the identifier
    path can surface the row, and with the dot-stripped form shown to find
    nothing.
    """
    storage = BlobStorage(get_session, embedder)
    giulia = (
        "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Giulia Verdi\n"
        "Email: giulia.verdi@acme.test\n#ABOUT\nRuns procurement."
    )
    blob = storage.store_blob(
        owner_id=OWNER_A, namespace=f"user:{COMPANY_A}", content=giulia, event_description="seed"
    )
    rows = Storage()
    rows.add_person_identifiers(OWNER_A, blob["id"], [("email", "giulia.verdi@acme.test")])
    assert rows.find_blobs_by_identifiers(OWNER_A, [("email", "giuliaverdi@acmetest")]) == []
    context = CommitContext(
        storage=storage,
        get_blob=lambda blob_id: storage.get_blob(blob_id, OWNER_A),
        search=lambda _query, _limit: (),  # only the identifier path can find the row
        identifier_blob_ids=lambda ids: rows.find_blobs_by_identifiers(OWNER_A, list(ids)),
    )
    llm = client(json.dumps({"action": "SKIP", "reason": "nothing new about her"}))

    result = submit(
        event(observation="Giulia.Verdi@acme.test ha chiamato: nulla di nuovo da annotare."),
        client=llm,
        context=context,
    )

    assert result.outcome == "skipped", result.reason
    payload = llm._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert blob["id"] in payload
    assert '"retrieved_by": "identifier-only"' in payload
    assert '"shared_identifiers": 1' in payload
