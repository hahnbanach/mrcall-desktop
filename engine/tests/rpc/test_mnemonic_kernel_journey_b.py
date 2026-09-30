"""The installed kernel CLI against this engine: D3 cases 6–10 of the M9 brief.

The second half of ``test_mnemonic_kernel_journey.py`` (cases 1–5), split only
for the file-size rule; the same real path — the installed kernel's ``cs``
entry point, ``rpc.chat`` / ``EngineClient`` over a real WebSocket, the
engine's own connection handler, ``dispatch_raw``, the real adapters, harness,
journal and stores — with only the provider transport and the bearer token
fixture-controlled. What this file proves:

6. A task-solve correction through ``cs rpc tasks.solve``: the typed
   instruction is the observation and the class ``operator_delegated``; the
   query selects nothing; the departure ``unnamed_subject`` is recorded.
7. A changed final proposal: the role answers UPDATE where the tool asked for
   CREATE; the write lands and ``departure.changed_action`` is in the row and in
   the tool's response the kernel relays to the model.
8. Decline: the kernel does not approve a tool outside ``--allow``; nothing is
   written and no mnemonic reservation exists.
9. Cancellation: the client drops the turn while the role is deciding; the
   grant is revoked, nothing commits, the event row is not ``committed``.
10. Second-account search: the second profile, same key, runs ``cs ask`` and
    finds the Acme entity and the FACT, not the first account's STYLE.

Every case asserts committed content, ``blob_versions``, namespaces, the
operation row's state and ``departure``, read visibility through the tools'
scoped read-back, ``search_local_memory``, ``get_facts_by_category`` and hybrid
search, and — through ``kernel_journey_env.assert_unrelated_unchanged`` over a
snapshot taken before the action — that no unrelated blob, version or operation
row moved.

Firebase verification is not in the loop: the server asserts a fixture bearer
token and sets the claims itself, so nothing here is a claim about the
production ``server_ws`` handshake. Skipped without ``CS_PROJECT_KERNEL_PYTHON``;
with ``MNEMONIC_JOURNEY_REQUIRED=1`` a missing kernel is an error.
"""

from __future__ import annotations

import threading

import pytest

from tests.rpc import kernel_journey_cases as cases
from tests.rpc import kernel_journey_env as env
from tests.rpc.kernel_journey_cases import (
    ACCOUNT_A,
    ACCOUNT_B,
    ACME,
    ACME_ORDERS,
    FACT_CONTENT,
    FACTS_NS,
    STYLE_CONTENT,
    USER_NS,
    Journey,
)

# The token the kernel presents, named here so the bearer check can be shown
# to bite from this file alone: point it elsewhere and every connecting case
# must fail at the server's handshake assertion.
KERNEL_TOKEN = env.TOKEN


@pytest.fixture(scope="module", autouse=True)
def kernel_python():
    return env.require_kernel()


@pytest.fixture
def journey(monkeypatch, tmp_path):
    monkeypatch.setattr(
        env, "BOOTSTRAP", env.BOOTSTRAP.replace(repr(env.TOKEN), repr(KERNEL_TOKEN))
    )
    j = Journey(monkeypatch, tmp_path)
    yield j
    j.stop()


# ─── Case 6: a task-solve correction through `cs rpc tasks.solve` ────

INSTRUCTION_6 = "Correggi l'indirizzo ordini di Acme: è orders@acme.test, non info@acme.test"
TASK_TEXT_6 = "Acme Srl chiede un preventivo entro venerdì"


def test_case_6_tasks_solve_typed_instruction_is_the_observation(journey, monkeypatch):
    import zylch.llm as llm_pkg
    from zylch.rpc import methods

    acme_id, version = journey.seed(ACME)
    created = journey.kernel.rpc(
        "tasks.create",
        {
            "contact_email": "info@acme.test",
            "contact_name": "Acme Srl",
            "title": TASK_TEXT_6,
            "event_id": "mail-acme-1",
            "suggested_action": "Rispondi con i termini di pagamento",
            "reason": TASK_TEXT_6,
        },
    )
    assert created["ok"] is True, created
    task_id = created["task_id"]
    ledger_before = journey.preparation_ledger()
    before = journey.snapshot()
    # The solve's own client and the post-solve reanalysis both come from the
    # `zylch.llm` package, not the chat agent's factory.
    outer = env.outer(
        monkeypatch,
        env.response(
            cases.tool_call("tu-solve", "update_memory", query="Acme", new_content=ACME_ORDERS)
        ),
        env.response(env.text_block("Corretto l'indirizzo ordini di Acme.")),
        env.response(
            cases.tool_call(
                "tu-re", "reanalyze_decision", action="keep", reason="still open", waiting_on="us"
            )
        ),
    )
    monkeypatch.setattr(llm_pkg, "make_llm_client", lambda *a, **k: outer)
    monkeypatch.setattr(llm_pkg, "try_make_llm_client", lambda *a, **k: outer)
    env.role(monkeypatch, cases.update_decision(acme_id, version, ACME_ORDERS))
    events = cases.record_events(monkeypatch)

    outcome = {}

    def solve():
        outcome["result"] = journey.kernel.rpc(
            "tasks.solve", {"task_id": task_id, "instructions": INSTRUCTION_6}, ok=None
        )

    worker = threading.Thread(target=solve, daemon=True)
    worker.start()
    cases.wait_until(
        lambda: methods._active_executor is not None
        and "tu-solve" in methods._active_executor._pending,
        what="the solve to park on its approval gate",
    )
    approved = journey.kernel.rpc(
        "tasks.solve.approve", {"tool_use_id": "tu-solve", "approved": True}
    )
    assert approved == {"ok": True}, approved
    worker.join(timeout=120)
    assert not worker.is_alive(), "tasks.solve did not return"
    assert outcome["result"].returncode == 0, (outcome["result"].stdout, outcome["result"].stderr)
    assert '"ok": true' in outcome["result"].stdout, outcome["result"].stdout

    ((event, requested),) = events
    assert event.observation == INSTRUCTION_6
    assert TASK_TEXT_6 not in event.observation
    assert event.caller_class == "operator_delegated" and event.origin == "interactive"
    assert event.source_kind == "task_instruction" and event.subject_hint is None
    assert event.suggestion == ACME_ORDERS
    assert requested.blob_id is None and requested.subject_is_authoritative is False

    (op,) = journey.operations()
    assert op["state"] == "committed"
    assert op["source_ref"].startswith(f"task_instruction:task:{task_id}@")
    assert op["departure"]["flags"] == ["unnamed_subject"]
    assert op["departure"]["proposed"]["targets"] == [acme_id]
    assert journey.blobs()[acme_id] == (USER_NS, ACCOUNT_A, ACME_ORDERS)
    assert journey.versions(acme_id) == [("append", ACME, event.event_id)]
    assert journey.read_back(acme_id, ACCOUNT_A)["content"] == ACME_ORDERS
    assert journey.hybrid_ids(ACCOUNT_A, "orders@acme.test") == [acme_id]
    assert journey.search_tool_ids(ACCOUNT_A, "Acme Srl") == [acme_id]
    assert journey.fact_ids(ACCOUNT_A, "Orari") == []
    assert "Memory updated" in cases.tool_results(outer)[0]
    assert "Note:" in cases.tool_results(outer)[0]
    journey.check_unrelated(before, blob_ids=[acme_id], event_ids=[event.event_id])
    assert journey.preparation_ledger() == ledger_before


# ─── Case 7: the role changes the action ─────────────────────────────

SAID_7 = "Ricorda: l'indirizzo ordini di Acme Srl è orders@acme.test"


def test_case_7_changed_action_is_committed_and_recorded_on_both_sides(journey, monkeypatch):
    acme_id, version = journey.seed(ACME)
    before = journey.snapshot()
    outer = env.outer(
        monkeypatch,
        env.response(
            cases.tool_call("tu-7", "create_memory", content=ACME_ORDERS, entry_type="entity_fact")
        ),
        env.response(env.text_block("Salvato l'indirizzo ordini di Acme.")),
    )
    env.role(monkeypatch, cases.update_decision(acme_id, version, ACME_ORDERS))
    events = cases.record_events(monkeypatch)

    result = journey.kernel.chat(SAID_7, allow=["create_memory", "update_memory"], timeout=30)

    assert "[approval] create_memory -> once" in result.stdout, result.stdout
    assert "Salvato l'indirizzo ordini di Acme." in result.stdout
    ((event, requested),) = events
    assert event.observation == SAID_7 and requested.action == "CREATE"
    (op,) = journey.operations()
    assert op["state"] == "committed"
    assert op["departure"]["flags"] == ["changed_action", "unnamed_subject"]
    assert op["departure"]["requested"]["action"] == "CREATE"
    assert op["departure"]["proposed"] == {
        "action": "UPDATE",
        "entity_type": "COMPANY",
        "scope": "entity",
        "targets": [acme_id],
    }
    assert journey.blobs()[acme_id] == (USER_NS, ACCOUNT_A, ACME_ORDERS)
    assert len(journey.blobs()) == 1
    assert journey.versions(acme_id) == [("append", ACME, event.event_id)]
    # The tool's response carries the same departure back to the model.
    (tool_result,) = cases.tool_results(outer)
    assert '"action": "updated"' in tool_result and "changed_action" in tool_result
    assert journey.read_back(acme_id, ACCOUNT_A)["content"] == ACME_ORDERS
    assert journey.hybrid_ids(ACCOUNT_A, "orders@acme.test") == [acme_id]
    assert journey.search_tool_ids(ACCOUNT_A, "Acme Srl") == [acme_id]
    journey.check_unrelated(before, blob_ids=[acme_id], event_ids=[event.event_id])


# ─── Case 8: the kernel declines a tool outside --allow ──────────────


def test_case_8_a_tool_outside_allow_is_denied_and_nothing_is_written(journey, monkeypatch):
    acme_id, _ = journey.seed(ACME)
    before = journey.snapshot()
    reservations_before = journey.reservations()
    outer = env.outer(
        monkeypatch,
        env.response(
            cases.tool_call("tu-8", "create_memory", content=FACT_CONTENT, entry_type="entity_fact")
        ),
        env.response(env.text_block("Non ho salvato nulla.")),
    )
    role = env.role(monkeypatch)
    events = cases.record_events(monkeypatch)

    result = journey.kernel.chat(
        "Ricorda: siamo chiusi ogni sabato", allow=["update_memory"], timeout=30
    )

    assert "[approval] create_memory -> deny" in result.stdout, result.stdout
    assert "Non ho salvato nulla." in result.stdout
    assert journey.server.frames == ["chat.send", "chat.approve"]
    (tool_result,) = cases.tool_results(outer)
    assert "declined" in tool_result.lower()
    assert events == []
    assert role._client.messages.create.calls == []
    assert journey.operations() == []
    assert set(journey.blobs()) == {acme_id}
    assert journey.versions(acme_id) == []
    assert journey.mnemonic_reservations() == []
    assert (
        len(journey.reservations()) == len(reservations_before) + 2
    )  # the outer agent's two turns
    assert journey.fact_ids(ACCOUNT_A, "Orari") == []
    assert journey.hybrid_ids(ACCOUNT_A, "chiusi sabato") == []
    journey.check_unrelated(before)


# ─── Case 9: the client drops the turn while the role is deciding ────

SAID_9 = "Ricorda: Beta Spa paga a 30 giorni, ordini@beta.test"
BETA = "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\nEmail: ordini@beta.test\n#ABOUT\nPays at 30 days."


def test_case_9_a_dropped_turn_revokes_the_grant_and_commits_nothing(journey, monkeypatch):
    from zylch.memory.mnemonic import authorization
    from zylch.rpc import methods

    acme_id, _ = journey.seed(ACME)
    before = journey.snapshot()
    env.outer(
        monkeypatch,
        env.response(
            cases.tool_call("tu-9", "create_memory", content=BETA, entry_type="entity_fact")
        ),
        env.response(env.text_block("Salvato Beta.")),
    )
    hold = env.Hold()
    role = env.role(monkeypatch, hold(env.response(env.text_block(cases.create_decision(BETA)))))
    events = cases.record_events(monkeypatch)
    disconnects = journey.server.disconnects

    outcome = {}

    def chat():
        outcome["result"] = journey.kernel.chat(SAID_9, allow=["create_memory"], timeout=3, ok=None)

    worker = threading.Thread(target=chat, daemon=True)
    worker.start()
    hold.wait_entered()
    journey.server.wait_disconnected(disconnects + 1)
    hold.release()
    worker.join(timeout=60)
    assert not worker.is_alive()
    assert outcome["result"].returncode != 0, outcome["result"].stdout
    assert "Salvato Beta." not in outcome["result"].stdout

    ((event, _requested),) = events
    cases.wait_until(
        lambda: journey.operations() and journey.operations()[0]["state"] != "pending",
        what="the cancelled operation to settle",
    )
    assert event.cancellation.cancelled is True
    assert authorization._ISSUED == {}
    (op,) = journey.operations()
    assert op["event_id"] == event.event_id
    assert op["state"] != "committed" and op["state"] in ("review", "failed")
    assert op["result"]["outcome"] != "committed"
    assert set(journey.blobs()) == {acme_id}
    assert journey.versions(acme_id) == []
    assert journey.hybrid_ids(ACCOUNT_A, "Beta Spa") == []
    assert journey.search_tool_ids(ACCOUNT_A, "Beta Spa") == []
    assert len(role._client.messages.create.calls) == 1
    assert methods._active_chats == {} and methods._pending_approvals == {}
    journey.check_unrelated(before, event_ids=[event.event_id])


# ─── Case 10: the second account searches the shared store ──────────


def test_case_10_second_account_finds_the_entity_and_the_fact_not_the_style(journey, monkeypatch):
    acme_id, _ = journey.seed(ACME)
    fact_id, _ = journey.seed(FACT_CONTENT, namespace=FACTS_NS)
    style_id, _ = journey.seed(STYLE_CONTENT, namespace=f"template:{ACCOUNT_A}")
    before = journey.snapshot()

    kernel_b = journey.switch(env.OWNER_B)
    outer = env.outer(
        monkeypatch,
        env.response(
            cases.tool_call(
                "tu-10", "search_local_memory", query="Acme Srl chiusi sabato punti esclamativi"
            )
        ),
        env.response(env.text_block("Acme Srl (info@acme.test); chiusi il sabato.")),
    )
    role = env.role(monkeypatch)
    inits = cases.count_agent_inits(monkeypatch)

    result = kernel_b.ask("Cosa sappiamo di Acme e del sabato?")

    assert "Acme Srl (info@acme.test); chiusi il sabato." in result.stdout, result.stdout
    assert journey.server.frames == ["system.capabilities", "chat.send"]
    assert inits[0] == 1
    (tool_result,) = cases.tool_results(outer)
    assert acme_id in tool_result and fact_id in tool_result
    assert style_id not in tool_result and STYLE_CONTENT not in tool_result
    assert role._client.messages.create.calls == []

    assert journey.read_back(acme_id, ACCOUNT_B)["content"] == ACME
    assert journey.read_back(fact_id, ACCOUNT_B)["namespace"] == FACTS_NS
    assert journey.read_back(style_id, ACCOUNT_B) is None
    assert journey.fact_ids(ACCOUNT_B, "Orari") == [fact_id]
    found = journey.hybrid_ids(ACCOUNT_B, "Acme Srl chiusi sabato punti esclamativi")
    assert {acme_id, fact_id} <= set(found) and style_id not in found
    found = journey.search_tool_ids(ACCOUNT_B, "Acme Srl chiusi sabato punti esclamativi")
    assert {acme_id, fact_id} <= set(found) and style_id not in found
    assert journey.read_back(style_id, ACCOUNT_A)["content"] == STYLE_CONTENT
    assert journey.operations() == []
    assert journey.mnemonic_reservations(env.OWNER_B) == []
    journey.check_unrelated(before)
