"""A fenced company is no failure of the item: preparation ends the run and suspends nothing.

On the ingestion bench (``tests/workers/ingestion_env.py``): the real worker on
real split databases, both clients scripted at the transport, every source run
inside an admitted preparation run. The fence refuses the source at its journal
writes; what is proven here is what that refusal does to preparation's
accounting, to the batch, the background job and the pipeline, and that the
source resumes once the fence is gone. The writers themselves are
``test_mnemonic_fence.py``.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, Mock, patch

import pytest

from zylch.memory.mnemonic import fence
from zylch.memory.mnemonic.fence import JOINING, CompanyFenced
from zylch.services import preparation
from zylch.storage.storage import Storage
from zylch.workers import memory as mem_mod

from tests.memory.mnemonic_env import COMPANY_A, COMPANY_B, OWNER_A, OWNER_B, BagOfWordsEmbedder, client, text_response
from tests.workers.ingestion_env import (
    ACME,
    LUCA,
    Crash,
    attempt_rows,
    blobs,
    booted,
    children_of,
    create_decision,
    email_processed,
    extraction,
    make_worker,
    parent_of,
    resume,
    run,
    seed_email,
)


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    yield from booted(tmp_path, monkeypatch, embedder)


def fenced_by_another_account() -> str:
    return fence.place(COMPANY_A, [OWNER_B], COMPANY_B)


def accounting():
    state = preparation.status(OWNER_A)
    return state["failed"], state["suspended"], state["stop_reason"]


def test_an_item_the_fence_refuses_after_a_paid_extraction_counts_no_failure(profile):
    mail = seed_email()
    worker = make_worker([extraction(LUCA)], [])

    def extract_then_fence(**kwargs):
        fenced_by_another_account()
        return text_response(extraction(LUCA))

    worker.client._client.messages.create = Mock(side_effect=extract_then_fence)

    with pytest.raises(CompanyFenced, match=JOINING):
        run(worker, "process_email", mail)

    assert worker.client._client.messages.create.call_count == 1
    assert attempt_rows() == [
        {"stage": "memory:email", "source": "mail-1", "inflight": 0, "dispatched": 1, "failures": 0}
    ]
    assert accounting() == (0, 0, JOINING)
    parent = parent_of("mail-1")
    assert parent["state"] == "pending" and children_of(parent["event_id"]) == {}
    assert not email_processed("mail-1") and blobs() == {}


def test_a_fenced_batch_stops_on_the_fence_and_suspends_nothing_however_often_it_runs(profile):
    mails = [seed_email(f"mail-{i}", body=f"Luca Bianchi writes about order {i}.") for i in range(4)]
    worker = make_worker([], [])
    fenced_by_another_account()

    for _ in range(4):
        profile.clock[0] += 1000
        with pytest.raises(CompanyFenced, match=JOINING):
            asyncio.run(worker.process_batch(mails, concurrency=1))
        assert accounting() == (0, 0, JOINING)

    assert worker.client._client.messages.create.call_count == 0
    assert [row["failures"] for row in attempt_rows()] == [0]
    assert not any(email_processed(m["id"]) for m in mails)


def test_a_source_opened_before_the_fence_resumes_after_it_is_released(profile):
    mail = seed_email()
    worker = make_worker([extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), Crash()])
    with pytest.raises(Crash):
        run(worker, "process_email", mail)
    parent = parent_of("mail-1")
    assert children_of(parent["event_id"])[f"{parent['event_id']}:1"]["state"] == "pending"
    failures = [row["failures"] for row in attempt_rows()]

    fence_id = fenced_by_another_account()
    resume(profile)
    worker.decision_client = client(create_decision(ACME, "COMPANY"))
    with pytest.raises(CompanyFenced):
        run(worker, "process_email", mail)
    assert worker.decision_client._client.messages.create.call_count == 0
    assert [row["failures"] for row in attempt_rows()] == failures
    assert not email_processed("mail-1") and len(blobs()) == 1

    assert fence.release(fence_id) is True
    resume(profile)
    assert run(worker, "process_email", mail) is True
    assert worker.client._client.messages.create.call_count == 1
    assert worker.decision_client._client.messages.create.call_count == 1
    assert email_processed("mail-1") and len(blobs()) == 2
    assert parent_of("mail-1")["state"] == "committed"


def test_a_memory_job_ends_on_the_fence_with_its_reason_and_no_traceback(profile, monkeypatch, caplog):
    from zylch.services.job_executor import JobExecutor

    storage = Storage()
    storage.store_agent_prompt(OWNER_A, "memory_message", "Extract entities. SKIP if none.", {})
    extraction_client, decision_client = client(), client()
    monkeypatch.setattr(mem_mod, "make_llm_client", Mock(side_effect=[extraction_client, decision_client]))
    seed_email("mail-1")
    seed_email("mail-2", body="Acme confirms the order.")
    fenced_by_another_account()
    job = storage.create_background_job(owner_id=OWNER_A, job_type="memory_process", channel="email")

    with caplog.at_level(logging.ERROR):
        asyncio.run(JobExecutor(storage).execute_job(job["id"], OWNER_A, ""))

    finished = storage.get_background_job(job["id"], OWNER_A)
    assert finished["status"] == "failed" and finished["last_error"] == JOINING
    assert not any(record.exc_info for record in caplog.records)
    assert [row["failures"] for row in attempt_rows()] == [0]
    assert accounting() == (0, 0, JOINING)
    assert extraction_client._client.messages.create.call_count == 0


def test_the_pipeline_ends_its_run_on_the_fence_instead_of_logging_a_memory_failure(profile, caplog):
    from zylch.services import process_pipeline as pp

    seed_email()
    errors: list = []

    class _Preflight:
        async def create_message(self, **kwargs):
            return object()

    tasks = AsyncMock(return_value="tasks ran")
    with (
        patch.object(pp, "_run_sync", AsyncMock(return_value={"success": True, "new_messages": 0})),
        patch.object(pp, "_run_whatsapp_sync", return_value={"skipped": True, "reason": "test"}),
        patch("zylch.llm.client.make_llm_client", lambda *a, **k: _Preflight()),
        patch.object(pp, "_run_memory", AsyncMock(side_effect=CompanyFenced(JOINING))),
        patch.object(pp, "_run_tasks", tasks),
        caplog.at_level(logging.ERROR),
    ):
        answer = asyncio.run(pp.handle_process([], None, OWNER_A, errors_out=errors))

    assert answer == JOINING
    assert [e["stage"] for e in errors] == ["preparation"] and str(errors[0]["error"]) == JOINING
    tasks.assert_not_awaited()
    assert not any(record.exc_info for record in caplog.records)
    assert accounting()[2] == JOINING

