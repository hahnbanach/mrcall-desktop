"""Durable preparation behavior with real SQLite and fake semantic work."""

import asyncio
from datetime import UTC

import pytest
from sqlalchemy import create_engine

from zylch.llm.budget import BudgetError
from zylch.services import preparation as p


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from zylch.storage import database

    engine = create_engine(f"sqlite:///{tmp_path / 'profile.db'}")
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    monkeypatch.delenv("OWNER_ID", raising=False)
    monkeypatch.setenv("PREPARATION_BATCH_SIZE", "25")
    yield engine
    engine.dispose()


def test_shared_limit_across_channels_and_stages(ledger):
    calls = []

    class Worker:
        owner_id = "owner"

        @p.bounded_item("memory:email")
        async def memory(self, data):
            calls.append(data["id"])
            p.check_dispatch()
            p.check_dispatch()  # multiple merge calls belong to the same item
            return True

        @p.bounded_item()
        async def task(self, kind, event_data):
            calls.append(event_data["id"])
            self.mark("owner", event_data["id"])
            return {"task_action": "none"}

        @p.task_checkpoint("task:whatsapp")
        def mark(self, owner, source):
            pass

    async def run():
        w = Worker()
        with p.preparation_run("owner"):
            await asyncio.gather(*(w.memory({"id": str(i)}) for i in range(20)))
            await asyncio.gather(*(w.task("whatsapp", {"id": str(i)}) for i in range(20)))

    asyncio.run(run())
    assert len(calls) == 25
    state = p.status("owner")
    assert state["attempted"] == state["completed"] == 25
    assert not state["running"]


def test_failures_backoff_and_explicit_reset_survive_runs(ledger, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(p.time, "time", lambda: clock[0])
    calls = []

    class Worker:
        owner_id = "owner"

        @p.bounded_item("memory:email")
        async def memory(self, data):
            calls.append(data["id"])
            return False

    def run():
        with p.preparation_run("owner", explicit=True):
            asyncio.run(Worker().memory({"id": "failed"}))

    for i in range(3):
        run()
        run()  # pressing resume cannot skip durable backoff
        clock[0] += 1000
    run()
    assert len(calls) == 3
    assert p.status("owner")["suspended"] == 1
    p.reset_failure("owner", "memory:email", "failed")
    run()
    assert len(calls) == 4


def test_budget_refusal_is_not_semantic_failure(ledger):
    class Worker:
        owner_id = "owner"

        @p.bounded_item("memory:email")
        async def memory(self, data):
            raise BudgetError("Daily budget exhausted")

    for _ in range(4):
        with pytest.raises(BudgetError), p.preparation_run("owner"):
            asyncio.run(Worker().memory({"id": "pending"}))
    with p._db() as conn:
        assert conn.exec_driver_sql("SELECT failures,inflight FROM preparation_attempts").one() == (
            0,
            0,
        )


def test_pause_stops_dispatch_resume_is_one_run_only(ledger):
    with p.preparation_run("owner"):
        p.check_dispatch()
        p.pause("owner")
        with pytest.raises(p.PreparationStopped):
            p.check_dispatch()
    assert not p.status("owner")["running"]
    with pytest.raises(p.PreparationStopped), p.preparation_run("owner"):
        pass
    with p.preparation_run("owner", explicit=True):
        p.check_dispatch()
    assert p.status("owner")["paused"]
    with pytest.raises(p.PreparationStopped), p.preparation_run("owner"):
        pass


def test_crash_attempt_and_concurrent_run_refusal(ledger):
    with p.preparation_run("owner"):
        p._admit("owner", "memory:email", "interrupted")
        # A fresh execution context (another RPC/thread) cannot admit a run.
        import contextvars

        def competing():
            with pytest.raises(p.PreparationStopped), p.preparation_run("owner"):
                pass

        contextvars.Context().run(competing)
    with p.preparation_run("owner"):
        assert p._admit("owner", "memory:email", "interrupted") is False
    with p._db() as conn:
        assert conn.exec_driver_sql("SELECT failures,inflight FROM preparation_attempts").one() == (
            1,
            0,
        )


def test_auxiliary_work_consumes_shared_allowance(ledger, monkeypatch):
    monkeypatch.setenv("PREPARATION_BATCH_SIZE", "2")
    with p.preparation_run("owner"):
        p.check_dispatch()  # training
        p.check_dispatch()  # canary
        with pytest.raises(p.PreparationStopped):
            p.check_dispatch()  # sweep refuses before upstream
    assert p.status("owner")["attempted"] == 2


def test_rpc_status_uses_real_checkpoints(ledger, monkeypatch):
    from zylch.rpc import preparation as rpc

    monkeypatch.setattr(rpc, "get_owner_id", lambda: "owner")
    with ledger.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE emails(id TEXT, owner_id TEXT, memory_processed_at TEXT, task_processed_at TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO emails VALUES ('one','owner','done',NULL),('two','owner',NULL,NULL),('other','other',NULL,NULL)"
        )
    result = asyncio.run(rpc.preparation_status({}, lambda *args: None))
    assert result["pending"] == 3
    assert result["checkpoints_completed"] == 1


def test_dispatched_budget_error_counts_uncertain_failure(ledger):
    class Worker:
        owner_id = "owner"

        @p.bounded_item("memory:email")
        async def memory(self, data):
            p.record_dispatch()
            raise BudgetError("Upstream returned unverifiable usage")

    with pytest.raises(BudgetError), p.preparation_run("owner"):
        asyncio.run(Worker().memory({"id": "uncertain"}))
    with p._db() as conn:
        assert conn.exec_driver_sql(
            "SELECT failures,inflight,dispatched FROM preparation_attempts"
        ).one() == (1, 0, 1)


def test_actual_memory_worker_preserves_failed_checkpoint_and_accepts_skip(ledger, monkeypatch):
    from datetime import datetime

    from sqlalchemy.orm import sessionmaker

    from zylch.storage import database
    from zylch.storage.models import Email
    from zylch.storage.storage import Storage
    from zylch.workers.memory import MemoryWorker

    Email.__table__.create(ledger)
    factory = sessionmaker(bind=ledger)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    monkeypatch.setattr(database, "memory_unavailable_reason", lambda: None)
    with factory.begin() as session:
        for source in ("bad", "skip"):
            session.add(
                Email(
                    id=source,
                    owner_id="owner",
                    gmail_id=source,
                    thread_id=source,
                    date=datetime.now(UTC),
                )
            )
    worker = MemoryWorker.__new__(MemoryWorker)
    worker.owner_id = "owner"
    worker.storage = Storage.__new__(Storage)

    def extract(email, contact):
        if email["id"] == "bad":
            raise RuntimeError("Provider unavailable")
        return []  # parsed explicit semantic SKIP

    worker._extract_entities = extract
    with p.preparation_run("owner"):
        assert not asyncio.run(
            worker.process_email({"id": "bad", "from_email": "example@example.test"})
        )
        assert asyncio.run(
            worker.process_email({"id": "skip", "from_email": "example@example.test"})
        )
    with factory() as session:
        assert session.get(Email, "bad").memory_processed_at is None
        assert session.get(Email, "skip").memory_processed_at is not None
    assert p.status("owner")["failed"] == 1
    assert p.status("owner")["completed"] == 1


def test_outside_legacy_private_calls_are_refused_before_dispatch(ledger):
    from zylch.llm.usage import call_site

    with call_site("memory.extract"), pytest.raises(p.PreparationStopped):
        p.check_dispatch()
    with call_site("chat"):
        p.check_dispatch()


def test_task_decision_without_committed_checkpoint_counts_failure(ledger):
    class Worker:
        owner_id = "owner"

        @p.bounded_item()
        async def analyze(self, kind, event_data):
            p.record_dispatch()
            return {"task_action": "create"}

    with p.preparation_run("owner"):
        asyncio.run(Worker().analyze("calendar", {"id": "write-failed"}))
        # Simulate caller's task write failing after successful inference.
    assert p.status("owner")["failed"] == 1
    assert p.status("owner")["completed"] == 0
    with p._db() as conn:
        assert conn.exec_driver_sql("SELECT failures,inflight FROM preparation_attempts").one() == (
            1,
            0,
        )


def test_account_email_change_does_not_reset_failure_history(ledger, monkeypatch):
    monkeypatch.setenv("OWNER_ID", "immutable")
    with p.preparation_run("old@example.test"):
        p._admit("old@example.test", "task:email", "source")
    assert p.status("new@example.test")["failed"] == 1
    with p.preparation_run("new@example.test"):
        assert p._admit("new@example.test", "task:email", "source") is False


def test_suspended_whatsapp_prefix_does_not_starve_later_items(ledger):
    from zylch.workers.memory import MemoryWorker

    class Worker:
        owner_id = "owner"
        process_whatsapp_batch = MemoryWorker.process_whatsapp_batch

        @p.bounded_item("memory:whatsapp")
        async def process_whatsapp_message(self, data):
            return True

    with p._db() as conn:
        for i in range(3):
            conn.exec_driver_sql(
                "INSERT INTO preparation_attempts(owner,stage,source,failures) VALUES ('owner','memory:whatsapp',?,3)",
                (str(i),),
            )
    assert (
        asyncio.run(
            Worker().process_whatsapp_batch([{"id": str(i)} for i in range(4)], concurrency=1)
        )
        == 1
    )
    assert p.status("owner")["completed"] == 1


def test_actual_client_uncertain_usage_retains_money_and_counts_item_failure(ledger, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from zylch.llm.budget import budget_snapshot
    from zylch.llm.client import LLMClient
    from zylch.storage import database
    from zylch.storage.models import LlmReservation, LlmUsage

    database.Base.metadata.create_all(ledger, tables=[LlmUsage.__table__, LlmReservation.__table__])
    monkeypatch.setenv("OWNER_ID", "owner")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    client = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    client._client.messages.create = Mock(
        return_value=SimpleNamespace(
            model="claude-haiku-4-5", content=[], stop_reason="end_turn", usage=None
        )
    )

    class Worker:
        owner_id = "owner"

        @p.bounded_item("memory:email")
        async def process(self, data):
            await client.create_message(
                messages=[{"role": "user", "content": "semantic fixture"}], max_tokens=32
            )
            return True

    with pytest.raises(BudgetError), p.preparation_run("owner"):
        asyncio.run(Worker().process({"id": "uncertain"}))
    client._client.messages.create.assert_called_once()
    assert budget_snapshot("owner")["reserved_usd"] > 0
    assert p.status("owner")["failed"] == 1
    with p._db() as conn:
        assert conn.exec_driver_sql(
            "SELECT failures,dispatched,inflight FROM preparation_attempts"
        ).one() == (1, 1, 0)
