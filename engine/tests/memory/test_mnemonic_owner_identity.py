"""Whose memory work this process may submit: either identity of its own profile.

A profile the app creates names its account twice: ``OWNER_ID``, the Firebase
uid, which the budget and preparation key on, and ``EMAIL_ADDRESS``, which
``get_owner_id()`` answers and every trigger puts on its event. The harness
accepts an event, and a dispatch grant, owned by either. These cases run on that
production shape (uid ≠ email) with the owner each trigger's own resolver
answers: the consolidation pair of the known issue's reproduction, a mail
ingested with ``update.run``'s owner, a ``create_memory`` with ``chat.send``'s.
The Settings button and ``zylch memory-sweep`` are ``test_consolidation.py``'s.

Every other account is refused, another profile on the same company store
included, and so is a process that cannot say which account it is: an empty
identity is none, and the ``local-user`` stand-in ``get_owner_id()`` answers
for a profile without an email names no account. Only the provider transport
is scripted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

import pytest

from zylch.cli.utils import get_owner_id
from zylch.llm.budget import budget_snapshot
from zylch.llm.usage import call_site
from zylch.memory.blob_storage import BlobStorage
from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic import journal, pairs
from zylch.memory.mnemonic.authorization import (
    MnemonicAuthorizationError,
    MnemonicRefusal,
    dispatch_scope,
    issue_grant,
)
from zylch.memory.mnemonic.contracts import MemoryEvent
from zylch.services.preparation import preparation_run
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import MemoryOperation
from zylch.tools.base import ToolStatus
from zylch.tools.create_memory_tool import CreateMemoryTool
from zylch.tools.session_state import SessionState

from tests.memory.consolidation_env import merge_answer, person, seed
from tests.memory.mnemonic_env import (
    COMPANY_A,
    OWNER_A,
    OWNER_B,
    BagOfWordsEmbedder,
    boot,
    clear_process_state,
    client,
    stub_embedder,
    with_client,
)
from tests.workers.ingestion_env import (
    LUCA,
    blobs,
    children_of,
    create_decision,
    email_processed,
    extraction,
    make_worker,
    parent_of,
    run,
    seed_email,
)

EMAIL_A = f"{OWNER_A}@company.test"  # the EMAIL_ADDRESS the bench's profile states
EMAIL_B = f"{OWNER_B}@company.test"
SAID = "Ricorda che Luca Bianchi segue gli acquisti di Alpha."
ANY_ANSWER = json.dumps({"action": "SKIP", "reason": "unused"})


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    """Profile A as the app writes it: ``OWNER_ID`` the uid, ``EMAIL_ADDRESS`` the email."""
    from zylch.assistant.turn_context import set_turn_observation

    stub_embedder(monkeypatch, embedder)
    boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    set_turn_observation(SAID)
    yield tmp_path
    set_turn_observation("")
    dbm.dispose_engine()
    clear_process_state()


def triggers_owner(resolve) -> str:
    """The owner a trigger's own resolver answers, checked to be the production shape."""
    owner = resolve()
    assert owner == os.environ["EMAIL_ADDRESS"] == EMAIL_A
    assert owner != os.environ["OWNER_ID"]
    return owner


def event(owner: str, source_id: str = "turn-1") -> MemoryEvent:
    """One interactive memory event owned by ``owner``."""
    return MemoryEvent(
        owner_id=owner,
        company_key=COMPANY_A,
        caller_class=c.VERIFIED_HUMAN_CORRECTION,
        origin=c.INTERACTIVE,
        source_kind="chat",
        source_id=source_id,
        source_revision="rev-1",
        observation=SAID,
    )


def dispatch(llm, grant):
    """One paid call inside the grant's scope, where the grant is checked again."""
    with dispatch_scope(grant), call_site("memory.mnemonic"):
        return llm.create_message_sync(
            messages=[{"role": "user", "content": "decide"}], max_tokens=256
        )


def create_memory(owner: str, monkeypatch):
    """``create_memory`` as a chat turn runs it, owned by ``owner``, the role answering CREATE."""
    llm = with_client(monkeypatch, client(create_decision(LUCA, "PERSON")))
    tool = CreateMemoryTool(session_state=SessionState(owner_id=owner))
    return asyncio.run(tool.execute(content=LUCA, entry_type="entity_fact")), llm


def operations():
    """Every journal row, as (owner, state)."""
    with get_session() as session:
        return [(r.owner_id, r.state) for r in session.query(MemoryOperation).all()]


def operation(event_id: str):
    """One journal row, as (owner, state), or ``None``."""
    with get_session() as session:
        row = session.get(MemoryOperation, event_id)
        return (row.owner_id, row.state) if row else None


# ─── The production shape, through each trigger's owner ───────────────


def test_the_known_issue_reproduction_now_commits(profile, embedder):
    """A consolidation pair owned by ``get_owner_id()``, in an admitted item, merges."""
    owner = triggers_owner(get_owner_id)
    store = BlobStorage(get_session, embedder)
    keeper = seed(store, person(about="Purchasing at Alpha; handles every order."), owner=owner)
    donor = seed(store, person(about="Joins the Thursday sync."), owner=owner)
    pair_ = pairs.pair(
        store, owner, COMPANY_A, store.get_blob(keeper, owner), store.get_blob(donor, owner)
    )
    llm = client(merge_answer(store, keeper, donor, owner=owner)())
    item = pairs.PairItem(owner, lambda p: pairs.decide(p, client=llm))

    with preparation_run(owner):
        asyncio.run(item.run(pair_))

    result = item.results[pair_["id"]]
    assert result.outcome == c.COMMITTED, result.reason
    assert llm._client.messages.create.call_count == 1
    assert store.get_blob(keeper, owner) is not None and store.get_blob(donor, owner) is None


def test_a_mail_ingested_with_the_owner_update_run_passes_commits(profile):
    from zylch.rpc.methods import _owner_id  # what update.run hands the pipeline

    owner = triggers_owner(_owner_id)
    mail = seed_email(owner=owner)
    worker = make_worker([extraction(LUCA)], [create_decision(LUCA, "PERSON")], owner=owner)

    assert run(worker, "process_email", mail) is True

    parent = parent_of("mail-1")
    assert parent["state"] == journal.COMMITTED and parent["owner_id"] == owner
    kids = children_of(parent["event_id"]).values()
    assert [kid["state"] for kid in kids] == [journal.COMMITTED]
    assert email_processed("mail-1") and len(blobs()) == 1


def test_a_chat_memory_write_with_the_owner_chat_send_passes_commits(profile, monkeypatch):
    from zylch.rpc.methods import _owner_id  # what chat.send hands the chat service

    owner = triggers_owner(_owner_id)
    result, llm = create_memory(owner, monkeypatch)

    assert result.status == ToolStatus.SUCCESS, result.error
    assert llm._client.messages.create.call_count == 1
    assert operations() == [(owner, journal.COMMITTED)] and len(blobs()) == 1


# ─── Either identity, and no other ────────────────────────────────────


@pytest.mark.parametrize("identity", ["OWNER_ID", "EMAIL_ADDRESS"])
def test_either_identity_of_the_profile_passes_the_request_and_the_dispatch(profile, identity):
    llm = client(ANY_ANSWER)
    grant = issue_grant(event(os.environ[identity]))  # the request is authorized inside

    dispatch(llm, grant)

    assert llm._client.messages.create.call_count == 1


def test_another_profile_on_the_same_store_may_not_submit_as_this_one(profile, monkeypatch):
    """B boots on A's company store; there, A's uid and A's email are another account."""
    written, _ = create_memory(EMAIL_A, monkeypatch)
    assert written.status == ToolStatus.SUCCESS, written.error
    before = blobs()

    boot(monkeypatch, profile, OWNER_B, COMPANY_A)
    assert (os.environ["OWNER_ID"], os.environ["EMAIL_ADDRESS"]) == (OWNER_B, EMAIL_B)
    for foreign in (OWNER_A, EMAIL_A):
        refused, llm = create_memory(foreign, monkeypatch)
        assert refused.status == ToolStatus.ERROR, refused
        assert refused.data["action"] == c.REVIEW_NEEDED
        assert "does not match the event owner" in refused.error
        assert llm._client.messages.create.call_count == 0
        # As every refusal is, it is kept as a review under the refused event's id.
        assert operation(refused.data["event_id"]) == (foreign, journal.REVIEW)
    assert blobs() == before

    own, llm = create_memory(EMAIL_B, monkeypatch)
    assert own.status == ToolStatus.SUCCESS, own.error
    assert llm._client.messages.create.call_count == 1


def test_a_grant_stops_when_the_process_acts_as_another_profile(profile, monkeypatch):
    grants = [issue_grant(event(OWNER_A, "turn-uid")), issue_grant(event(EMAIL_A, "turn-email"))]
    monkeypatch.setenv("OWNER_ID", OWNER_B)
    monkeypatch.setenv("EMAIL_ADDRESS", EMAIL_B)

    for grant in grants:
        llm = client(ANY_ANSWER)
        with pytest.raises(MnemonicAuthorizationError, match="belongs to another account"):
            dispatch(llm, grant)
        assert llm._client.messages.create.call_count == 0
    assert budget_snapshot(OWNER_A)["reserved_usd"] == 0
    assert budget_snapshot(OWNER_B)["reserved_usd"] == 0


# ─── A process that cannot say which account it is ────────────────────


def test_a_profile_that_states_neither_identity_is_refused(profile, monkeypatch):
    grant = issue_grant(event(OWNER_A))  # minted while the profile still names itself
    monkeypatch.delenv("OWNER_ID")
    monkeypatch.delenv("EMAIL_ADDRESS")
    assert get_owner_id() == "local-user"

    with pytest.raises(MnemonicRefusal, match="cannot say which account"):
        issue_grant(event(get_owner_id(), "turn-2"))
    with pytest.raises(MnemonicAuthorizationError, match="cannot say which account"):
        dispatch(client(ANY_ANSWER), grant)


def test_an_empty_identity_is_no_identity(profile, monkeypatch):
    """No event can be owned by ``""``, so an empty identity shows as "cannot say"."""
    monkeypatch.setenv("OWNER_ID", "")
    monkeypatch.setenv("EMAIL_ADDRESS", "")

    with pytest.raises(MnemonicRefusal, match="cannot say which account"):
        issue_grant(event(OWNER_A))


def test_the_local_user_stand_in_names_no_account(profile, monkeypatch):
    """A profile with a uid and no email: the stand-in its triggers would pass is refused."""
    monkeypatch.delenv("EMAIL_ADDRESS")
    assert get_owner_id() == "local-user"

    with pytest.raises(MnemonicRefusal, match="does not match the event owner"):
        issue_grant(event(get_owner_id()))
    issue_grant(event(OWNER_A, "turn-2"))  # the uid alone still names the account


def test_an_email_that_cannot_be_resolved_leaves_the_uid(profile, monkeypatch, caplog):
    def unresolvable():
        raise RuntimeError("the profile cannot be read")

    monkeypatch.setattr("zylch.cli.utils.get_owner_id", unresolvable)

    with caplog.at_level(logging.WARNING, logger="zylch.memory.mnemonic.authorization"):
        issue_grant(event(OWNER_A))
        with pytest.raises(MnemonicRefusal, match="does not match the event owner"):
            issue_grant(event(EMAIL_A, "turn-2"))

    assert (
        "[mnemonic] this profile's email identity cannot be resolved: the profile cannot be read"
        in caplog.messages
    )
