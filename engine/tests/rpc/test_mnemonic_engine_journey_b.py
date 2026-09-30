"""The worker and the join of the installed-client journey: D3 cases 14, 15 and 16.

Every ingestion run here is ``cs rpc preparation.resume`` through the installed
kernel over the engine's own WebSocket handler (``kernel_journey_env``): the
real pipeline, the real ``MemoryWorker`` on the real split databases, the real
``LLMClient`` and reservation ledger, only the worker's two transports scripted
(``engine_journey_cases.script_worker``). The ``memory_process`` job and the
crash between two children are driven where the engine offers them — the job
executor in process, a second OS process for the crash — and the join through
``cs rpc memory.join`` with ``zylch memory-reviews --dismiss`` in process,
because the kernel has no route for the review.

Each case asserts the committed content, the retained versions, the
namespaces, the operation rows' states and departures, one settled reservation
per decided child, the read visibility from each account it names, and that
no unrelated blob, version or operation row moved. Firebase verification is
not in the loop: the handler asserts the fixture bearer token and sets the
claims itself, so nothing here is a claim about ``server_ws``'s own auth. Cases
11–13 and 17 are ``test_mnemonic_engine_journey.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.memory import join_env, mnemonic_env
from tests.rpc import engine_journey_cases as cases
from tests.rpc import kernel_journey_env as env
from tests.rpc.engine_journey_cases import EMAIL_A, EMAIL_B
from tests.workers.ingestion_env import ACME, FACT_ENTITY, LUCA, create_decision, extraction

ENGINE_ROOT = Path(__file__).resolve().parents[2]
ENTITY_NS = f"user:{env.COMPANY}"
FACTS_NS = f"facts:{env.COMPANY}"
PRICE = "Category: pricing\nKey: list\nValue: EUR 100 per unit"
RULE_A = "Sign every reply with the warehouse number."
RULE_B = "Answer in Italian unless asked otherwise."


@pytest.fixture
def bench(monkeypatch, tmp_path):
    """Account A booted on the company key with its extraction prompt trained,
    the server serving it, its kernel, and the preparation clock in hand."""
    env.require_kernel()
    join_env.isolate(monkeypatch)
    env.boot(monkeypatch, tmp_path, env.OWNER_A)
    cases.store_prompt()
    server = env.EngineServer(env.OWNER_A).start(monkeypatch)
    kernel = env.Kernel(tmp_path, server, env.OWNER_A)
    yield SimpleNamespace(
        root=tmp_path,
        server=server,
        kernel=kernel,
        db=env.company_db(tmp_path),
        advance=cases.clock(monkeypatch),
    )
    server.stop()
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    mnemonic_env.clear_process_state()


def as_b(monkeypatch, bench, key: str = env.COMPANY) -> env.Kernel:
    env.switch(monkeypatch, bench.root, bench.server, env.OWNER_B, key)
    return env.Kernel(bench.root, bench.server, env.OWNER_B)


def settled_source(db, source_id: str, n: int):
    """The parent of ``source_id`` committed with its ``n`` children, all committed."""
    parent = cases.parent_of(db, source_id)
    kids = cases.children_of(db, parent["event_id"])
    assert sorted(kids) == [f"{parent['event_id']}:{i}" for i in range(n)]
    assert parent["state"] == "committed" and parent["departure"] is None
    assert {k["state"] for k in kids.values()} == {"committed"}
    assert all(k["departure"] is None and k["origin"] == "automatic" for k in kids.values())
    assert len(parent["result"]["committed_ids"]) == n
    return parent, kids


# ─── Case 14: one mail through the pipeline, then through the job ─────


def test_case_14_a_mail_ingested_by_the_pipeline_is_the_same_source_the_job_replays(
    monkeypatch, bench
):
    """``preparation.resume`` commits one source: one parent, two children, two
    blobs, the checkpoint. The ``memory_process`` job then meets the same
    source with its checkpoint cleared (what ``--force`` does) and replays the
    parent: no extraction, no decision, no new row, the checkpoint landed once
    more, nothing else in the store touched."""
    from zylch.services.job_executor import JobExecutor
    from zylch.storage.storage import Storage

    cases.seed_mail()
    extract, decide = cases.script_worker(
        monkeypatch,
        [extraction(LUCA, ACME)],
        [create_decision(LUCA, "PERSON"), create_decision(ACME, "COMPANY")],
    )
    before = env.snapshot(bench.db)

    out = cases.resume(bench.kernel)

    assert out["channels"]["emails:memory_processed_at"] == {"pending": 0, "completed": 1}
    assert (cases.calls(extract), cases.calls(decide)) == (1, 2)
    parent, kids = settled_source(bench.db, "mail-1", 2)
    stored = cases.blobs(bench.db)
    assert {v[2] for v in stored.values()} == {LUCA, ACME}
    assert {(v[0], v[1]) for v in stored.values()} == {(ENTITY_NS, EMAIL_A)}
    assert all(cases.versions(bench.db, b) == [] for b in stored)
    assert cases.email_processed("mail-1")
    assert cases.reservations(bench.root, call_site="memory.extract") == [("memory.extract", 1)]
    assert cases.paid_decisions(bench.root) == [("memory.mnemonic", 1)] * 2
    ledger = cases.reservations(bench.root)
    rows_before = cases.operations(bench.db)

    storage = Storage()
    assert storage.reset_memory_processing_timestamps(EMAIL_A)["emails"] == 1
    extract_again, decide_again = cases.script_worker(monkeypatch, [], [])
    job = storage.create_background_job(
        owner_id=EMAIL_A, job_type="memory_process", channel="email"
    )
    import asyncio

    asyncio.run(JobExecutor(storage).execute_job(job["id"], EMAIL_A, ""))

    finished = storage.get_background_job(job["id"], EMAIL_A)
    assert finished["status"] == "completed", finished
    assert (cases.calls(extract_again), cases.calls(decide_again)) == (0, 0)
    assert cases.operations(bench.db) == rows_before
    assert cases.email_processed("mail-1") and cases.blobs(bench.db) == stored
    assert cases.reservations(bench.root) == ledger
    status = bench.kernel.rpc("preparation.status")
    assert status["channels"]["emails:memory_processed_at"] == {"pending": 0, "completed": 1}
    luca, acme = (next(b for b, v in stored.items() if v[2] == text) for text in (LUCA, ACME))
    found = cases.readback_ids(monkeypatch, bench.kernel, "Luca Bianchi")
    assert luca in found and found <= set(stored)

    kernel_b = as_b(monkeypatch, bench)
    found = cases.readback_ids(monkeypatch, kernel_b, "Acme Srl")
    assert acme in found and found <= set(stored)
    env.assert_unrelated_unchanged(
        before, env.snapshot(bench.db), blob_ids=list(stored), event_ids=[parent["event_id"]]
    )


# ─── Case 15: a restart between two children ──────────────────────────

CRASH_SCRIPT = """
    import sys
    sys.path.insert(0, {engine!r})
    import zylch.memory as memory_pkg
    import zylch.memory.embeddings as emb_mod
    from tests.memory.mnemonic_env import BagOfWordsEmbedder

    embedder = BagOfWordsEmbedder()
    memory_pkg.EmbeddingEngine = lambda *a, **k: embedder
    emb_mod.EmbeddingEngine = lambda *a, **k: embedder

    from tests.workers.ingestion_env import ACME, LUCA, Crash, create_decision, extraction, make_worker, run
    from zylch.storage import database as dbm
    from zylch.storage.storage import Storage

    dbm.init_db()
    worker = make_worker(
        [extraction(LUCA, ACME)], [create_decision(LUCA, "PERSON"), Crash()], owner={owner!r}
    )
    mail = next(row for row in Storage().get_unprocessed_emails({owner!r}) if row["id"] == "mail-1")
    run(worker, "process_email", mail)
"""


def crash_between_children(bench) -> None:
    """A second OS process ingests ``mail-1`` and dies after its first child.

    The fault is the bench's ``Crash`` — a ``BaseException`` raised where the
    role's second answer would be — and the process ends on it, as a killed
    worker would, with the profile's ledger and the company journal on disk.
    """
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    script = bench.root / "crash_between_children.py"
    script.write_text(textwrap.dedent(CRASH_SCRIPT).format(engine=str(ENGINE_ROOT), owner=EMAIL_A))
    done = subprocess.run(
        [sys.executable, str(script)],
        env=mnemonic_env.owner_env(env.OWNER_A),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert done.returncode != 0 and "Crash" in done.stderr, (done.stdout, done.stderr[-2000:])
    mnemonic_env.reboot()


def test_case_15_a_run_resumed_after_a_crash_between_children_decides_only_the_rest(
    monkeypatch, bench
):
    """The first process paid one extraction and one decision and left the
    second child undecided. The resumed run through ``preparation.resume``
    re-extracts nothing, decides that child alone, and lands the checkpoint:
    two blobs, no version, one settled reservation per decided child."""
    cases.seed_mail()
    before = env.snapshot(bench.db)

    crash_between_children(bench)

    parent = cases.parent_of(bench.db, "mail-1")
    kids = cases.children_of(bench.db, parent["event_id"])
    assert parent["state"] == "pending"
    assert kids[f"{parent['event_id']}:0"]["state"] == "committed"
    assert kids[f"{parent['event_id']}:1"]["state"] == "pending"
    assert [v[2] for v in cases.blobs(bench.db).values()] == [LUCA]
    assert not cases.email_processed("mail-1")
    assert cases.reservations(bench.root, call_site="memory.extract") == [("memory.extract", 1)]
    # The second child's call was reserved and went out as the process died:
    # its hold is retained, unsettled, beside the first child's settled payment.
    assert cases.paid_decisions(bench.root) == [("memory.mnemonic", 1), ("memory.mnemonic", 0)]

    bench.advance(3600)
    extract, decide = cases.script_worker(monkeypatch, [], [create_decision(ACME, "COMPANY")])
    out = cases.resume(bench.kernel)

    assert out["channels"]["emails:memory_processed_at"] == {"pending": 0, "completed": 1}
    assert (cases.calls(extract), cases.calls(decide)) == (0, 1)
    parent, kids = settled_source(bench.db, "mail-1", 2)
    stored = cases.blobs(bench.db)
    assert sorted(v[2] for v in stored.values()) == sorted([LUCA, ACME])
    assert {(v[0], v[1]) for v in stored.values()} == {(ENTITY_NS, EMAIL_A)}
    assert env.rows(bench.db, "SELECT COUNT(*) FROM blob_versions") == [(0,)]
    assert cases.email_processed("mail-1")
    assert cases.reservations(bench.root, call_site="memory.extract") == [("memory.extract", 1)]
    # One settled payment per decided child, and the crashed hold still unsettled.
    assert cases.paid_decisions(bench.root) == [
        ("memory.mnemonic", 1),
        ("memory.mnemonic", 0),
        ("memory.mnemonic", 1),
    ]
    acme = next(b for b, v in stored.items() if v[2] == ACME)
    found = cases.readback_ids(monkeypatch, bench.kernel, "Acme Srl")
    assert acme in found and found <= set(stored)
    env.assert_unrelated_unchanged(
        before, env.snapshot(bench.db), blob_ids=list(stored), event_ids=[parent["event_id"]]
    )


# ─── Case 16: the join refused, then cut over ─────────────────────────


def review_declining_the_fact(fact_id: str) -> str:
    return json.dumps(
        {
            "action": "REVIEW",
            "reason": "a customer's price, not company knowledge",
            "ineligible": [fact_id],
        }
    )


def test_case_16_a_join_refused_for_a_reviewed_child_cuts_over_once_the_child_is_settled(
    monkeypatch, tmp_path
):
    """The source company holds the second account's rule, the first account's
    rule, a legacy FACT and one ingested mail whose second child the role
    parked in review, restricting the FACT. ``memory.join`` refuses with the
    two blocking rows and their verbs; ``zylch memory-reviews --dismiss``
    settles the child, one ordinary run lands the checkpoint unpaid, and the
    join cuts over: fence completed, source byte for byte, the restriction
    carried, the joining account's rule moved and the other account's left."""
    from zylch.memory.company_key import current_company_key
    from zylch.memory.join import BLOCKED
    from zylch.memory.mnemonic.fence import COMPLETED, RELEASED

    env.require_kernel()
    join_env.isolate(monkeypatch)
    env.boot(monkeypatch, tmp_path, env.OWNER_B)
    rule_b = cases.seed_blob(env.OWNER_B, f"template:{env.OWNER_B}", RULE_B)
    join_env.destination(mnemonic_env.COMPANY_B)
    env.boot(monkeypatch, tmp_path, env.OWNER_A)
    cases.store_prompt()
    server = env.EngineServer(env.OWNER_A).start(monkeypatch)
    bench = SimpleNamespace(
        root=tmp_path,
        server=server,
        kernel=env.Kernel(tmp_path, server, env.OWNER_A),
        db=env.company_db(tmp_path),
        advance=cases.clock(monkeypatch),
    )
    try:
        # The engine writes this account's rules as its email identity; a rule
        # family is visible to its exact owner, so the seed uses the same one.
        rule_a = cases.seed_blob(EMAIL_A, f"template:{env.OWNER_A}", RULE_A)
        price = cases.seed_blob(env.OWNER_A, FACTS_NS, PRICE)
        price_version = cases.version_of(price)
        cases.seed_mail(body="Luca Bianchi will call; our list price is now EUR 120 per unit.")
        extract, decide = cases.script_worker(
            monkeypatch,
            [extraction(LUCA, FACT_ENTITY)],
            [create_decision(LUCA, "PERSON"), review_declining_the_fact(price)],
        )
        before = env.snapshot(bench.db)
        cases.resume(bench.kernel)
        assert (cases.calls(extract), cases.calls(decide)) == (1, 2)
        parent = cases.parent_of(bench.db, "mail-1")
        kids = cases.children_of(bench.db, parent["event_id"])
        first, second = f"{parent['event_id']}:0", f"{parent['event_id']}:1"
        assert parent["state"] == "review" and kids[first]["state"] == "committed"
        assert kids[second]["state"] == "review"
        assert kids[second]["restrictions"] == [{"blob_id": price, "version": price_version}]
        (luca,) = [b for b, v in cases.blobs(bench.db).items() if v[2] == LUCA]
        assert not cases.email_processed("mail-1")
        env_before = join_env.env_bytes()

        refused = bench.kernel.rpc("memory.join", {"key": mnemonic_env.COMPANY_B})

        assert refused["ok"] is False and refused["reason"] == BLOCKED, refused
        blocking = {row["event_id"]: row for row in refused["blocking"]}
        assert set(blocking) == {parent["event_id"], second}
        assert blocking[second]["state"] == "review"
        assert blocking[second]["verb"] == f"zylch memory-reviews --retry {second} (or --dismiss)"
        assert blocking[parent["event_id"]]["verb"] == (
            f"zylch memory-reviews --dismiss {parent['event_id']}"
        )
        assert blocking[second]["source_ref"].startswith("email:mail-1@")
        assert join_env.phases(env.COMPANY) == [RELEASED]
        assert join_env.env_bytes() == env_before and current_company_key() == env.COMPANY
        assert join_env.count(mnemonic_env.COMPANY_B, "blobs") == 0

        dismissed = cases.cli(
            monkeypatch, tmp_path, env.OWNER_A, "memory-reviews", "--dismiss", second
        )

        assert dismissed.exit_code == 0, dismissed.output
        assert dismissed.output == (
            f"dismiss: {second} is now skipped; parent {parent['event_id']} is committed\n"
        )
        assert cases.operations(bench.db)[second]["restrictions"] == [
            {"blob_id": price, "version": price_version}
        ]
        bench.advance(3600)
        extract_again, decide_again = cases.script_worker(monkeypatch, [], [])
        cases.resume(bench.kernel)
        assert (cases.calls(extract_again), cases.calls(decide_again)) == (0, 0)
        assert cases.email_processed("mail-1")
        assert cases.paid_decisions(bench.root) == [("memory.mnemonic", 1)] * 2
        source = join_env.store_digest(env.COMPANY)
        destination_before = env.snapshot(env.company_db(tmp_path, mnemonic_env.COMPANY_B))

        joined = bench.kernel.rpc("memory.join", {"key": mnemonic_env.COMPANY_B})

        assert joined["ok"] is True and "blocking" not in joined, joined
        assert joined["merged"]["blobs"] == 3
        assert join_env.phases(env.COMPANY) == [RELEASED, COMPLETED]
        assert join_env.store_digest(env.COMPANY) == source
        assert current_company_key() == mnemonic_env.COMPANY_B
        assert join_env.env_value("MEMORY_KEY") == mnemonic_env.COMPANY_B
        assert join_env.env_value("MEMORY_KEY_SOURCE") == "join"
        moved = join_env.blob_ids(mnemonic_env.COMPANY_B)
        assert moved == {luca, price, rule_a} and rule_b not in moved
        assert {luca, price, rule_a, rule_b} <= join_env.blob_ids(env.COMPANY)
        (receipt,) = join_env.receipts()
        carried = cases.operations(env.company_db(tmp_path, mnemonic_env.COMPANY_B))[receipt]
        assert carried["state"] == "committed"
        assert carried["restrictions"] == [{"blob_id": price, "version": price_version}]
        assert cases.facts(EMAIL_A, "pricing") == []
        assert cases.storage().get_blob(price, env.OWNER_A)["content"] == PRICE
        assert cases.readback_ids(monkeypatch, bench.kernel, "Luca Bianchi") == {luca}
        assert cases.hybrid(EMAIL_A, RULE_A) == {rule_a}
        env.assert_unrelated_unchanged(
            before, env.snapshot(bench.db), blob_ids=[luca], event_ids=[parent["event_id"]]
        )

        kernel_b = as_b(monkeypatch, bench, mnemonic_env.COMPANY_B)
        assert cases.readback_ids(monkeypatch, kernel_b, "Luca Bianchi") == {luca}
        assert cases.hybrid(EMAIL_B, RULE_A) == set() and cases.facts(EMAIL_B, "pricing") == []
        env.assert_unrelated_unchanged(
            destination_before,
            env.snapshot(env.company_db(tmp_path, mnemonic_env.COMPANY_B)),
            blob_ids=[luca, price, rule_a],
            event_ids=[receipt],
        )
    finally:
        server.stop()
