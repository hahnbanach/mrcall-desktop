"""``/memory store`` is one memory event on the chat turn, answered by its outcome.

Against the real profile (``tests/memory/mnemonic_env.py``): the real verb, the
real harness, the real databases, the memory role scripted at the transport.
What these hold is that the verb submits an explicit interactive event whose
observation is what the human said, reads the committed row back before it
answers, lets the role change memory it was shown and records that as a
departure from the create that was asked for, refuses that change under
``--force``, and asks no model and writes nothing on a read-only turn.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from zylch.memory.blob_versions import list_versions
from zylch.memory.mnemonic.approval import CHANGED_ACTION
from zylch.memory.mnemonic.contracts import CREATE, INTERACTIVE, OPERATOR_DELEGATED, UPDATE
from zylch.services.command_handlers import handle_memory
from zylch.services.request_policy import policy_scope
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

ACME = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Acme Srl\n"
    "Email: info@acme.test\n#ABOUT\nIndustrial supplier in Milan."
)
ACME_MOVED = ACME.replace("Milan", "Turin")
SAID = "ricorda che Acme Srl si è trasferita a Torino"
TYPED = "Acme Srl, industrial supplier, has moved to Turin"


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    from zylch.assistant.turn_context import set_turn_observation

    stub_embedder(monkeypatch, embedder)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    set_turn_observation(SAID)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def seed(content, embedder):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(
        owner_id=OWNER_A, namespace=f"user:{COMPANY_A}", content=content, event_description="seed"
    )
    return blob["id"], storage.get_blob(blob["id"], OWNER_A)["updated_at"]


def blobs():
    with get_session() as session:
        return {b.id: b.content for b in session.query(Blob).all()}


def versions(blob_id):
    with get_session() as session:
        return [v.content for v in list_versions(session, blob_id)]


def rows():
    with get_session() as session:
        return [r.to_dict() for r in session.query(MemoryOperation).all()]


def decision(content, action, target=None, version=None):
    body = {
        "action": action,
        "entity_type": "COMPANY",
        "scope": "entity",
        "content": content,
        "reason": "the same subject" if target else "no visible candidate describes this subject",
    }
    if target:
        body["write_set"] = [{"blob_id": target, "expected_version": version, "role": "target"}]
    return json.dumps(body)


def store(*args):
    return asyncio.run(handle_memory(list(args), None, OWNER_A))


def submitted(monkeypatch, llm):
    """Route the verb through ``llm`` and record what it handed to ``submit``.

    The journal prunes a terminal row down to its receipt, so the event's
    flags are proven here, on the call, and on what the role was sent.
    """
    from zylch.memory import mnemonic as pkg
    from zylch.memory.mnemonic import commit as commit_mod

    routed = with_client(monkeypatch, llm) and pkg.submit
    seen = []

    def recording(event, **kwargs):
        seen.append((event, kwargs))
        return routed(event, **kwargs)

    recording._real_submit = routed._real_submit
    monkeypatch.setattr(pkg, "submit", recording)
    monkeypatch.setattr(commit_mod, "submit", recording)
    return seen


def role_saw(llm):
    """The text of every message the role was sent, on its last call."""
    sent = llm._client.messages.create.call_args.kwargs["messages"]
    return " ".join(str(m.get("content")) for m in sent)


def calls(llm):
    return llm._client.messages.create.call_count


# ─── What the verb submits ────────────────────────────────────────────


def test_store_submits_an_explicit_interactive_event_and_reads_back(profile, monkeypatch):
    llm = client(decision(ACME, CREATE))
    calls_made = submitted(monkeypatch, llm)

    answer = store("store", TYPED)

    ((blob_id, content),) = blobs().items()
    assert content == ACME
    assert "Memory stored" in answer and blob_id in answer and ACME in answer, answer
    ((event, kwargs),) = calls_made
    assert event.explicit_request is True
    assert event.origin == INTERACTIVE and event.caller_class == OPERATOR_DELEGATED
    assert event.source_kind == "chat" and event.source_id.startswith("turn:")
    assert event.observation == SAID and event.suggestion == TYPED
    assert kwargs["allow_actions"] == (CREATE, UPDATE) and kwargs["requested"].action == CREATE
    (row,) = rows()
    assert row["state"] == "committed" and row["event_id"] == event.event_id
    assert row["origin"] == INTERACTIVE and row["caller_class"] == OPERATOR_DELEGATED
    assert row["source_ref"] == event.source_ref and row["departure"] is None
    seen = role_saw(llm)
    assert SAID in seen and TYPED in seen and '"explicit_request": true' in seen


def test_without_a_chat_turn_the_typed_content_is_the_observation(profile, monkeypatch):
    from zylch.assistant.turn_context import set_turn_observation

    set_turn_observation("")
    llm = client(decision(ACME, CREATE))
    calls_made = submitted(monkeypatch, llm)

    answer = store("store", TYPED)

    assert "Memory stored" in answer, answer
    ((event, _kwargs),) = calls_made
    assert event.observation == TYPED and event.suggestion == TYPED
    assert [r["state"] for r in rows()] == ["committed"]
    assert TYPED in role_saw(llm)


# ─── The role may change what it was shown; --force forbids it ────────


def test_the_role_may_change_memory_it_was_shown_and_the_departure_is_recorded(
    profile, monkeypatch, embedder
):
    target, version = seed(ACME, embedder)
    with_client(monkeypatch, client(decision(ACME_MOVED, UPDATE, target, version)))

    answer = store("store", TYPED)

    assert "Memory updated" in answer and target in answer and ACME_MOVED in answer, answer
    assert blobs() == {target: ACME_MOVED}
    assert versions(target) == [ACME]  # the retaining rewrite, never an overwrite
    (row,) = rows()
    assert row["state"] == "committed"
    assert CHANGED_ACTION in row["departure"]["flags"]
    assert row["departure"]["requested"]["action"] == CREATE
    assert row["departure"]["proposed"]["action"] == UPDATE


def test_force_refuses_a_proposal_to_change_existing_memory(profile, monkeypatch, embedder):
    target, version = seed(ACME, embedder)
    llm = client(decision(ACME_MOVED, UPDATE, target, version))
    calls_made = submitted(monkeypatch, llm)

    answer = store("store", "--force", TYPED)

    ((_event, kwargs),) = calls_made
    assert kwargs["allow_actions"] == (CREATE,)
    assert "Not stored" in answer and "CREATE" in answer, answer
    assert blobs() == {target: ACME} and versions(target) == []
    (row,) = rows()
    assert row["state"] == "review" and "UPDATE" in row["result"]["reason"]
    assert calls(llm) == 1  # asked once, refused after the answer, not re-asked


def test_force_still_stores_new_memory(profile, monkeypatch):
    with_client(monkeypatch, client(decision(ACME, CREATE)))

    answer = store("store", "--force", TYPED)

    ((blob_id, content),) = blobs().items()
    assert content == ACME and "Memory stored" in answer and blob_id in answer, answer


# ─── A read-only turn ─────────────────────────────────────────────────


def test_a_read_only_turn_reaching_the_verb_directly_writes_nothing(profile, monkeypatch):
    """Routing refuses a read-only ``/memory store`` before the handler
    (``tests/rpc/test_memory_readonly.py``); reached directly, the harness
    refuses it again before any model work."""
    llm = with_client(monkeypatch, client(decision(ACME, CREATE)))

    with policy_scope("read_only"):
        answer = store("store", TYPED)

    assert "Not stored" in answer, answer
    assert calls(llm) == 0 and blobs() == {}
    assert [r["state"] for r in rows()] == ["review"]
