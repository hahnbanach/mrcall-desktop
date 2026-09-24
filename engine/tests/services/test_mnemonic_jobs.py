"""The background memory job is a facade over the worker's own admitted path.

Against the ingestion bench (``tests/workers/ingestion_env.py``): the real
``JobExecutor`` on real split databases, the real worker with both clients
scripted at the transport. What these hold is that the job path and the
pipeline path are one contract: the same source through either entry is one
parent operation with the same children, a job runs under a bounded
preparation run and one revocable turn, a refusal leaves the channel loop and
fails the job visibly, and a read-only origin acquires no worker authority.
"""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.usage import call_site, current_call_site
from zylch.memory.mnemonic.turn import turn_cancellation
from zylch.services import job_executor, preparation
from zylch.services.job_executor import JobExecutor
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation
from zylch.storage.storage import Storage
from zylch.workers import memory as mem_mod

from tests.memory.mnemonic_env import OWNER_A, BagOfWordsEmbedder, client
from tests.workers.ingestion_env import (
    ACME,
    LUCA,
    Crash,
    blobs,
    booted,
    children_of,
    create_decision,
    email_processed,
    extraction,
    operations,
    parent_of,
    resume,
    scripted,
    seed_calendar,
    seed_email,
    seed_mrcall,
)


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


@pytest.fixture
def executor(profile):
    storage = Storage()
    storage.store_agent_prompt(OWNER_A, "memory_message", "Extract entities. SKIP if none.", {})
    return JobExecutor(storage)


def script(monkeypatch, extractions, decisions):
    """The worker the job builds gets these two clients, in construction order."""
    extraction_client = client(*extractions) if all(isinstance(e, str) for e in extractions) else scripted(extractions)
    decision_client = client(*decisions) if all(isinstance(d, str) for d in decisions) else scripted(decisions)
    monkeypatch.setattr(mem_mod, "make_llm_client", Mock(side_effect=[extraction_client, decision_client]))
    return extraction_client, decision_client


def run_job(executor, channel="email"):
    job = executor.storage.create_background_job(owner_id=OWNER_A, job_type="memory_process", channel=channel)
    asyncio.run(executor.execute_job(job["id"], OWNER_A, ""))
    return executor.storage.get_background_job(job["id"], OWNER_A)


def transport_calls(llm):
    return llm._client.messages.create.call_count


# ─── One source, one contract, whichever entry ────────────────────────


def test_the_same_source_through_the_worker_and_the_facade_is_one_operation(executor, profile, monkeypatch):
    """The pipeline commits the source and crashes before its checkpoint; the
    job then picks the same mail up and finds the parent already terminal:
    it marks the source, pays nothing, and the children are the same rows."""
    from tests.workers.ingestion_env import make_worker, run

    mail = seed_email()
    worker = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), create_decision(ACME, "COMPANY")])
    real = Storage.mark_email_processed
    once = {"left": 1}

    def crashing(self, owner_id, email_id):
        if once["left"]:
            once["left"] -= 1
            raise Crash()
        return real(self, owner_id, email_id)

    monkeypatch.setattr(Storage, "mark_email_processed", crashing)
    with pytest.raises(Crash):
        run(worker, "process_email", mail)
    parent = parent_of("mail-1")
    assert parent["state"] == "committed" and not email_processed("mail-1")
    before = sorted(children_of(parent["event_id"]))
    resume(profile)

    extraction_client, decision_client = script(monkeypatch, [], [])
    job = run_job(executor)

    assert job["status"] == "completed" and job["result"]["email_count"] == 1
    assert email_processed("mail-1")
    assert transport_calls(extraction_client) == 0 and transport_calls(decision_client) == 0
    assert [r for r in operations().values() if r["parent_event_id"] is None] == [parent_of("mail-1")]
    assert sorted(children_of(parent["event_id"])) == before
    assert len(blobs()) == 2


def test_a_read_only_origin_job_acquires_no_worker_authority(executor, monkeypatch):
    from zylch.services.request_policy import READ_ONLY_POLICY, policy_scope

    seed_email()
    extraction_client, decision_client = script(monkeypatch, [extraction(LUCA)], [create_decision(LUCA, "PERSON")])

    with policy_scope(READ_ONLY_POLICY):
        job = run_job(executor)

    assert transport_calls(extraction_client) == 0 and transport_calls(decision_client) == 0
    assert budget_snapshot(OWNER_A)["reserved_usd"] == 0
    assert blobs() == {} and not email_processed("mail-1")
    parent = parent_of("mail-1")
    assert parent["state"] == "review" and "read-only" in parent["result"]["reason"]
    assert job["status"] == "completed" and job["result"]["email_count"] == 0


# ─── The job runs under preparation and one revocable turn ────────────


def test_a_job_restart_resumes_the_same_children(executor, profile, monkeypatch):
    seed_email()
    extraction_client, decision_client = script(monkeypatch, [extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), Crash()])
    job = executor.storage.create_background_job(owner_id=OWNER_A, job_type="memory_process", channel="email")
    with pytest.raises(Crash):
        asyncio.run(executor.execute_job(job["id"], OWNER_A, ""))
    parent = parent_of("mail-1")
    kids = children_of(parent["event_id"])
    assert kids[f"{parent['event_id']}:0"]["state"] == "committed"
    assert kids[f"{parent['event_id']}:1"]["state"] == "pending"
    executor.storage.fail_background_job(job["id"], "crashed")  # the stuck row, as an operator would clear it
    resume(profile)

    extraction_client, decision_client = script(monkeypatch, [], [create_decision(ACME, "COMPANY")])
    job = run_job(executor)

    assert job["status"] == "completed" and job["result"]["email_count"] == 1
    assert transport_calls(extraction_client) == 0 and transport_calls(decision_client) == 1
    assert sorted(children_of(parent["event_id"])) == sorted(kids)
    assert len(blobs()) == 2 and email_processed("mail-1")


def test_a_stopped_job_revokes_the_turn_and_the_next_child_is_refused_before_dispatch(executor, monkeypatch):
    seed_email()
    extraction_client, decision_client = script(monkeypatch, [extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), create_decision(ACME, "COMPANY")])
    job = executor.storage.create_background_job(owner_id=OWNER_A, job_type="memory_process", channel="email")
    real_create = decision_client._client.messages.create

    def deciding(**kwargs):
        response = real_create(**kwargs)
        executor.storage.fail_background_job(job["id"], "stopped by user")  # the stop lands after child 1
        return response

    decision_client._client.messages.create = Mock(side_effect=deciding)
    asyncio.run(executor.execute_job(job["id"], OWNER_A, ""))

    assert decision_client._client.messages.create.call_count == 1
    parent = parent_of("mail-1")
    kids = children_of(parent["event_id"])
    assert kids[f"{parent['event_id']}:0"]["state"] == "committed"
    assert kids[f"{parent['event_id']}:1"]["state"] == "pending"
    assert parent["state"] == "pending" and not email_processed("mail-1")
    assert executor.storage.get_background_job(job["id"], OWNER_A)["status"] != "completed"


def test_a_refusal_at_item_two_of_three_fails_the_job_and_leaves_the_rest_untouched(executor, monkeypatch):
    for i in (1, 2, 3):
        seed_email(f"mail-{i}", body=f"Mail {i} about Acme.")
    # The job walks the storage's own order (newest first); name the items by it.
    first, second, third = [row["id"] for row in Storage().get_unprocessed_emails(OWNER_A)]
    extraction_client, decision_client = script(
        monkeypatch,
        [extraction(LUCA), extraction(ACME), extraction(ACME)],
        [create_decision(LUCA, "PERSON")],
    )
    from zylch.llm import budget

    real_reserve = budget.reserve
    extractions = {"n": 0}

    def refusing(request_kwargs, transport, **kwargs):
        if current_call_site() == "memory.extract":
            extractions["n"] += 1
            if extractions["n"] == 2:
                raise BudgetError("Daily AI budget unavailable")
        return real_reserve(request_kwargs, transport, **kwargs)

    monkeypatch.setattr(budget, "reserve", refusing)

    job = run_job(executor)

    assert job["status"] == "failed" and "budget" in (job["last_error"] or "").lower()
    assert email_processed(first) and not email_processed(second) and not email_processed(third)
    assert transport_calls(extraction_client) == 1  # the second refused at reserve; the third never attempted
    assert parent_of(second)["state"] == "pending"
    assert not any(f":{third}@" in r["source_ref"] for r in operations().values())


def test_the_call_site_tag_and_the_turn_are_read_inside_the_thread(executor, monkeypatch):
    seed_email("mail-1")
    seed_email("mail-2", body="Second mail.")
    script(monkeypatch, [extraction(LUCA), "SKIP"], [create_decision(LUCA, "PERSON")])
    seen = []
    real = job_executor.run_source_sync

    def probing(worker, channel, item):
        seen.append((current_call_site(), turn_cancellation(), preparation.current_item()))
        return real(worker, channel, item)

    monkeypatch.setattr(job_executor, "run_source_sync", probing)

    with call_site("job.memory"):
        job = run_job(executor)

    assert job["status"] == "completed"
    assert [tag for tag, _, _ in seen] == ["job.memory", "job.memory"]
    handles = {id(handle) for _, handle, _ in seen}
    assert len(handles) == 1  # one revocable turn for the whole job, shared by every source
    assert all(item is None for _, _, item in seen)  # the item is admitted inside the coroutine


def test_calendar_and_mrcall_are_reachable_through_the_facade(executor, monkeypatch):
    seed_email()
    seed_calendar()
    seed_mrcall()
    marta = "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Marta Riva\nCompany: Acme\n#ABOUT\nFinance lead."
    script(
        monkeypatch,
        [extraction(LUCA), "Marta Riva of Acme attended as finance lead.", extraction(ACME)],
        [create_decision(LUCA, "PERSON"), create_decision(marta, "PERSON"), create_decision(ACME, "COMPANY")],
    )

    job = run_job(executor, channel="all")

    assert job["status"] == "completed"
    assert (job["result"]["email_count"], job["result"]["calendar_count"], job["result"]["mrcall_count"]) == (1, 1, 1)
    parents = [r for r in operations().values() if r["parent_event_id"] is None]
    assert sorted(r["source_ref"].split(":")[0] for r in parents) == ["calendar", "email", "mrcall"]
    assert all(r["state"] == "committed" for r in parents)


def test_a_paused_preparation_fails_the_job_visibly(executor, monkeypatch):
    seed_email()
    extraction_client, decision_client = script(monkeypatch, [extraction(LUCA)], [create_decision(LUCA, "PERSON")])
    preparation.pause(OWNER_A)

    job = run_job(executor)

    assert job["status"] == "failed" and "paused" in (job["last_error"] or "").lower()
    assert transport_calls(extraction_client) == 0
    assert blobs() == {} and not email_processed("mail-1")
    with get_session() as session:
        assert session.query(MemoryOperation).count() == 0
