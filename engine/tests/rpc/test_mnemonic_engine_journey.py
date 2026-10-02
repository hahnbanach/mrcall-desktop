"""The engine paths of the installed-client journey: D3 cases 11, 12, 13 and 17.

What the kernel CLI drives is driven through it — ``cs rpc preparation.pause``
and ``preparation.status``, ``cs chat --allow update_memory`` for a correction,
``cs ask`` for every read-back — over the engine's own WebSocket handler
(``kernel_journey_env``); what the kernel has no route for is driven where the
engine offers it: a direct ``submit`` for an automatic event and the ``zylch
memory-sweep`` command in process. Two profiles on one company key, real
profile and company SQLite files, the real ``LLMClient`` and reservation
ledger, only the provider transport scripted.

Each case asserts the committed content, the retained versions, the
namespaces, the operation row's state and departure, the paid calls in the
profile ledger, the read visibility from each account it names, and that no
unrelated blob, version or operation row moved. Firebase verification is not
in the loop: the handler asserts the fixture bearer token and sets the claims
itself, so nothing here is a claim about ``server_ws``'s own auth. Cases 14–16
(the worker, the restart replay and the join) are ``test_mnemonic_engine_journey_b.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.memory import mnemonic_env
from tests.memory.consolidation_env import LUCA_EMAIL, healthy, merge_answer, person, scripted
from tests.rpc import engine_journey_cases as cases
from tests.rpc import kernel_journey_env as env
from tests.rpc.engine_journey_cases import EMAIL_A, EMAIL_B

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\nPhone: +390212345678\n"
    "#ABOUT\nIndustrial supplier in Milan.\n#HISTORY\n- pays at 60 days"
)
ACME_CORRECTED = ACME.replace("info@acme.test", "orders@acme.test")
ACME_PRICE = "Category: pricing\nKey: acme list\nValue: EUR 90 per unit for Acme only"
ACME_PRICE_NEW = ACME_PRICE.replace("EUR 90", "EUR 95")
HOURS = "Category: hours\nKey: saturday\nValue: closed every Saturday"
ENTITY_NS = f"user:{env.COMPANY}"
FACTS_NS = f"facts:{env.COMPANY}"


@pytest.fixture
def bench(monkeypatch, tmp_path):
    """Account A booted on the company key, the server serving it, its kernel."""
    env.require_kernel()
    env.boot(monkeypatch, tmp_path, env.OWNER_A)
    server = env.EngineServer(env.OWNER_A).start(monkeypatch)
    kernel = env.Kernel(tmp_path, server, env.OWNER_A)
    yield SimpleNamespace(root=tmp_path, server=server, kernel=kernel, db=env.company_db(tmp_path))
    server.stop()
    from zylch.storage import database as dbm

    dbm.dispose_engine()
    mnemonic_env.clear_process_state()


def as_b(monkeypatch, bench, key: str = env.COMPANY) -> env.Kernel:
    """The second account, booted in place of the first; the server authenticates it."""
    env.switch(monkeypatch, bench.root, bench.server, env.OWNER_B, key)
    return env.Kernel(bench.root, bench.server, env.OWNER_B)


def update_decision(blob_id: str, version: str, content: str) -> str:
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the same company, its ordering address corrected",
        }
    )


def correction(monkeypatch, bench, blob_id: str, new_content: str, *decisions: str):
    """``cs chat --allow update_memory``: the agent corrects ``blob_id``, the role decides."""
    llm = env.outer(
        monkeypatch,
        env.response(
            env.tool_use_block(
                "tu-fix", "update_memory", {"blob_id": blob_id, "new_content": new_content}
            )
        ),
        env.response(env.text_block("Fatto.")),
    )
    env.role(monkeypatch, *decisions)
    result = bench.kernel.chat(
        "Correzione sulla memoria di Acme", allow=["update_memory"], timeout=60
    )
    assert "update_memory: once" in result.stdout, result.stdout
    (tool_result,) = [
        b
        for b in llm._client.messages.create.calls[1]["messages"][2]["content"]
        if b.get("type") == "tool_result"
    ]
    return tool_result["content"]


# ─── Case 11: an explicit correction while preparation is paused ──────


def test_case_11_a_correction_under_a_paused_preparation_commits_and_the_pause_survives(
    monkeypatch, bench
):
    """An interactive grant rides the caller's turn: the reservation is real, the
    pause is not consulted, and nothing of preparation's ledger moves."""
    acme = cases.seed_blob(env.OWNER_A, ENTITY_NS, ACME)
    version = cases.version_of(acme)
    before = env.snapshot(bench.db)
    paused = bench.kernel.rpc("preparation.pause")
    assert paused["paused"] is True

    answer = correction(
        monkeypatch, bench, acme, ACME_CORRECTED, update_decision(acme, version, ACME_CORRECTED)
    )

    assert "orders@acme.test" in answer and "info@acme.test" not in answer
    stored = cases.blobs(bench.db)
    assert stored[acme] == (ENTITY_NS, env.OWNER_A, ACME_CORRECTED)
    assert cases.versions(bench.db, acme) == [("append", ACME)]
    row = cases.chat_operation(bench.db)
    assert (row["state"], row["departure"], row["owner_id"]) == ("committed", None, EMAIL_A)
    assert (row["caller_class"], row["origin"]) == ("operator_delegated", "interactive")
    assert row["result"]["committed_ids"] == [[acme, cases.version_of(acme)]]
    assert cases.paid_decisions(bench.root) == [("memory.mnemonic", 1)]
    after = bench.kernel.rpc("preparation.status")
    assert after["paused"] is True
    for field in ("running", "attempted", "completed", "failed", "limit", "stop_reason"):
        assert after[field] == paused[field], field
    assert after["channels"] == paused["channels"]
    assert cases.readback_ids(monkeypatch, bench.kernel, "Acme Srl") == {acme}
    env.assert_unrelated_unchanged(
        before, env.snapshot(bench.db), blob_ids=[acme], event_ids=[row["event_id"]]
    )


# ─── Case 12: an automatic event with no admitted item ────────────────


def test_case_12_an_automatic_event_outside_an_admitted_item_is_refused_before_any_reservation(
    bench,
):
    """The engine has no route that submits an automatic event on its own: the
    worker does, inside an admitted item. Submitted with none, the grant is
    minted and the dispatch is refused at the boundary — zero provider calls,
    zero reservations, no blob, the row parked in review."""
    from zylch.llm.budget import budget_snapshot
    from zylch.memory.mnemonic.commit import submit
    from zylch.memory.mnemonic.contracts import AUTOMATIC, AUTOMATIC_OBSERVATION, MemoryEvent

    before = env.snapshot(bench.db)
    event = MemoryEvent(
        owner_id=EMAIL_A,
        company_key=env.COMPANY,
        caller_class=AUTOMATIC_OBSERVATION,
        origin=AUTOMATIC,
        source_kind="email",
        source_id="mail-9",
        source_revision="rev-9",
        observation="Acme Srl pays at 60 days.",
        stage="memory:email",
    )
    llm = mnemonic_env.client(
        json.dumps(
            {
                "action": "CREATE",
                "entity_type": "COMPANY",
                "scope": "entity",
                "content": ACME,
                "reason": "no visible candidate describes this company",
            }
        )
    )

    result = submit(event, client=llm)

    assert result.outcome == "review_needed" and "admitted preparation item" in result.reason
    assert result.committed_ids == () and cases.calls(llm) == 0
    assert cases.reservations(bench.root) == []
    snapshot = budget_snapshot(env.OWNER_A)
    assert (snapshot["reserved_usd"], snapshot["spent_usd"]) == (0, 0)
    assert cases.blobs(bench.db) == {}
    row = cases.operations(bench.db)[event.event_id]
    assert (row["state"], row["origin"], row["departure"]) == ("review", "automatic", None)
    assert row["source_ref"] == "email:mail-9@rev-9"
    env.assert_unrelated_unchanged(before, env.snapshot(bench.db), event_ids=[event.event_id])


# ─── Case 13: a restricted legacy FACT ────────────────────────────────


def test_case_13_a_fact_a_review_restricted_is_absent_from_reads_while_a_valid_one_stays(
    monkeypatch, bench
):
    """The restriction is recorded the way a review records it: the role, shown
    the pinned legacy row, declines to treat it as company knowledge and names
    it ``ineligible``. From then on the row is left out of the fact store and
    hybrid search for every account, stays readable by id, and the valid
    unmarked FACT beside it is served as before."""
    restricted = cases.seed_blob(env.OWNER_A, FACTS_NS, ACME_PRICE)
    valid = cases.seed_blob(env.OWNER_A, FACTS_NS, HOURS)
    version = cases.version_of(restricted)
    assert cases.facts(EMAIL_A, "pricing") == [restricted]
    before = env.snapshot(bench.db)

    answer = correction(
        monkeypatch,
        bench,
        restricted,
        ACME_PRICE_NEW,
        json.dumps(
            {
                "action": "REVIEW",
                "reason": "a customer's price, not company knowledge",
                "ineligible": [restricted],
            }
        ),
    )

    assert "not company knowledge" in answer
    row = cases.chat_operation(bench.db)
    assert (row["state"], row["departure"]) == ("review", None)
    assert row["restrictions"] == [{"blob_id": restricted, "version": version}]
    assert cases.paid_decisions(bench.root) == [("memory.mnemonic", 1)]
    stored = cases.blobs(bench.db)
    assert stored[restricted] == (FACTS_NS, env.OWNER_A, ACME_PRICE)
    assert stored[valid] == (FACTS_NS, env.OWNER_A, HOURS)
    assert cases.versions(bench.db, restricted) == []
    for owner in (EMAIL_A, env.OWNER_A):
        assert cases.facts(owner, "pricing") == []
        assert cases.facts(owner, "hours") == [valid]
        assert restricted not in cases.hybrid(owner, "Acme list price per unit")
        assert valid in cases.hybrid(owner, "closed every Saturday")
    assert cases.storage().get_blob(restricted, env.OWNER_A)["content"] == ACME_PRICE
    assert restricted not in cases.readback_ids(monkeypatch, bench.kernel, "Acme price per unit")
    assert valid in cases.readback_ids(monkeypatch, bench.kernel, "closed every Saturday")

    kernel_b = as_b(monkeypatch, bench)
    assert cases.facts(EMAIL_B, "pricing") == [] and cases.facts(EMAIL_B, "hours") == [valid]
    assert restricted not in cases.hybrid(EMAIL_B, "Acme list price per unit")
    assert restricted not in cases.readback_ids(monkeypatch, kernel_b, "Acme price per unit")
    assert valid in cases.readback_ids(monkeypatch, kernel_b, "closed every Saturday")
    env.assert_unrelated_unchanged(before, env.snapshot(bench.db), event_ids=[row["event_id"]])


# ─── Case 17: a merge with deferred profile references ────────────────


def test_case_17_a_sweep_merges_one_pair_and_re_points_only_the_committing_profiles_ledger(
    monkeypatch, tmp_path
):
    """``zylch memory-sweep`` on the scripted transport: one MERGE, the keeper
    rewritten with both texts retained, the donor gone behind its alias, the
    ``task_references`` effect applied to this profile's task ledger and to no
    other — the second account's ledger keeps the donor id and resolves it
    through the alias."""
    from zylch.memory.scope import resolve_aliases
    from zylch.storage.database import get_session

    env.require_kernel()
    env.boot(monkeypatch, tmp_path, env.OWNER_B)
    keeper = cases.seed_blob(
        env.OWNER_B,
        ENTITY_NS,
        person(about="Purchasing at Alpha; handles every order."),
        ("email", LUCA_EMAIL),
    )
    donor = cases.seed_blob(
        env.OWNER_B, ENTITY_NS, person(about="Joins the Thursday sync."), ("email", LUCA_EMAIL)
    )
    cases.seed_task(EMAIL_B, "t-b", [donor])
    env.boot(monkeypatch, tmp_path, env.OWNER_A)
    server = env.EngineServer(env.OWNER_A).start(monkeypatch)
    bench = SimpleNamespace(root=tmp_path, server=server, db=env.company_db(tmp_path))
    try:
        cases.seed_task(EMAIL_A, "t-a", [donor, "blob-other"])
        keeper_text = cases.blobs(bench.db)[keeper][2]
        donor_text = cases.blobs(bench.db)[donor][2]
        healthy(monkeypatch, owner=EMAIL_A)
        transport = scripted(monkeypatch, merge_answer(cases.storage(), keeper, donor))
        before = env.snapshot(bench.db)

        result = cases.cli(monkeypatch, tmp_path, env.OWNER_A, "memory-sweep")

        assert result.exit_code == 0, result.output
        assert transport.call_count == 1
        stored = cases.blobs(bench.db)
        assert donor not in stored
        assert stored[keeper] == (
            ENTITY_NS,
            env.OWNER_B,
            keeper_text + f"\n- folded in {donor[:8]}",
        )
        assert cases.versions(bench.db, keeper) == [("consolidate", keeper_text)]
        assert cases.versions(bench.db, donor) == [("consolidate", donor_text)]
        assert env.rows(bench.db, "SELECT merged_id, keeper_id FROM blob_aliases") == [
            (donor, keeper)
        ]
        (row,) = operations_of_kind(bench.db, "consolidation:")
        assert (row["state"], row["departure"], row["owner_id"]) == ("committed", None, EMAIL_A)
        assert row["pending_effects"] == [] and row["result"]["committed_ids"][0][0] == keeper
        assert cases.reservations(bench.root) == [("memory.mnemonic", 1)]
        assert cases.task_blobs("t-a") == [keeper, "blob-other"]
        with get_session() as session:
            assert keeper in resolve_aliases(session, [donor])

        kernel_b = as_b(monkeypatch, bench)
        assert cases.task_blobs("t-b") == [donor]
        with get_session() as session:
            assert resolve_aliases(session, [donor]) == {donor, keeper}
        assert cases.readback_ids(monkeypatch, kernel_b, "Luca Bianchi") == {keeper}
        env.assert_unrelated_unchanged(
            before, env.snapshot(bench.db), blob_ids=[keeper, donor], event_ids=[row["event_id"]]
        )
    finally:
        server.stop()


def operations_of_kind(db, prefix: str):
    return [r for r in cases.operations(db).values() if r["source_ref"].startswith(prefix)]
