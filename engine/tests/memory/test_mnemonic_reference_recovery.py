"""The follow-up a merge owes its profile: recorded, idempotent, and only where it belongs.

A merge commits in the company store; the task ledger of the profile that
committed it lives in another file and is re-pointed afterwards, from an effect
the merge's own receipt recorded. These cases run real merges through the real
harness and then look at the ledger and the receipt: only the donor's id
changes in the ledger, a crash after the company commit leaves the effect on
record for the next replay, another profile's file is never opened, a profile
that has since joined another company applies nothing, and alias chains resolve
from either end.
"""

from __future__ import annotations

import hashlib
import os
from unittest.mock import Mock

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.mnemonic import references
from zylch.memory.mnemonic.proposals import PendingEffect
from zylch.memory.scope import resolve_aliases
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation, TaskItem
from zylch.storage.storage import Storage

from tests.memory.mnemonic_env import (
    COMPANY_A,
    COMPANY_B,
    OWNER_A,
    OWNER_B,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    client,
    stub_embedder,
)
from tests.memory.test_mnemonic_merge import (
    LUCA_CAL,
    LUCA_MAIL,
    LUCA_THIRD,
    make,
    merge_decision,
    read,
    run,
    seed,
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


def seed_task(owner, task_id, blobs):
    with get_session() as session:
        session.add(
            TaskItem(
                id=task_id,
                owner_id=owner,
                event_type="email",
                event_id=f"ev-{task_id}",
                contact_email="luca@alpha.example",
                title=f"Call Luca ({task_id})",
                urgency="high",
                reason="asked for a quote",
                suggested_action="call back",
                action_required=True,
                sources={"blobs": list(blobs), "emails": ["mail-9"]},
            )
        )


def task(task_id):
    with get_session() as session:
        return session.get(TaskItem, task_id).to_dict()


def pending(event_id):
    with get_session() as session:
        return session.get(MemoryOperation, event_id).pending_effects


def merge(store, keeper, donor):
    pair_ = make(store, keeper, donor)
    result = run(pair_, client(merge_decision(read(store, keeper), read(store, donor))))
    assert result.outcome == "committed", result.reason
    return result, pair_["event"].event_id


# ─── What the follow-up changes ───────────────────────────────────────


def test_the_follow_up_rewrites_only_the_donors_id_in_this_owners_ledger(store):
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    seed_task(OWNER_A, "t-1", [donor, "other-blob", keeper])
    seed_task(OWNER_A, "t-2", ["other-blob"])
    seed_task(OWNER_B, "t-3", [donor])  # another account's row in this file
    before = {t: task(t) for t in ("t-1", "t-2", "t-3")}

    result, event_id = merge(store, keeper, donor)

    assert result.pending_effects == () and pending(event_id) == []
    after = {t: task(t) for t in ("t-1", "t-2", "t-3")}
    assert after["t-1"]["sources"] == {"blobs": [keeper, "other-blob"], "emails": ["mail-9"]}
    unchanged = {k: v for k, v in before["t-1"].items() if k != "sources"}
    assert {k: v for k, v in after["t-1"].items() if k != "sources"} == unchanged
    assert after["t-2"] == before["t-2"] and after["t-3"] == before["t-3"]


def test_a_crash_after_the_company_commit_leaves_the_effect_for_one_replay(store, monkeypatch):
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    seed_task(OWNER_A, "t-1", [donor])
    with monkeypatch.context() as patched:  # the profile file fails after the commit
        patched.setattr(references, "_rewrite_ledger", Mock(side_effect=OSError("profile busy")))
        result, event_id = merge(store, keeper, donor)

    effect = PendingEffect(kind="task_references", detail=f"{donor}->{keeper}")
    assert result.outcome == "committed" and result.pending_effects == (effect,)
    assert pending(event_id) == [{"kind": "task_references", "detail": f"{donor}->{keeper}"}]
    assert task("t-1")["sources"]["blobs"] == [donor]
    with get_session() as session:
        assert keeper in resolve_aliases(session, [donor])  # readable meanwhile

    assert references.replay_pending(OWNER_A) == {"references_resolved": 1, "references_pending": 0}
    assert task("t-1")["sources"]["blobs"] == [keeper] and pending(event_id) == []
    assert references.replay_pending(OWNER_A) == {"references_resolved": 0, "references_pending": 0}
    assert task("t-1")["sources"]["blobs"] == [keeper]


# ─── Only where it belongs ────────────────────────────────────────────


def test_another_profiles_file_is_never_opened_and_resolves_the_donor(store, tmp_path, monkeypatch):
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)  # the second profile, same company
    seed_task(OWNER_B, "t-b", [donor])
    dbm.dispose_engine()
    b_file = tmp_path / f"profile-{OWNER_B}" / "zylch.db"
    digest = hashlib.sha256(b_file.read_bytes()).hexdigest()
    os.chmod(b_file, 0)  # unavailable: any attempt to open it would fail
    try:
        boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
        result, _ = merge(store, keeper, donor)
        assert result.pending_effects == ()
    finally:
        os.chmod(b_file, 0o600)
    assert hashlib.sha256(b_file.read_bytes()).hexdigest() == digest

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)
    assert task("t-b")["sources"]["blobs"] == [donor]  # untouched, and still found:
    found = Storage().get_open_tasks_by_blobs(OWNER_B, [keeper])
    assert [t["id"] for t in found] == ["t-b"]


def test_a_profile_bound_to_another_company_applies_nothing(store, tmp_path, monkeypatch):
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    seed_task(OWNER_A, "t-1", [donor])
    with monkeypatch.context() as patched:
        patched.setattr(references, "_rewrite_ledger", Mock(side_effect=OSError("profile busy")))
        _, event_id = merge(store, keeper, donor)

    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_B)  # the profile joined another company
    assert references.replay_pending(OWNER_A) == {"references_resolved": 0, "references_pending": 0}
    assert references.apply(event_id, owner_id=OWNER_A) == ()  # not in this store at all
    assert task("t-1")["sources"]["blobs"] == [donor]

    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    assert references.replay_pending(OWNER_A) == {"references_resolved": 1, "references_pending": 0}
    assert task("t-1")["sources"]["blobs"] == [keeper]


def test_another_account_never_applies_a_merges_follow_up(store, tmp_path, monkeypatch):
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    with monkeypatch.context() as patched:
        patched.setattr(references, "_rewrite_ledger", Mock(side_effect=OSError("profile busy")))
        _, event_id = merge(store, keeper, donor)

    boot(monkeypatch, tmp_path, OWNER_B, COMPANY_A)  # same company, another account
    seed_task(OWNER_B, "t-b", [donor])
    left = references.apply(event_id, owner_id=OWNER_B)
    assert left == (PendingEffect(kind="task_references", detail=f"{donor}->{keeper}"),)
    assert references.replay_pending(OWNER_B) == {"references_resolved": 0, "references_pending": 0}
    assert task("t-b")["sources"]["blobs"] == [donor] and pending(event_id) != []


def test_the_immediate_follow_up_checks_the_binding_too(store, monkeypatch):
    keeper, donor = seed(store, LUCA_MAIL), seed(store, LUCA_CAL)
    seed_task(OWNER_A, "t-1", [donor])
    with monkeypatch.context() as patched:
        patched.setattr(references, "current_company_key", lambda: COMPANY_B)
        result, event_id = merge(store, keeper, donor)

    assert result.pending_effects != () and pending(event_id) != []
    assert task("t-1")["sources"]["blobs"] == [donor]


# ─── Chains ───────────────────────────────────────────────────────────


def test_alias_chains_resolve_from_either_end(store):
    first_donor, keeper, final = (
        seed(store, LUCA_CAL),
        seed(store, LUCA_MAIL),
        seed(store, LUCA_THIRD),
    )
    seed_task(OWNER_A, "t-a", [first_donor])
    seed_task(OWNER_B, "t-b", [first_donor])  # a ledger no follow-up of ours rewrites

    merge(store, keeper, first_donor)  # first_donor -> keeper
    merge(store, final, keeper)  # keeper -> final: the keeper is now a donor

    with get_session() as session:
        assert {first_donor, keeper, final} <= resolve_aliases(session, [first_donor])
        assert {first_donor, keeper} <= resolve_aliases(session, [final])
    assert task("t-a")["sources"]["blobs"] == [final]  # re-pointed twice
    assert task("t-b")["sources"]["blobs"] == [first_donor]
    found = Storage().get_open_tasks_by_blobs(OWNER_B, [final])
    assert [t["id"] for t in found] == ["t-b"]
