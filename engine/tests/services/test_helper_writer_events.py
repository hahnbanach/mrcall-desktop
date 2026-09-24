"""The helper writers are adapters: facts, rules and correction learning submit.

Against real split databases with the role's answers scripted at the
transport (``tests/memory/mnemonic_env.with_client``); the validator, the
journal and the commit are real. What these hold: each adapter submits with
the hint and the requested baseline the brief states; the deterministic
defences stay deterministic and unpaid; ``entry.py`` grants exactly three
states; correction learning rides the turn it was spawned in and leaves
preparation untouched; the spawn in the RPC solve sits inside that turn.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from zylch.memory.blob_storage import BlobStorage
from zylch.memory.mnemonic import commit as commit_mod
from zylch.memory.mnemonic.contracts import AUTOMATIC, INTERACTIVE, OPERATOR_DELEGATED
from zylch.memory.mnemonic.entry import EntryRefused, entry_for
from zylch.memory.mnemonic.turn import revocable_turn
from zylch.services import correction_learning as cl
from zylch.services import facts_store, preparation, prefs_store
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob, MemoryOperation

from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    client,
    stub_embedder,
    with_client,
)

RULE = (
    "Never promise a specific callback time to a customer; say the team will get "
    "back to them and ask for the details needed to proceed."
)
STYLE_HEADER = "#IDENTIFIERS\nEntity type: STYLE\nScope: account\n#ABOUT\n"
FACT_HEADER = "#IDENTIFIERS\nEntity type: FACT\nScope: company\n"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    from zylch.assistant.turn_context import set_turn_observation

    stub_embedder(monkeypatch, embedder)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    set_turn_observation("Ricordati: mai promettere un orario di richiamata.")
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def create(entity_type, content, scope):
    return json.dumps(
        {"action": "CREATE", "entity_type": entity_type, "scope": scope, "content": content, "reason": "new"}
    )


def update(entity_type, content, scope, blob_id, version):
    return json.dumps(
        {
            "action": "UPDATE",
            "entity_type": entity_type,
            "scope": scope,
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the same subject, updated",
        }
    )


def submitted(monkeypatch):
    """Capture every event and baseline the adapters submit, deciding nothing."""
    seen = []

    def capture(event, **kwargs):
        from zylch.memory.mnemonic.proposals import MnemonicResult

        seen.append((event, kwargs.get("requested")))
        return MnemonicResult.review_needed(event.event_id, "captured")

    import zylch.memory.mnemonic as pkg

    monkeypatch.setattr(commit_mod, "submit", capture)
    monkeypatch.setattr(pkg, "submit", capture)
    return seen


def blobs():
    with get_session() as session:
        return {str(b.id): (b.namespace, b.content) for b in session.query(Blob).all()}


def version_of(blob_id, embedder):
    return BlobStorage(get_session, embedder).get_blob(blob_id, OWNER_A)["updated_at"]


# ─── facts: the exact row pinned, the baseline named ──────────────────


def test_a_fact_pins_its_exact_row_and_names_an_update(profile, monkeypatch, embedder):
    storage = BlobStorage(get_session, embedder)
    row = storage.store_blob(OWNER_A, f"facts:{COMPANY_A}", "Category: pricing\nKey: list\nValue: 100", "seed")
    seen = submitted(monkeypatch)

    assert facts_store.upsert_fact(OWNER_A, "Pricing", "List", "EUR 120") is None  # captured, not written

    (event, requested), = seen
    assert event.subject_hint.entity_type == "FACT"
    assert event.subject_hint.target_blob_id == row["id"]
    assert event.suggestion == "Category: Pricing\nKey: List\nEUR 120"
    assert event.caller_class == OPERATOR_DELEGATED and event.origin == INTERACTIVE
    assert event.source_kind == "chat" and event.observation.startswith("Ricordati")
    assert (requested.action, requested.blob_id, requested.entity_type) == ("UPDATE", row["id"], "FACT")
    assert requested.subject_is_authoritative is True


def test_a_new_fact_names_a_create_and_returns_the_committed_id(profile, monkeypatch):
    content = FACT_HEADER + "Category: pricing\nKey: list\n#ABOUT\nValue: EUR 120 per unit"
    with_client(monkeypatch, client(create("FACT", content, "company")))

    blob_id = facts_store.upsert_fact(OWNER_A, "pricing", "list", "EUR 120 per unit")

    assert blob_id and blobs()[blob_id] == (f"facts:{COMPANY_A}", content)
    assert facts_store.exact_fact(OWNER_A, "pricing", "list")["blob_id"] == blob_id


def test_a_fact_the_role_declines_is_not_written_and_returns_none(profile, monkeypatch):
    with_client(monkeypatch, client(json.dumps({"action": "REVIEW", "reason": "this is one customer's price"})))
    assert facts_store.upsert_fact(OWNER_A, "pricing", "acme-rate", "EUR 80") is None
    assert blobs() == {}


# ─── rules: deterministic defences unpaid, the rest submitted ──────────


def test_an_entity_shaped_rule_and_an_exact_duplicate_never_reach_the_role(profile, monkeypatch):
    with_client(monkeypatch, client(create("STYLE", STYLE_HEADER + RULE, "account")))
    assert prefs_store.store_rule(OWNER_A, RULE, "t", writer="test")["action"] == "created"
    seen = submitted(monkeypatch)

    assert prefs_store.store_rule(OWNER_A, f"  {RULE.upper()}  ", "t", writer="test")["action"] == "duplicate"
    entity = "#IDENTIFIERS\nEntity type: STYLE\nName: Win-back\n#ABOUT\nx"
    assert prefs_store.store_rule(OWNER_A, entity, "t", writer="test")["action"] == "refused"
    assert seen == []


def test_a_superseding_rule_pins_the_candidate_and_names_an_update(profile, monkeypatch, embedder):
    with_client(monkeypatch, client(create("STYLE", STYLE_HEADER + RULE, "account")))
    first = prefs_store.store_rule(OWNER_A, RULE, "t", writer="test")
    assert first["action"] == "created"
    seen = submitted(monkeypatch)
    extended = RULE + " Always sign as the team, never with an invented first name."

    outcome = prefs_store.store_rule(OWNER_A, extended, "t", writer="test")

    assert outcome["action"] == "review"  # captured, not decided
    (event, requested), = seen
    assert event.subject_hint.entity_type == "STYLE"
    assert event.subject_hint.target_blob_id == first["blob_id"]
    assert event.explicit_request is False
    assert (requested.action, requested.blob_id, requested.entity_type, requested.scope) == (
        "UPDATE",
        first["blob_id"],
        "STYLE",
        "account",
    )


def test_a_superseding_rule_the_role_accepts_is_superseded_in_place(profile, monkeypatch, embedder):
    with_client(monkeypatch, client(create("STYLE", STYLE_HEADER + RULE, "account")))
    first = prefs_store.store_rule(OWNER_A, RULE, "t", writer="test")
    extended = RULE + " Always sign as the team, never with an invented first name."
    with_client(
        monkeypatch,
        client(update("STYLE", STYLE_HEADER + extended, "account", first["blob_id"], version_of(first["blob_id"], embedder))),
    )

    outcome = prefs_store.store_rule(OWNER_A, extended, "t", writer="test")

    assert outcome == {"action": "superseded", "blob_id": first["blob_id"], "reason": "extends an existing rule"}
    assert blobs()[first["blob_id"]] == (f"template:{OWNER_A}", STYLE_HEADER + extended)
    assert len(blobs()) == 1


def test_a_refinement_pins_the_row_with_an_authoritative_baseline(profile, monkeypatch):
    with_client(monkeypatch, client(create("STYLE", STYLE_HEADER + "RULE: v1", "account")))
    rid = prefs_store.store_rule(OWNER_A, "RULE: v1", "t", writer="test")["blob_id"]
    seen = submitted(monkeypatch)

    outcome = prefs_store.refine_rule(OWNER_A, rid, "RULE: v2 refined", "t", writer="test")

    assert outcome["action"] == "review"
    (event, requested), = seen
    assert event.subject_hint.target_blob_id == rid and event.explicit_request is True
    assert requested.action == "UPDATE" and requested.subject_is_authoritative is True


# ─── entry.py: three states ───────────────────────────────────────────


def test_inside_an_admitted_item_the_entry_is_automatic_with_the_items_stage_and_source(profile):
    import asyncio

    seen = {}

    class Worker:
        owner_id = OWNER_A

        @preparation.bounded_item("memory:email")
        async def process(self, item):
            seen["entry"] = entry_for(fallback="x")
            return True

    with preparation.preparation_run(OWNER_A):
        asyncio.run(Worker().process({"id": "mail-9"}))

    entry = seen["entry"]
    assert entry.origin == AUTOMATIC and entry.stage == "memory:email" and entry.source_id == "mail-9"
    assert entry.source_kind == "email"


def test_inside_a_run_but_outside_an_item_the_helpers_refuse_and_write_nothing(profile, monkeypatch):
    seen = submitted(monkeypatch)
    with preparation.preparation_run(OWNER_A):
        with pytest.raises(EntryRefused):
            entry_for(fallback="x")
        assert facts_store.upsert_fact(OWNER_A, "pricing", "list", "EUR 1") is None
        assert prefs_store.store_rule(OWNER_A, RULE, "t", writer="test")["action"] == "refused"
    assert seen == [] and blobs() == {}


def test_outside_any_run_the_entry_is_interactive_on_the_turn(profile):
    from zylch.assistant.turn_context import get_turn_id
    from zylch.memory.mnemonic.turn import turn_cancellation

    with revocable_turn() as handle:
        entry = entry_for(fallback="x")
        assert entry.origin == INTERACTIVE and entry.stage is None
        assert entry.source_id == f"turn:{get_turn_id()}"
        assert entry.observation == "Ricordati: mai promettere un orario di richiamata."
        assert entry.cancellation is handle is turn_cancellation()


# ─── correction learning rides the turn and leaves preparation alone ──


class _Judge:
    """Both judges answer at once: a durable rule and a fact change."""

    def __init__(self):
        self.calls = 0

    def create_message_sync(self, **kwargs):
        self.calls += 1
        from types import SimpleNamespace

        data = {
            "is_durable_rule": True,
            "rule": "Quote the standard day rate.",
            "why": "the edit set the rate",
            "is_fact_change": True,
            "category": "white-label",
            "key": "Day rate",
            "value": "800 EUR/day",
        }
        return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(input=data)])


CORRECTION = {
    "tool_name": "send_email",
    "proposed": {"to": "buyer@acme.test", "body": "Our rate is 700 EUR/day."},
    "edited": {"to": "buyer@acme.test", "body": "Our rate is 800 EUR/day."},
}


def test_correction_learning_submits_a_rule_and_a_fact_on_the_turns_handle(profile, monkeypatch):
    monkeypatch.setattr(cl, "_existing_rules", lambda owner_id: [])
    monkeypatch.setattr(cl, "_existing_fact_categories", lambda owner_id: [])
    seen = submitted(monkeypatch)
    before = preparation.status(OWNER_A)

    with revocable_turn() as handle:
        ids = cl.learn_from_corrections([CORRECTION], OWNER_A, client=_Judge())

    assert ids == []  # captured, nothing committed
    assert len(seen) == 2
    rule_event, fact_event = (e for e, _ in seen)
    assert rule_event.subject_hint.entity_type == "STYLE" and fact_event.subject_hint.entity_type == "FACT"
    for event in (rule_event, fact_event):
        assert event.cancellation is handle
        assert event.origin == INTERACTIVE and event.caller_class == OPERATOR_DELEGATED
        assert event.source_kind == "correction" and event.source_id.startswith("correction:")
        assert "TO: buyer@acme.test" in event.observation
        assert "USER ACTUALLY SENT:\nOur rate is 800 EUR/day." in event.observation
    assert rule_event.source_id == fact_event.source_id and rule_event.event_id != fact_event.event_id
    assert preparation.status(OWNER_A) == before


def test_a_corrections_envelope_is_never_mined_for_identity(profile, monkeypatch):
    from zylch.memory.mnemonic.candidates import identity_tokens, mines_observation
    from zylch.memory.mnemonic.wiring import typed_identifiers

    seen = submitted(monkeypatch)
    monkeypatch.setattr(cl, "_existing_rules", lambda owner_id: [])
    monkeypatch.setattr(cl, "_existing_fact_categories", lambda owner_id: [])
    cl.learn_from_corrections([CORRECTION], OWNER_A, client=_Judge())
    for event, _ in seen:
        assert mines_observation(event) is False
        assert identity_tokens(event) == set()
        assert typed_identifiers(event) == []


def test_the_learning_thread_is_spawned_inside_the_solve_turn():
    """Structural: the spawn sits inside the ``with revocable_turn()`` block of
    ``tasks_solve``, so the copied context carries the turn's handle."""
    source = Path(__file__).resolve().parents[2] / "zylch" / "rpc" / "methods.py"
    tree = ast.parse(source.read_text())

    def spawns(node):
        return any(
            isinstance(n, ast.Name) and n.id == "learn_from_corrections" for n in ast.walk(node)
        )

    inside = []
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Call)
            and getattr(item.context_expr.func, "id", "") == "revocable_turn"
            for item in node.items
        ):
            inside.append(spawns(node))
    assert True in inside, "the learning spawn is not inside a revocable_turn block"


def test_the_duplicate_and_shape_paths_stay_unpaid_through_the_tool(profile, monkeypatch):
    import asyncio

    from zylch.tools.create_memory_tool import CreateMemoryTool

    with_client(monkeypatch, client(create("STYLE", STYLE_HEADER + RULE, "account")))
    first = asyncio.run(CreateMemoryTool(owner_id=OWNER_A).execute(content=RULE, entry_type="behavioral_rule"))
    assert first.data["action"] == "created"
    seen = submitted(monkeypatch)
    again = asyncio.run(CreateMemoryTool(owner_id=OWNER_A).execute(content=RULE, entry_type="behavioral_rule"))
    assert again.data["action"] == "duplicate" and seen == []
