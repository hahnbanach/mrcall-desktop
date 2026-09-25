"""The MERGE commit: one pair, one company transaction, nothing lost.

Every case runs a real consolidation pair through the real harness — the pair
admitted as a preparation item, the real `LLMClient` with only the transport
scripted, the real validator, the real permit and the real split stores — and
checks what the transaction left behind: the keeper rewritten with its replaced
text retained, the donor gone with its final text retained, every source link
on the survivor, the identifiers its merged text states and no others, the
alias, one bump of the mutation sequence and the receipt. And what it must not
leave behind: anything at all, when a member went stale, when a third memory
is named, when any one of its writes fails, or when the MERGE did not come
from consolidation's own item for that very pair.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from unittest.mock import Mock

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.blob_versions import CONSOLIDATE, list_versions
from zylch.memory.mnemonic import pairs
from zylch.memory.mnemonic.commit import submit
from zylch.memory.mnemonic.contracts import (
    CREATE,
    INTERACTIVE,
    MERGE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
)
from zylch.services.preparation import preparation_run
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import (
    Blob,
    BlobAlias,
    BlobVersion,
    CalendarBlob,
    EmailBlob,
    MemoryMeta,
    MemoryOperation,
    PersonIdentifier,
    WhatsAppBlob,
)
from zylch.storage.storage import Storage

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    client,
    stub_embedder,
    text_response,
)

HEADER = "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Luca Bianchi\n"
LUCA_MAIL = (
    HEADER + "Email: luca@alpha.example\n#ABOUT\nPurchasing at Alpha.\n#HISTORY\n- ordered 40 units"
)
LUCA_CAL = (
    HEADER + "Email: luca@alpha.example\n#ABOUT\nJoins the Thursday sync.\n#HISTORY\n- invited"
)
LUCA_THIRD = HEADER + "Email: luca@alpha.example\n#ABOUT\nA third record.\n#HISTORY\n- called once"
MERGED = (
    HEADER + "Email: luca@alpha.example\n#ABOUT\nPurchasing at Alpha; joins the Thursday sync."
    "\n#HISTORY\n- ordered 40 units\n- invited"
)


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def store(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    yield BlobStorage(get_session, embedder)
    dbm.dispose_engine()
    clear_process_state()


def seed(store, content):
    return store.store_blob(OWNER_A, f"user:{COMPANY_A}", content, "seed")["id"]


def read(store, blob_id):
    return store.get_blob(blob_id, OWNER_A)


def make(store, keeper_id, donor_id, *, pinned=None):
    pair_ = pairs.pair(store, OWNER_A, COMPANY_A, read(store, keeper_id), read(store, donor_id))
    if pinned is not None:  # a context pinned to another pair than the event names
        pair_["context"] = pairs.pair_context(store, OWNER_A, *(read(store, b) for b in pinned))
    return pair_


def merge_decision(keeper, donor, *, effects=None, content=MERGED):
    return json.dumps(
        {
            "action": MERGE,
            "entity_type": "PERSON",
            "scope": "entity",
            "content": content,
            "write_set": [
                {
                    "blob_id": keeper["id"],
                    "expected_version": keeper["updated_at"],
                    "role": "keeper",
                },
                {"blob_id": donor["id"], "expected_version": donor["updated_at"], "role": "donor"},
            ],
            "declared_effects": effects
            or [f"alias:{donor['id']}->{keeper['id']}", f"delete:{donor['id']}"],
            "reason": "both headers state the same email address",
        }
    )


def run(pair_, llm, *, decide=None):
    """One pair as consolidation runs it: an admitted preparation item."""
    item = pairs.PairItem(OWNER_A, decide or (lambda p: pairs.decide(p, client=llm)))
    with preparation_run(OWNER_A):
        asyncio.run(item.run(pair_))
    return item.results.get(pair_["id"])


def seed_pair(store):
    """Keeper and donor with identifiers and links, as ingestion would leave them."""
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    rows = Storage()
    # Each blob also carries an index row no text states — a sender address or a
    # switchboard a legacy writer attached. A merge must not keep or spread either.
    rows.add_person_identifiers(
        OWNER_A, keeper, [("email", "luca@alpha.example"), ("phone", "+390200000000")]
    )
    rows.add_person_identifiers(
        OWNER_A, donor, [("email", "luca@alpha.example"), ("email", "sender@shop.example")]
    )
    for email_id, blob_id in (
        ("mail-1", keeper),
        ("mail-2", donor),
        ("mail-3", keeper),
        ("mail-3", donor),
    ):
        rows.add_email_blob_link(OWNER_A, email_id, blob_id)
    rows.add_calendar_blob_link(OWNER_A, "cal-1", donor)
    rows.add_whatsapp_blob_link(OWNER_A, "wa-1", donor)
    return keeper, donor


def state():
    """Everything a merge may touch, as comparable values."""
    with get_session() as s:
        return {
            "blobs": {b.id: b.content for b in s.query(Blob).all()},
            "versions": {(v.blob_id, v.reason, v.content) for v in s.query(BlobVersion).all()},
            "links": links(s),
            "identifiers": {(r.blob_id, r.kind, r.value) for r in s.query(PersonIdentifier).all()},
            "aliases": {(r.merged_id, r.keeper_id) for r in s.query(BlobAlias).all()},
            "seq": s.query(MemoryMeta.mutation_seq).filter(MemoryMeta.id == 1).scalar(),
        }


def links(session):
    return (
        {("email", r.email_id, r.blob_id) for r in session.query(EmailBlob).all()}
        | {("calendar", r.event_id, r.blob_id) for r in session.query(CalendarBlob).all()}
        | {
            ("whatsapp", r.whatsapp_message_id, r.blob_id)
            for r in session.query(WhatsAppBlob).all()
        }
    )


def versions(blob_id):
    with get_session() as s:
        return [(v.reason, v.content, v.operation_id) for v in list_versions(s, blob_id)]


def operation(event_id):
    with get_session() as s:
        row = s.get(MemoryOperation, event_id)
        return None if row is None else row.to_dict()


# ─── The merge ────────────────────────────────────────────────────────


def test_a_pairs_merge_commits_every_effect_in_one_transaction(store):
    keeper, donor = seed_pair(store)
    pair_ = make(store, keeper, donor)
    before = state()
    llm = client(merge_decision(read(store, keeper), read(store, donor)))

    result = run(pair_, llm)

    assert result.outcome == "committed", result.reason
    assert result.committed_ids[0][0] == keeper
    after = state()
    assert after["blobs"] == {keeper: MERGED}
    event_id = pair_["event"].event_id
    # Both halves retained, stamped as consolidation's own and as this operation.
    assert versions(keeper) == [(CONSOLIDATE, LUCA_MAIL, event_id)]
    assert versions(donor) == [(CONSOLIDATE, LUCA_CAL, event_id)]
    # Every source either blob was extracted from reaches the survivor.
    assert after["links"] == {
        ("email", "mail-1", keeper),
        ("email", "mail-2", keeper),
        ("email", "mail-3", keeper),
        ("calendar", "cal-1", keeper),
        ("whatsapp", "wa-1", keeper),
    }
    # What the merged text states, and neither legacy row nobody stated.
    assert after["identifiers"] == {(keeper, "email", "luca@alpha.example")}
    assert after["aliases"] == {(donor, keeper)}
    assert after["seq"] == before["seq"] + 1
    receipt = operation(event_id)
    assert receipt["state"] == "committed"
    # The recorded ledger follow-up ran right after the company commit and was
    # cleared; test_mnemonic_reference_recovery.py shows it recorded when it fails.
    assert receipt["pending_effects"] == [] and result.pending_effects == ()
    assert llm._client.messages.create.call_count == 1


def test_a_duplicate_replay_of_a_committed_pair_pays_nothing_and_writes_nothing(store):
    keeper, donor = seed_pair(store)
    pair_ = make(store, keeper, donor)
    first = run(pair_, client(merge_decision(read(store, keeper), read(store, donor))))
    assert first.outcome == "committed"
    before = state()
    silent = client()  # any provider call would raise

    again = submit(pair_["event"], client=silent, context=pair_["context"], allow_actions=(MERGE,))

    assert again.outcome == "committed" and again.committed_ids == first.committed_ids
    assert silent._client.messages.create.call_count == 0
    assert state() == before


# ─── A member that moved ──────────────────────────────────────────────


@pytest.mark.parametrize("stale", ["keeper", "donor"])
def test_a_stale_member_ends_the_pair_unpaid_and_the_next_pairing_commits(store, stale):
    keeper, donor = seed_pair(store)
    k, d = read(store, keeper), read(store, donor)
    pair_ = make(store, keeper, donor)
    moved = keeper if stale == "keeper" else donor

    def another_writer_then_answer(*_args, **_kwargs):
        store.update_blob(
            blob_id=moved,
            owner_id=OWNER_A,
            content=read(store, moved)["content"] + "\n- another writer got here first",
            event_description="concurrent",
        )
        return text_response(merge_decision(k, d))

    llm = client()
    llm._client.messages.create = Mock(side_effect=another_writer_then_answer)
    result = run(pair_, llm)

    assert result.outcome == "skipped" and result.reason == pairs.PAIR_CHANGED
    assert llm._client.messages.create.call_count == 1  # the changed pair costs no second call
    now = state()
    assert set(now["blobs"]) == {keeper, donor} and "another writer" in now["blobs"][moved]
    assert CONSOLIDATE not in {reason for reason, _, _ in versions(keeper) + versions(donor)}
    assert now["aliases"] == set()

    fresh_k, fresh_d = read(store, keeper), read(store, donor)
    again = run(make(store, keeper, donor), client(merge_decision(fresh_k, fresh_d)))
    assert again.outcome == "committed" and set(state()["blobs"]) == {keeper}


def test_a_member_gone_before_the_round_settles_the_pair_without_a_paid_call(store):
    keeper, donor = seed_pair(store)
    pair_ = make(store, keeper, donor)
    assert store.delete_blob(donor, OWNER_A) is True  # the owner deleted it meanwhile
    llm = client()

    result = run(pair_, llm)

    assert result.outcome == "skipped" and result.reason == pairs.PAIR_CHANGED
    assert llm._client.messages.create.call_count == 0
    assert state()["blobs"] == {keeper: LUCA_MAIL}


# ─── What a merge may touch ───────────────────────────────────────────


@pytest.mark.parametrize("where", ["write_set", "declared_effect"])
def test_an_undeclared_third_entity_is_refused_and_nothing_is_touched(store, where):
    keeper, donor = seed_pair(store)
    third = seed(store, LUCA_THIRD)
    k, d, x = read(store, keeper), read(store, donor), read(store, third)
    decision = (
        merge_decision(k, x)
        if where == "write_set"
        else merge_decision(k, d, effects=[f"alias:{donor}->{keeper}", f"delete:{third}"])
    )
    before = state()

    result = run(make(store, keeper, donor), client(decision, decision, decision))

    assert result.outcome == "review_needed"
    assert state() == before


@pytest.mark.parametrize(
    "target, attr",
    [
        ("zylch.memory.blob_storage", "retain_version"),
        ("zylch.memory.blob_storage:BlobStorage", "_rewrite"),
        ("zylch.memory.blob_storage:BlobStorage", "delete_blob"),
        ("zylch.memory.associations", "links_of"),
        ("zylch.memory.associations", "link_source"),
        ("zylch.memory.associations", "drop_identifiers"),
        ("zylch.memory.associations", "add_identifiers"),
        ("zylch.memory.associations", "record_alias"),
        ("zylch.memory.store", "bump_mutation_seq"),
        ("zylch.memory.mnemonic.journal", "receipt"),
    ],
)
def test_a_failure_at_any_company_write_leaves_everything_as_it_was(
    store, monkeypatch, target, attr
):
    keeper, donor = seed_pair(store)
    pair_ = make(store, keeper, donor)
    llm = client(merge_decision(read(store, keeper), read(store, donor)))
    before = state()
    module, _, cls = target.partition(":")
    owner = importlib.import_module(module)
    with monkeypatch.context() as patched:
        patched.setattr(
            getattr(owner, cls) if cls else owner, attr, Mock(side_effect=RuntimeError(attr))
        )
        result = run(pair_, llm)

    assert result.outcome == "retryable_failure", result.reason
    assert state() == before
    # Failed, or still pending when the receipt itself is what failed (recording
    # the failure goes through it too): resumable either way, never committed.
    assert operation(pair_["event"].event_id)["state"] in ("failed", "pending")


# ─── Only consolidation's own item for that very pair ─────────────────


def test_a_merge_outside_consolidation_stays_review(store):
    keeper, donor = seed_pair(store)
    k, d = read(store, keeper), read(store, donor)
    chat = MemoryEvent(
        event_id="evt-chat-merge",
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="Luca Bianchi, luca@alpha.example, is one person in both records.",
    )
    before = state()

    result = submit(
        chat,
        client=client(merge_decision(k, d)),
        context=pairs.pair_context(store, OWNER_A, k, d),
        allow_actions=(CREATE, UPDATE, MERGE),
    )

    assert result.outcome == "review_needed" and result.reason == pairs.MERGE_OUTSIDE_CONSOLIDATION
    assert state() == before


def test_a_merge_without_merge_in_allow_actions_stays_review(store):
    keeper, donor = seed_pair(store)
    llm = client(merge_decision(read(store, keeper), read(store, donor)))

    result = run(
        make(store, keeper, donor),
        llm,
        decide=lambda p: submit(
            p["event"], client=llm, context=p["context"], allow_actions=(CREATE, UPDATE)
        ),
    )

    assert result.outcome == "review_needed" and result.reason == pairs.MERGE_OUTSIDE_CONSOLIDATION
    assert set(state()["blobs"]) == {keeper, donor}


def test_a_merge_of_another_pair_than_the_event_names_stays_review(store):
    keeper, donor = seed_pair(store)
    third = seed(store, LUCA_THIRD)
    before = state()

    result = run(
        make(store, keeper, donor, pinned=(keeper, third)),
        client(merge_decision(read(store, keeper), read(store, third))),
    )

    assert result.outcome == "review_needed" and result.reason == pairs.MERGE_OTHER_PAIR
    assert state() == before


def test_a_pair_submitted_outside_its_admitted_item_is_refused_before_any_call(store):
    keeper, donor = seed_pair(store)
    pair_ = make(store, keeper, donor)
    llm = client()
    before = state()

    with preparation_run(OWNER_A):  # a run, but no admitted item for this pair
        result = submit(
            pair_["event"], client=llm, context=pair_["context"], allow_actions=(MERGE,)
        )

    assert result.outcome == "review_needed"
    assert llm._client.messages.create.call_count == 0
    assert state() == before


def test_a_retaining_drop_outside_a_callers_transaction_is_refused(store):
    donor = seed(store, LUCA_CAL)
    with pytest.raises(ValueError):
        store.delete_blob(donor, OWNER_A, retain=True)
    assert read(store, donor) is not None
    with get_session() as session:
        assert list_versions(session, donor) == []
