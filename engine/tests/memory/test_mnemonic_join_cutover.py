"""A company-memory join refuses while the joining account's source work is unsettled.

On the ingestion bench (``tests/workers/ingestion_env.py``): the real worker on
real split databases, both clients scripted at the transport, every source run
inside an admitted preparation run; the destination is a second real company
store beside the source. Each unsettled state is produced the way the engine
produces it — a crash between children, a crash before the checkpoint, a
review, a provider failure — and each refuses the join, releases the fence and
leaves the profile's ``.env`` byte for byte (AC2). ``--drain`` is refused by a
paused or busy preparation without a paid call, and with preparation free it
runs one ordinary memory pass that settles what it can (AC3). The crash points
of the cutover itself are ``test_mnemonic_join_crashes.py``.
"""

from __future__ import annotations

import json
import os

import pytest

from zylch.memory.company_key import current_company_key
from zylch.memory.join import BLOCKED, DRAIN, join
from zylch.memory.mnemonic import journal, pairs
from zylch.memory.mnemonic.contracts import INTERACTIVE, OPERATOR_DELEGATED, MemoryEvent
from zylch.memory.mnemonic.fence import COMPLETED, RELEASED
from zylch.memory.mnemonic.proposals import MnemonicResult, PendingEffect
from zylch.services import preparation
from zylch.storage.storage import Storage

from tests.memory.join_env import count, destination, env_bytes, isolate, phases, receipts
from tests.memory.mnemonic_env import COMPANY_A, COMPANY_B, OWNER_A, OWNER_B, BagOfWordsEmbedder
from tests.workers.ingestion_env import (
    ACME,
    LUCA,
    NAME_ONLY,
    Crash,
    booted,
    children_of,
    create_decision,
    email_processed,
    extraction,
    make_worker,
    operations,
    parent_of,
    resume,
    run,
    seed_email,
)

EMAIL_A = f"{OWNER_A}@company.test"
UNCLEAR = json.dumps({"action": "REVIEW", "reason": "which Acme is this"})
NOTHING = json.dumps({"action": "SKIP", "reason": "a passing mention, nothing durable"})
MARTA = (
    "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Marta Riva\n"
    "Email: marta@beta.example\n#ABOUT\nFinance lead at Beta.\n#HISTORY\n- wrote about the invoice"
)


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    isolate(monkeypatch)
    bench = booted(tmp_path, monkeypatch, embedder)
    joined = next(bench)
    destination()
    yield joined
    next(bench, None)


def refused():
    """Join, expect the refusal, and prove nothing moved: ``.env``, key, fence, destination."""
    before = env_bytes()
    out = join(COMPANY_B)
    assert out["ok"] is False and out["reason"] == BLOCKED, out
    assert env_bytes() == before and current_company_key() == COMPANY_A
    assert phases(COMPANY_A) == [RELEASED]
    assert count(COMPANY_B, "blobs") == 0 and count(COMPANY_B, "memory_operations") == 0
    return {row["event_id"]: row for row in out["blocking"]}


def chat_event(event_id: str, owner: str = OWNER_A) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        owner_id=owner,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="Acme Srl pays at 60 days.",
    )


# ─── AC2: every blocking state ────────────────────────────────────────


def test_a_source_with_one_committed_child_and_an_undecided_remainder_blocks(profile):
    worker = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), Crash()])
    with pytest.raises(Crash):
        run(worker, "process_email", seed_email())
    parent = parent_of("mail-1")["event_id"]
    assert operations()[f"{parent}:0"]["state"] == journal.COMMITTED

    blocking = refused()

    assert set(blocking) == {parent, f"{parent}:1"}
    assert blocking[parent]["state"] == blocking[f"{parent}:1"]["state"] == journal.PENDING
    assert blocking[parent]["verb"].startswith(DRAIN)
    assert blocking[parent]["source_ref"].startswith("email:mail-1@")


def test_a_committed_parent_whose_checkpoint_has_not_landed_blocks(profile, monkeypatch):
    def crash(*args, **kwargs):
        raise Crash()

    monkeypatch.setattr(Storage, "mark_email_processed", crash)
    with pytest.raises(Crash):
        run(make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")]), "process_email", seed_email())
    parent = parent_of("mail-1")
    assert parent["state"] == journal.COMMITTED and not email_processed("mail-1")

    blocking = refused()

    assert set(blocking) == {parent["event_id"]}
    assert blocking[parent["event_id"]]["verb"] == DRAIN


def test_a_child_in_review_blocks_with_the_verbs_that_settle_it(profile):
    worker = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), UNCLEAR])
    assert run(worker, "process_email", seed_email()) is False
    parent = parent_of("mail-1")["event_id"]

    blocking = refused()

    assert set(blocking) == {parent, f"{parent}:1"}
    assert blocking[f"{parent}:1"]["state"] == journal.REVIEW
    assert blocking[f"{parent}:1"]["verb"] == f"zylch memory-reviews --retry {parent}:1 (or --dismiss)"
    assert blocking[parent]["verb"] == f"zylch memory-reviews --dismiss {parent}"


def test_a_failed_child_blocks(profile, monkeypatch):
    from zylch.memory.mnemonic import commit

    def broken(*args, **kwargs):
        raise RuntimeError("database disk image is malformed")

    monkeypatch.setattr(commit, "_commit", broken)
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    assert run(worker, "process_email", seed_email()) is False
    parent = parent_of("mail-1")["event_id"]
    assert children_of(parent)[f"{parent}:0"]["state"] == journal.FAILED

    blocking = refused()

    assert blocking[f"{parent}:0"]["state"] == journal.FAILED
    assert f"{parent}:0" in blocking and parent in blocking


def test_a_failed_chat_event_blocks_and_is_dismissed_not_drained(profile):
    event = chat_event("turn-failed")
    journal.open_operation(event)
    journal.record_result(
        event.event_id,
        MnemonicResult.retryable_failure(event.event_id, "provider down"),
        state=journal.FAILED,
    )

    blocking = refused()

    assert blocking == {
        "turn-failed": {
            "event_id": "turn-failed",
            "state": journal.FAILED,
            "source_ref": "chat:turn:1@rev-1",
            "verb": "zylch memory-reviews --dismiss turn-failed",
        }
    }


def test_a_committed_merge_with_a_pending_task_reference_effect_blocks(profile):
    first = {"id": "blob-keeper", "content": "Name: Luca", "updated_at": "v1"}
    second = {"id": "blob-donor", "content": "Name: Luca", "updated_at": "v2"}
    event = pairs.pair_event(OWNER_A, COMPANY_A, first, second)
    journal.open_operation(event)
    journal.record_result(
        event.event_id,
        MnemonicResult.committed(
            event.event_id,
            (("blob-keeper", "v3"),),
            pending=(PendingEffect("task_references", "blob-donor->blob-keeper"),),
        ),
        state=journal.COMMITTED,
    )

    blocking = refused()

    assert set(blocking) == {event.event_id}
    assert blocking[event.event_id]["state"] == journal.COMMITTED
    assert blocking[event.event_id]["verb"] == DRAIN


def test_skipped_children_with_no_blob_and_another_accounts_pending_rows_do_not_block(profile):
    assert run(make_worker([extraction(NAME_ONLY)], [NOTHING]), "process_email", seed_email()) is True
    parent = parent_of("mail-1")["event_id"]
    assert operations()[parent]["state"] == journal.SKIPPED
    assert operations()[f"{parent}:0"]["state"] == journal.SKIPPED
    journal.open_operation(chat_event("turn-other", owner=OWNER_B))
    assert operations()["turn-other"]["state"] == journal.PENDING

    out = join(COMPANY_B)

    assert out["ok"] is True and "blocking" not in out, out
    assert current_company_key() == COMPANY_B
    assert phases(COMPANY_A) == [COMPLETED]
    assert len(receipts()) == 1


# ─── AC3: the drain ───────────────────────────────────────────────────


def undecided_mail(monkeypatch):
    """``mail-1`` with its second child undecided, and ``mail-2`` committed with no checkpoint."""
    first = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), Crash()], owner=EMAIL_A)
    with pytest.raises(Crash):
        run(first, "process_email", seed_email("mail-1", owner=EMAIL_A))

    def crash(*args, **kwargs):
        raise Crash()

    with monkeypatch.context() as patched:
        patched.setattr(Storage, "mark_email_processed", crash)
        second = make_worker([extraction(MARTA)], [create_decision(MARTA, "PERSON")], owner=EMAIL_A)
        with pytest.raises(Crash):
            run(second, "process_email", seed_email("mail-2", body="Marta writes.", owner=EMAIL_A))
    assert not email_processed("mail-1") and not email_processed("mail-2")


def drained_by(monkeypatch, worker):
    """The memory pass the drain runs, with its worker's clients scripted at the transport."""
    from zylch.memory import consolidation
    from zylch.workers import memory as mem_mod
    from zylch.workers import merge_canary_gate

    monkeypatch.setattr(mem_mod, "MemoryWorker", lambda *a, **k: worker)
    monkeypatch.setattr(merge_canary_gate, "merge_canary_policy", lambda owner: {"run": False})
    monkeypatch.setattr(consolidation, "try_make_llm_client", lambda *a, **k: None)
    return worker


def paid_calls(worker) -> int:
    return (
        worker.client._client.messages.create.call_count
        + worker.decision_client._client.messages.create.call_count
    )


@pytest.mark.parametrize("stopped", ["paused", "busy"])
def test_a_drain_while_preparation_is_paused_or_busy_pays_nothing_and_places_no_fence(
    profile, monkeypatch, stopped
):
    undecided_mail(monkeypatch)
    resume(profile)
    worker = drained_by(monkeypatch, make_worker([], [create_decision(ACME, "COMPANY")], owner=EMAIL_A))
    if stopped == "paused":
        preparation.pause(OWNER_A)
        reason = "Preparation is paused. Resume starts one bounded run."
    else:
        with preparation._db() as conn:
            preparation._ensure(conn, OWNER_A)
            conn.exec_driver_sql(
                "UPDATE preparation_state SET running=1, pid=? WHERE owner=?", (os.getpid(), OWNER_A)
            )
        reason = "Preparation is already running."
    before = env_bytes()

    out = join(COMPANY_B, drain=True)

    assert out == {"ok": False, "reason": reason}
    assert paid_calls(worker) == 0
    assert phases(COMPANY_A) == [] and env_bytes() == before
    assert current_company_key() == COMPANY_A


def test_a_drain_with_preparation_free_settles_the_source_and_the_join_proceeds(profile, monkeypatch):
    undecided_mail(monkeypatch)
    resume(profile)
    worker = drained_by(monkeypatch, make_worker([], [create_decision(ACME, "COMPANY")], owner=EMAIL_A))

    out = join(COMPANY_B, drain=True)

    assert out["ok"] is True, out
    assert worker.client._client.messages.create.call_count == 0
    assert worker.decision_client._client.messages.create.call_count == 1
    assert email_processed("mail-1") and email_processed("mail-2")
    assert preparation.status(OWNER_A)["attempted"] == 2
    assert current_company_key() == COMPANY_B and phases(COMPANY_A) == [COMPLETED]


# ─── The engine CLI ───────────────────────────────────────────────────


def test_the_cli_prints_the_blocking_rows_refuses_a_paused_drain_and_releases_only_a_fenced_fence(
    profile, tmp_path, monkeypatch
):
    from click.testing import CliRunner

    from zylch.memory.mnemonic import fence
    from zylch.storage import database as dbm

    from tests.memory.test_cli_memory import _cli_for

    run(make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), UNCLEAR]), "process_email", seed_email())
    child = f"{parent_of('mail-1')['event_id']}:1"
    cli = _cli_for(monkeypatch, tmp_path, f"profile-{OWNER_A}")

    def invoke(*args):
        dbm.dispose_engine()
        Storage._instance = None
        return CliRunner().invoke(cli, ["-p", f"profile-{OWNER_A}", "memory-join", *args])

    blocked = invoke("--yes", COMPANY_B)
    assert blocked.exit_code == 2, blocked.output
    assert f"refused: {BLOCKED}" in blocked.output
    assert f"  {child}  review  email:mail-1@" in blocked.output
    assert f"    settle with: zylch memory-reviews --retry {child} (or --dismiss)" in blocked.output

    preparation.pause(OWNER_A)
    paused = invoke("--yes", "--drain", COMPANY_B)
    assert paused.exit_code == 2 and "refused: Preparation is paused." in paused.output

    other = fence.place(COMPANY_A, [OWNER_B], COMPANY_B)
    released = invoke("--release-fence")
    assert released.exit_code == 0 and "released the join fence" in released.output
    assert phases(COMPANY_A) == [RELEASED, RELEASED]
    accepted = fence.place(COMPANY_A, [OWNER_B], COMPANY_B)
    assert fence.move(accepted, fence.FENCED, fence.ACCEPTED) and other != accepted
    refused_release = invoke("--release-fence")
    assert refused_release.exit_code == 2
    assert "refused: an accepted join fence is finished by its own profile's recovery" in refused_release.output
    assert phases(COMPANY_A)[-1] == fence.ACCEPTED
