"""The installed kernel CLI against this engine: D3 cases 1–5 of the M9 brief.

What this file proves, through the real ``cs`` entry point of an installed
kernel, the real ``rpc.chat`` / ``EngineClient`` over a real WebSocket, the
engine's own connection handler, ``dispatch_raw``, the real adapters, harness,
journal and stores, with only the provider transport and the bearer token
fixture-controlled:

1. ``cs memory`` renders its report from a TCP probe alone: no handshake, no
   RPC method dispatched.
2. ``cs ask`` is server-enforced read-only: every memory-writing verb and the
   natural-language "remember that" are refused with zero rows written, zero
   reservations and no agent initialised, while a read-only search still answers.
3. ``cs chat --allow create_memory,update_memory`` with the Acme forwarding
   correction commits one interactive ``operator_delegated`` UPDATE on the Acme
   COMPANY row, the typed words as observation and the model's content as
   suggestion, both numbers retained (``#HISTORY`` plus the ``append`` version),
   and the preparation ledger untouched.
4. A global-hours turn commits a company FACT the second account can read.
5. An account rule commits a STYLE in the caller's ``template:`` namespace that
   the second account's search and reads cannot see.

Every case asserts committed content, ``blob_versions``, namespaces, the
operation row's state and ``departure``, read visibility through the tools'
scoped read-back, ``search_local_memory``, ``get_facts_by_category`` and hybrid
search, and — through ``kernel_journey_env.assert_unrelated_unchanged`` over a
snapshot taken before the action — that no unrelated blob, version or operation
row moved. Cases 6–10 are ``test_mnemonic_kernel_journey_b.py``.

Firebase verification is not in the loop: the server asserts a fixture bearer
token and sets the claims itself, so nothing here is a claim about the
production ``server_ws`` handshake. Skipped without ``CS_PROJECT_KERNEL_PYTHON``;
with ``MNEMONIC_JOURNEY_REQUIRED=1`` a missing kernel is an error.
"""

from __future__ import annotations

import pytest

from tests.rpc import kernel_journey_cases as cases
from tests.rpc import kernel_journey_env as env
from tests.rpc.kernel_journey_cases import (
    ACCOUNT_A,
    ACCOUNT_B,
    ACME,
    ACME_MODEL,
    ACME_ROLE,
    FACT_CONTENT,
    FACTS_NS,
    NEW_PHONE,
    OLD_PHONE,
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


# ─── Case 1: `cs memory` ───────────────────────────────────────────────


def test_case_1_cs_memory_probes_the_socket_and_dispatches_nothing(journey):
    before = cases.table_snapshot(journey.db), cases.table_snapshot(journey.profile_db())

    result = journey.kernel.memory()

    assert "reachable" in result.stdout, result.stdout
    assert journey.server.url in result.stdout
    assert journey.server.frames == [], journey.server.frames
    assert journey.server.connections == 0
    assert (cases.table_snapshot(journey.db), cases.table_snapshot(journey.profile_db())) == before


# ─── Case 2: `cs ask` refusals ────────────────────────────────────────

REFUSED = [
    "/memory store Acme paga a 60 giorni",
    "/memory store Acme paga a 60 giorni --force",
    "/memory delete abc",
    "/update",
    "/jobs resume",
    "remember that the price is 12 euro",
]


def test_case_2_cs_ask_refuses_every_write_and_still_answers_a_search(journey, monkeypatch):
    acme_id, _ = journey.seed(ACME)
    inits = cases.count_agent_inits(monkeypatch)
    outer = env.outer(monkeypatch)  # nothing scripted: an agent that spoke would fail here
    role = env.role(monkeypatch)

    for message in REFUSED:
        before = cases.table_snapshot(journey.db), cases.table_snapshot(journey.profile_db())
        frames_before = len(journey.server.frames)

        result = journey.kernel.ask(message)

        assert "read-only" in result.stdout, (message, result.stdout, result.stderr)
        assert journey.server.frames[frames_before:] == ["system.capabilities", "chat.send"]
        assert (
            cases.table_snapshot(journey.db),
            cases.table_snapshot(journey.profile_db()),
        ) == before, message
        assert journey.reservations() == []
        assert inits[0] == 0, message
        assert outer._client.messages.create.calls == []
        assert role._client.messages.create.calls == []
    assert journey.operations() == []

    # A read-only search still answers: the real tool, the seeded row.
    env.outer(
        monkeypatch,
        env.response(cases.tool_call("tu-search", "search_local_memory", query="Acme")),
        env.response(env.text_block("Acme Srl: info@acme.test")),
    )
    company_before = journey.snapshot()
    result = journey.kernel.ask("Che email ha Acme?")
    assert "Acme Srl: info@acme.test" in result.stdout, (result.stdout, result.stderr)
    assert inits[0] == 1
    assert journey.operations() == []
    assert journey.mnemonic_reservations() == []
    journey.check_unrelated(company_before)


# ─── Case 3: the Acme forwarding correction through `cs chat` ────────

SAID_3 = f"Correggi: il numero di inoltro di Acme Srl ora è {NEW_PHONE}, non più {OLD_PHONE}"


def test_case_3_cs_chat_commits_the_acme_correction_and_leaves_preparation_alone(
    journey, monkeypatch
):
    acme_id, version = journey.seed(ACME)
    journey.disturb_preparation()
    ledger_before = journey.preparation_ledger()
    assert ledger_before["status"]["paused"] is True
    before = journey.snapshot()
    outer = env.outer(
        monkeypatch,
        env.response(
            cases.tool_call(
                "tu-3",
                "update_memory",
                blob_id=acme_id,
                new_content=ACME_MODEL,
                entry_type="entity_fact",
            )
        ),
        env.response(env.text_block("Aggiornato il numero di Acme.")),
    )
    env.role(monkeypatch, cases.update_decision(acme_id, version, ACME_ROLE))
    events = cases.record_events(monkeypatch)

    result = journey.kernel.chat(SAID_3, allow=["create_memory", "update_memory"], timeout=30)

    assert "[approval] update_memory -> once" in result.stdout, result.stdout
    assert "Aggiornato il numero di Acme." in result.stdout
    assert journey.server.frames == ["chat.send", "chat.approve"]

    # One interactive, operator-delegated event: the typed words are the
    # observation, the model's rewrite is the suggestion.
    ((event, requested),) = events
    assert event.origin == "interactive" and event.caller_class == "operator_delegated"
    assert event.observation == SAID_3
    assert event.suggestion == ACME_MODEL
    assert event.subject_hint.target_blob_id == acme_id
    assert requested.blob_id == acme_id and requested.subject_is_authoritative

    (op,) = journey.operations()
    assert op["event_id"] == event.event_id
    assert op["state"] == "committed" and op["departure"] is None
    assert op["caller_class"] == "operator_delegated" and op["origin"] == "interactive"
    assert op["source_ref"].startswith("chat:turn:")
    assert op["target_family"] == "user" and op["owner_id"] == ACCOUNT_A
    assert op["result"]["committed_ids"][0][0] == acme_id
    assert op["payload"] is None and op["lease"] is None

    # The UPDATE landed on the Acme COMPANY row and both numbers are retained:
    # the new one in force, the old one in #HISTORY and in the append version.
    namespace, owner, content = journey.blobs()[acme_id]
    assert (namespace, owner, content) == (USER_NS, ACCOUNT_A, ACME_ROLE)
    assert NEW_PHONE in content and OLD_PHONE in content.split("#HISTORY", 1)[1]
    assert journey.versions(acme_id) == [("append", ACME, event.event_id)]
    assert len(journey.blobs()) == 1

    # Read visibility, through every reader the brief names.
    assert journey.read_back(acme_id, ACCOUNT_A)["content"] == ACME_ROLE
    assert journey.hybrid_ids(ACCOUNT_A, "Acme Srl") == [acme_id]
    assert journey.search_tool_ids(ACCOUNT_A, "Acme Srl") == [acme_id]
    assert cases.tool_results(outer) and "Memory updated" in cases.tool_results(outer)[0]

    journey.check_unrelated(before, blob_ids=[acme_id], event_ids=[event.event_id])
    assert journey.preparation_ledger() == ledger_before
    assert len(journey.mnemonic_reservations()) == 1


# ─── Case 4: global hours, a company FACT the second account reads ───

SAID_4 = "Ricorda: siamo chiusi ogni sabato"


def test_case_4_global_hours_commit_a_company_fact_visible_to_the_second_account(
    journey, monkeypatch
):
    acme_id, _ = journey.seed(ACME)
    before = journey.snapshot()
    env.outer(
        monkeypatch,
        env.response(
            cases.tool_call(
                "tu-4",
                "create_memory",
                content=FACT_CONTENT,
                entry_type="entity_fact",
                namespace="facts",
            )
        ),
        env.response(env.text_block("Segnato: chiusi il sabato.")),
    )
    env.role(monkeypatch, cases.create_decision(FACT_CONTENT, "FACT", "company"))
    events = cases.record_events(monkeypatch)

    result = journey.kernel.chat(SAID_4, allow=["create_memory", "update_memory"], timeout=30)

    assert "[approval] create_memory -> once" in result.stdout, result.stdout
    ((event, requested),) = events
    assert event.observation == SAID_4 and event.suggestion == FACT_CONTENT
    assert requested.entity_type == "FACT"
    (op,) = journey.operations()
    assert op["state"] == "committed" and op["departure"] is None
    assert op["caller_class"] == "operator_delegated" and op["target_family"] == "facts"
    fact_id = op["result"]["committed_ids"][0][0]
    assert journey.blobs()[fact_id] == (FACTS_NS, ACCOUNT_A, FACT_CONTENT)
    assert journey.versions(fact_id) == []
    assert journey.blobs()[acme_id][2] == ACME

    assert journey.fact_ids(ACCOUNT_A, "Orari") == [fact_id]
    assert journey.read_back(fact_id, ACCOUNT_A)["namespace"] == FACTS_NS
    assert fact_id in journey.hybrid_ids(ACCOUNT_A, "chiusi sabato")
    assert fact_id in journey.search_tool_ids(ACCOUNT_A, "chiusi sabato")
    journey.check_unrelated(before, blob_ids=[fact_id], event_ids=[event.event_id])

    # The second account, same key: the FACT is company knowledge.
    journey.switch(env.OWNER_B)
    assert journey.fact_ids(ACCOUNT_B, "Orari") == [fact_id]
    assert journey.read_back(fact_id, ACCOUNT_B)["content"] == FACT_CONTENT
    assert fact_id in journey.hybrid_ids(ACCOUNT_B, "chiusi sabato")
    assert fact_id in journey.search_tool_ids(ACCOUNT_B, "chiusi sabato")
    assert acme_id in journey.hybrid_ids(ACCOUNT_B, "Acme Srl")
    journey.check_unrelated(before, blob_ids=[fact_id], event_ids=[event.event_id])


# ─── Case 5: an account rule, invisible to the second account ────────

SAID_5 = "D'ora in poi evita i punti esclamativi nelle risposte ai clienti"


def test_case_5_account_rule_commits_a_style_the_second_account_cannot_see(journey, monkeypatch):
    acme_id, _ = journey.seed(ACME)
    before = journey.snapshot()
    env.outer(
        monkeypatch,
        env.response(
            cases.tool_call(
                "tu-5", "create_memory", content=STYLE_CONTENT, entry_type="behavioral_rule"
            )
        ),
        env.response(env.text_block("Regola salvata.")),
    )
    env.role(monkeypatch, cases.create_decision(STYLE_CONTENT, "STYLE", "account"))
    events = cases.record_events(monkeypatch)

    result = journey.kernel.chat(SAID_5, allow=["create_memory", "update_memory"], timeout=30)

    assert "[approval] create_memory -> once" in result.stdout, result.stdout
    ((event, requested),) = events
    assert event.observation == SAID_5 and event.suggestion == STYLE_CONTENT
    assert event.subject_hint.entity_type == "STYLE"
    assert requested.entity_type == "STYLE" and requested.scope == "account"
    (op,) = journey.operations()
    assert op["state"] == "committed" and op["departure"] is None
    assert op["target_family"] == "template" and op["owner_id"] == ACCOUNT_A
    style_id = op["result"]["committed_ids"][0][0]
    assert journey.blobs()[style_id] == (f"template:{ACCOUNT_A}", ACCOUNT_A, STYLE_CONTENT)
    assert journey.versions(style_id) == []

    assert journey.read_back(style_id, ACCOUNT_A)["content"] == STYLE_CONTENT
    assert style_id in journey.hybrid_ids(ACCOUNT_A, "punti esclamativi")
    assert style_id in journey.search_tool_ids(ACCOUNT_A, "punti esclamativi")
    assert journey.fact_ids(ACCOUNT_A, "Orari") == []
    journey.check_unrelated(before, blob_ids=[style_id], event_ids=[event.event_id])

    # The second account, same key: the rule is not theirs to see.
    journey.switch(env.OWNER_B)
    assert journey.read_back(style_id, ACCOUNT_B) is None
    assert style_id not in journey.hybrid_ids(ACCOUNT_B, "punti esclamativi")
    assert journey.search_tool_ids(ACCOUNT_B, "punti esclamativi") == []
    assert journey.read_back(acme_id, ACCOUNT_B)["content"] == ACME
    journey.check_unrelated(before, blob_ids=[style_id], event_ids=[event.event_id])
