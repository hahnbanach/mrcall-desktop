"""Binding an acceptance to the change it accepts.

The question every test here asks is the same one: can this answer authorize
*this* write? Not "did somebody say yes" — three mechanisms in production say
yes without a human reading anything, and they all say it by tool name:

- ``cs --allow update_memory`` answers every ``chat.pending_approval`` for that
  name (``cs-kernel/cs/rpc.py``: ``mode = "once" if tool in allow ...``);
- the engine remembers ``chat.approve(mode="session")`` per conversation and
  tool name and skips the notification entirely;
- the Desktop card offers "Allow for session" for non-send tools.

A new tool name defeats none of them, because all three key on whatever name is
used. So the acceptance is a single-use nonce plus the digest of the proposal the
surface was shown, and every one of those mechanisms fails it by construction:
they can only answer ``(True, None)``.

Everything runs against real split profile and company databases, the real
``LLMClient`` with only the provider transport replaced, and the real commit — so
a refusal that is asserted to write nothing is asserted against actual rows.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from zylch.memory.mnemonic import journal
from zylch.memory.mnemonic.approval import (
    AUTO_APPROVED,
    describe,
    CHANGED_SCOPE,
    CHANGED_SUBJECT,
    DESTRUCTIVE_EFFECTS,
    EDITED,
    NO_CHANNEL,
    STALE_ACCEPTANCE,
    UNNAMED_SUBJECT,
    Acceptance,
    RequestedWrite,
    final_mutation,
    flags_for,
    install_channel,
    verify,
)
from zylch.memory.mnemonic.contracts import (
    CREATE,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    MemoryEvent,
)
from zylch.memory.mnemonic.proposals import Proposal, WriteTarget
from zylch.storage import database as dbm
from zylch.storage.database import get_session
from zylch.storage.models import Blob

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
BETA = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n"
    "Email: info@beta.test\n#ABOUT\nPackaging supplier in Turin."
)
# What the human said this turn: it is about Beta. Every end-to-end test below
# has the model name ACME's blob anyway — the wrong-id case these adapters exist
# for — so the role's own answer is about a memory the caller did not choose.
SAID = "L'indirizzo ordini di Beta Spa ora è orders@beta.test, non info@beta.test"
BETA_CORRECTED = BETA.replace("info@beta.test", "orders@beta.test")


# ─── Wiring ───────────────────────────────────────────────────────────


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def supervised(tmp_path, monkeypatch, embedder):
    """A real profile with the milestone 4 slice on, and the turn already set."""
    from zylch.assistant.turn_context import set_turn_observation

    stub_embedder(monkeypatch, embedder)
    monkeypatch.setenv("MNEMONIC_WRITE_PATH", "supervised")
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    set_turn_observation(SAID)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def seed(content, namespace=f"user:{COMPANY_A}", embedder=None):
    """One committed blob, written the ordinary way, to be a target."""
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(
        owner_id=OWNER_A,
        namespace=namespace,
        content=content,
        event_description="seed",
    )
    return blob["id"], storage.get_blob(blob["id"], OWNER_A)["updated_at"]


def blobs():
    with get_session() as session:
        return {b.id: b.content for b in session.query(Blob).all()}


def version_of(blob_id, embedder):
    """The blob's current CAS version, as the storage layer states it.

    Read through ``get_blob`` and not off the ORM column: the version is a
    string the storage boundary compares, and ``str(datetime)`` is not it — a
    test that spelled it itself would get a CAS conflict and blame the gate.
    """
    from zylch.memory.blob_storage import BlobStorage

    return BlobStorage(get_session, embedder).get_blob(blob_id, OWNER_A)["updated_at"]


def update_decision(blob_id, version, content=BETA_CORRECTED):
    return json.dumps(
        {
            "action": UPDATE,
            "entity_type": "COMPANY",
            "scope": "entity",
            "content": content,
            "write_set": [{"blob_id": blob_id, "expected_version": version, "role": "target"}],
            "reason": "the ordering address replaces the old one",
        }
    )


class Surface:
    """A recording approval channel with a configurable answer.

    ``answer`` receives the card and returns whatever a real surface would echo
    back, so a test can be exactly as honest or as lazy as the surface it stands
    for.
    """

    def __init__(self, answer):
        self._answer = answer
        self.cards = []

    def request(self, mutation):
        card = mutation.as_card()
        self.cards.append(card)
        return self._answer(card)


def honest(card):
    """What a surface that actually showed a human the change echoes back."""
    from zylch.services.mnemonic_approval import acceptance_payload

    return Acceptance.from_payload(acceptance_payload(card))


def standing_grant(_card):
    """What every name-keyed auto-approver can produce: yes, and nothing else."""
    return Acceptance.from_payload(None)


def run_update(monkeypatch, *, named, target, version, channel, content=BETA_CORRECTED):
    """The real ``update_memory`` tool through the real role, under one channel.

    ``named`` is the blob the model passed as ``blob_id``; ``target`` is the one
    the role decides to write. Exactly one mocked response, so a validator
    re-ask shows up as a failure here rather than passing on the second try.
    """
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    with_client(monkeypatch, client(update_decision(target, version, content)))
    with install_channel(channel):
        return asyncio.run(
            UpdateMemoryTool(owner_id=OWNER_A).execute(
                blob_id=named, new_content=content, entry_type="entity_fact"
            )
        )


# ─── What counts as a change at all ───────────────────────────────────


def test_a_faithful_proposal_is_not_flagged():
    """The initial tool-call approval already showed the human this write.

    A second card for a proposal that does exactly what was asked would train
    the human to click through, which is how a confirmation stops being one.
    """
    requested = RequestedWrite(action=UPDATE, blob_id="blob-1", subject_is_authoritative=True)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-1", expected_version="v1"),),
    )
    assert flags_for(requested, proposal) == ()


def test_a_different_target_is_a_changed_subject():
    requested = RequestedWrite(action=UPDATE, blob_id="blob-1", subject_is_authoritative=True)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-OTHER", expected_version="v1"),),
    )
    assert CHANGED_SUBJECT in flags_for(requested, proposal)


def test_a_create_that_comes_back_an_update_is_flagged():
    """``create_memory`` asked for a new memory; this changes an existing one."""
    requested = RequestedWrite(action=CREATE, subject_is_authoritative=False)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-1", expected_version="v1"),),
    )
    flags = flags_for(requested, proposal)
    assert "changed_action" in flags


def test_an_entity_request_proposed_as_a_company_fact_is_flagged():
    """entity → FACT moves the memory out of the family the caller expected."""
    requested = RequestedWrite(action=CREATE, entity_type="COMPANY")
    proposal = Proposal(action=CREATE, entity_type="FACT", scope="company", content="x")
    assert CHANGED_SCOPE in flags_for(requested, proposal)


def test_an_update_nobody_named_a_target_for_is_always_flagged():
    """The solve path names no blob, so the row was chosen for it.

    This is the defect the conversion exists to remove: a query is a retrieval
    hint, and a write picked from a similarity ranking is a write no human saw.
    """
    requested = RequestedWrite(action=UPDATE, subject_is_authoritative=False)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-1", expected_version="v1"),),
    )
    assert UNNAMED_SUBJECT in flags_for(requested, proposal)


def test_an_absorbing_effect_is_flagged_even_on_a_faithful_target():
    requested = RequestedWrite(action=UPDATE, blob_id="blob-1", subject_is_authoritative=True)
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-1", expected_version="v1"),),
        declared_effects=("alias:blob-9->blob-1",),
    )
    assert DESTRUCTIVE_EFFECTS in flags_for(requested, proposal)


def test_an_adapter_that_declares_nothing_is_treated_as_having_changed_everything():
    """A caller that did not say what it asked for cannot be taken on trust.

    `submit` without `requested` resolves in the direction that asks a human,
    because the alternative is a converted writer silently skipping the gate by
    omitting an argument.
    """
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-1", expected_version="v1"),),
    )
    assert flags_for(RequestedWrite(action=proposal.action), proposal) != ()


# ─── What counts as an acceptance ─────────────────────────────────────


def mutation_for(nonce_source=None):
    event = MemoryEvent(
        owner_id=OWNER_A,
        company_key=COMPANY_A,
        caller_class=OPERATOR_DELEGATED,
        origin=INTERACTIVE,
        source_kind="chat",
        source_id="turn:1",
        source_revision="rev-1",
        observation="orders@acme.test è l'indirizzo giusto",
    )
    proposal = Proposal(
        action=UPDATE,
        entity_type="COMPANY",
        scope="entity",
        content=ACME,
        write_set=(WriteTarget(blob_id="blob-OTHER", expected_version="v1"),),
    )
    requested = RequestedWrite(action=UPDATE, blob_id="blob-1", subject_is_authoritative=True)
    return final_mutation(event, proposal, requested, (CHANGED_SUBJECT,))


def test_a_bare_yes_is_read_as_a_standing_grant_not_an_acceptance():
    mutation = mutation_for()
    assert verify(Acceptance.from_payload(None), mutation) == AUTO_APPROVED


def test_an_acceptance_naming_this_exact_change_verifies():
    mutation = mutation_for()
    assert verify(honest(mutation.as_card()), mutation) is None


def test_an_acceptance_naming_another_proposal_is_stale():
    """A digest that is not this one cannot have been given for this change."""
    mutation = mutation_for()
    other = Acceptance(accepted=True, nonce=mutation.nonce, proposal_digest="a" * 64)
    assert verify(other, mutation) == STALE_ACCEPTANCE


def test_an_acceptance_carrying_another_cards_nonce_is_stale():
    first, second = mutation_for(), mutation_for()
    replayed = Acceptance(
        accepted=True,
        nonce=first.nonce,
        proposal_digest=second.proposal_digest,
    )
    assert verify(replayed, second) == STALE_ACCEPTANCE


def test_an_edited_card_is_not_an_acceptance_of_what_was_decided():
    mutation = mutation_for()
    edited = Acceptance(
        accepted=True,
        nonce=mutation.nonce,
        proposal_digest=mutation.proposal_digest,
        edited=True,
    )
    assert verify(edited, mutation) == EDITED


def test_an_uncomparable_acceptance_is_a_refusal_and_never_an_exception():
    """The values come from a client, so they can be any string at all.

    ``secrets.compare_digest`` raises ``TypeError`` on a non-ASCII string. Letting
    that escape turns a malformed acceptance into a ``retryable_failure`` and a
    ``failed`` journal row — "try again" about something that can never succeed.
    """
    mutation = mutation_for()
    for value in ("nonce-è-latin1", "🔑", "\u00ff" * 8):
        answer = Acceptance(accepted=True, nonce=value, proposal_digest=mutation.proposal_digest)
        assert verify(answer, mutation) == STALE_ACCEPTANCE, value
        digest_side = Acceptance(accepted=True, nonce=mutation.nonce, proposal_digest=value)
        assert verify(digest_side, mutation) == STALE_ACCEPTANCE, value


def test_no_channel_at_all_is_a_refusal_with_its_own_reason():
    assert verify(None, mutation_for()) == NO_CHANNEL


def test_the_proposal_digest_moves_with_the_version_it_read():
    """So an acceptance cannot survive a CAS re-read onto a newer row.

    The human accepted changing version 1. Version 2 is a different change, and
    binding to the digest is what makes that automatic rather than remembered.
    """
    from zylch.memory.mnemonic.digests import proposal_digest

    def at(version):
        return Proposal(
            action=UPDATE,
            entity_type="COMPANY",
            scope="entity",
            content=ACME,
            write_set=(WriteTarget(blob_id="blob-1", expected_version=version),),
        )

    assert proposal_digest(at("v1")) != proposal_digest(at("v2"))


# ─── The gate, end to end, against real rows ──────────────────────────


def test_a_changed_subject_is_written_only_after_an_honest_acceptance(
    supervised, monkeypatch, embedder
):
    """The model named the wrong blob; the role corrected it; the human confirmed.

    This is the defect the harness exists for, with the gate doing its job: the
    write lands on the memory the turn was actually about, and only after a human
    saw that it was a different one.
    """
    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    surface = Surface(honest)

    result = run_update(monkeypatch, named=named, target=target, version=version, channel=surface)

    assert len(surface.cards) == 1
    card = surface.cards[0]
    assert card["action"] == UPDATE
    assert card["write_set"][0]["blob_id"] == target
    assert card["requested_blob_id"] == named
    assert CHANGED_SUBJECT in card["flags"]
    # The complete prose, not a preview of it: the human is accepting the words.
    assert card["content"] == BETA_CORRECTED
    # And the observation, so they can see what the change is being read from.
    assert card["observation"] == SAID

    assert result.status.value == "success", result.error
    assert "orders@beta.test" in blobs()[target]
    assert blobs()[named] == ACME


def test_a_headless_caller_returns_review_and_writes_nothing(supervised, monkeypatch, embedder):
    """No channel means nobody to ask, and nobody to ask means refuse."""
    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    before = blobs()

    result = run_update(monkeypatch, named=named, target=target, version=version, channel=None)

    assert result.status.value == "error"
    assert result.error == NO_CHANNEL
    assert blobs() == before


def test_a_standing_grant_cannot_accept_a_changed_mutation(supervised, monkeypatch, embedder):
    """This is the kernel's ``--allow`` and the engine's session grant, exactly.

    Both answer ``(True, None)``. Neither read the card, so neither can echo the
    nonce, so the write does not happen — without the harness having to know
    which surface it was talking to.
    """
    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    before = blobs()
    surface = Surface(standing_grant)

    result = run_update(monkeypatch, named=named, target=target, version=version, channel=surface)

    assert surface.cards, "the card is still presented — it is the answer that fails"
    assert result.status.value == "error"
    assert result.error == AUTO_APPROVED
    assert blobs() == before


def test_a_second_auto_approved_notification_cannot_reuse_the_first_acceptance(
    supervised, monkeypatch, embedder
):
    """A surface that replays the last answer it gave is refused.

    The nonce is consumed on first use, so an auto-approver that remembers one
    honest acceptance and echoes it at the next card gets nowhere.
    """
    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    remembered = {}

    def replaying(card):
        from zylch.services.mnemonic_approval import acceptance_payload

        if not remembered:
            remembered.update(acceptance_payload(card))
        return Acceptance.from_payload(dict(remembered))

    surface = Surface(replaying)
    first = run_update(monkeypatch, named=named, target=target, version=version, channel=surface)
    assert first.status.value == "success", first.error

    after_first = blobs()
    second = run_update(
        monkeypatch,
        named=named,
        target=target,
        version=version_of(target, embedder),
        channel=surface,
        content=BETA_CORRECTED.replace("Packaging", "Industrial packaging"),
    )

    assert second.status.value == "error"
    assert second.error == STALE_ACCEPTANCE
    assert blobs() == after_first


def test_a_stale_version_is_refused_before_anybody_is_asked(supervised, monkeypatch, embedder):
    """A proposal naming a version the row has moved past never reaches a human.

    The validator holds the rule "UPDATE takes its target at the exact version it
    was read at", so a stale proposal is re-asked, not shown. Bothering a human
    with a change that cannot be applied would teach them the card is noise.
    """
    from zylch.memory.blob_storage import BlobStorage
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    named, _ = seed(ACME, embedder=embedder)
    target, stale = seed(BETA, embedder=embedder)
    BlobStorage(get_session, embedder).update_blob(
        blob_id=target,
        owner_id=OWNER_A,
        content=BETA + "\n- another writer got here first",
        event_description="concurrent write",
    )
    surface = Surface(honest)

    with_client(monkeypatch, client(*[update_decision(target, stale)] * 3))
    with install_channel(surface):
        result = asyncio.run(
            UpdateMemoryTool(owner_id=OWNER_A).execute(
                blob_id=named, new_content=BETA_CORRECTED, entry_type="entity_fact"
            )
        )

    assert surface.cards == []
    assert result.status.value == "error"
    assert "another writer got here first" in blobs()[target]
    assert "orders@beta.test" not in blobs()[target]


def test_a_cas_conflict_asks_again_rather_than_reusing_the_first_acceptance(
    supervised, monkeypatch, embedder
):
    """The human accepted changing the row as it stood. The row then moved.

    A genuine race between the validator's read and the transaction's re-read
    cannot be scheduled from inside one process, so the conflict is injected at
    the transaction boundary — the behaviour under test is the decision loop's,
    not SQLite's. What must hold: the second round issues its own card with its
    own nonce, and the acceptance given for the first proposal authorizes
    nothing.
    """
    from zylch.memory.commit_permit import ConflictError
    from zylch.memory.mnemonic import commit as commit_mod
    from zylch.tools.update_memory_tool import UpdateMemoryTool

    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    surface = Surface(honest)

    real_commit = commit_mod._commit
    attempts = {"n": 0}

    def conflicting_once(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConflictError("the row moved between the read and the write")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(commit_mod, "_commit", conflicting_once)
    with_client(monkeypatch, client(*[update_decision(target, version)] * 2))
    with install_channel(surface):
        result = asyncio.run(
            UpdateMemoryTool(owner_id=OWNER_A).execute(
                blob_id=named, new_content=BETA_CORRECTED, entry_type="entity_fact"
            )
        )

    assert attempts["n"] == 2
    assert len(surface.cards) == 2
    # Two rounds, two nonces. Neither answer could have served the other round.
    assert len({card["acceptance_nonce"] for card in surface.cards}) == 2
    assert result.status.value == "success", result.error
    assert "orders@beta.test" in blobs()[target]


def test_a_declined_card_writes_nothing(supervised, monkeypatch, embedder):
    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    before = blobs()
    surface = Surface(lambda _card: Acceptance.declined("the human said no"))

    result = run_update(monkeypatch, named=named, target=target, version=version, channel=surface)

    assert result.status.value == "error"
    assert result.error == "the human said no"
    assert blobs() == before


def test_a_channel_that_raises_is_a_refusal(supervised, monkeypatch, embedder):
    """A gate that cannot reach its human has not been answered."""
    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    before = blobs()

    def explode(_card):
        raise RuntimeError("the websocket died")

    result = run_update(
        monkeypatch,
        named=named,
        target=target,
        version=version,
        channel=Surface(explode),
    )

    assert result.status.value == "error"
    assert "the websocket died" in result.error
    assert blobs() == before


def test_a_refused_mutation_is_recorded_as_a_review_not_a_failure(
    supervised, monkeypatch, embedder
):
    """The journal has to be able to say what happened to the event."""
    from zylch.storage.models import MemoryOperation

    named, _ = seed(ACME, embedder=embedder)
    target, version = seed(BETA, embedder=embedder)
    run_update(
        monkeypatch,
        named=named,
        target=target,
        version=version,
        channel=Surface(standing_grant),
    )
    with get_session() as session:
        assert [row.state for row in session.query(MemoryOperation).all()] == [journal.REVIEW]


# ─── The bridge ───────────────────────────────────────────────────────


def test_asked_from_the_event_loop_the_bridge_refuses_instead_of_deadlocking():
    """Blocking the loop would stop the loop that must deliver the answer."""
    from zylch.services.mnemonic_approval import ON_LOOP_THREAD, CallbackChannel

    async def never_called(*_a, **_k):  # pragma: no cover - must not run
        raise AssertionError("the callback must not be awaited from the loop thread")

    async def on_the_loop():
        channel = CallbackChannel(never_called)
        return channel.request(mutation_for())

    answer = asyncio.run(on_the_loop())
    assert answer.accepted is False
    assert answer.reason == ON_LOOP_THREAD


def test_the_bridge_reads_the_acceptance_out_of_what_the_surface_echoed():
    """And a surface that echoed nothing produces an acceptance with nothing."""
    from zylch.services.mnemonic_approval import CallbackChannel

    seen = {}

    async def callback(use_id, tool_name, card):
        from zylch.services.mnemonic_approval import acceptance_payload

        seen["tool_name"] = tool_name
        seen["card"] = card
        return (True, acceptance_payload(card))

    async def drive():
        loop = asyncio.get_running_loop()
        channel = CallbackChannel(callback, loop=loop)
        mutation = mutation_for()
        answer = await asyncio.to_thread(channel.request, mutation)
        return mutation, answer

    mutation, answer = asyncio.run(drive())
    assert seen["tool_name"] == "confirm_memory_write"
    # The card carries the complete change AND a rendered preview for surfaces
    # that can only show a string.
    assert seen["card"]["content"]
    assert "confirm the final change" in seen["card"]["preview"]
    assert verify(answer, mutation) is None


def test_an_unanswered_card_expires_into_a_refusal():
    """A human who never answers has not accepted.

    The plan lists expiry beside denial and cancellation, and the failure to
    avoid is a decision that sits on a worker thread forever holding a lease and
    a grant. The timeout is the same 600s the send path waits, shortened here.
    """
    from zylch.services.mnemonic_approval import TIMED_OUT, CallbackChannel

    async def never_answers(*_a, **_k):
        await asyncio.Event().wait()

    async def drive():
        loop = asyncio.get_running_loop()
        channel = CallbackChannel(never_answers, loop=loop, timeout=0.3)
        return await asyncio.to_thread(channel.request, mutation_for())

    answer = asyncio.run(drive())
    assert answer.accepted is False
    assert answer.reason == TIMED_OUT
    # And it is a refusal the gate reports as such, not a silent proceed.
    assert verify(answer, mutation_for()) == TIMED_OUT


def test_a_cancelled_turn_refuses_the_acceptance_rather_than_waiting():
    from zylch.services.mnemonic_approval import TURN_GONE, CallbackChannel

    async def never_answers(*_a, **_k):
        await asyncio.Event().wait()

    async def drive():
        loop = asyncio.get_running_loop()
        channel = CallbackChannel(never_answers, loop=loop)
        asking = asyncio.get_running_loop().run_in_executor(None, channel.request, mutation_for())
        await asyncio.sleep(0.05)
        # Every pending acceptance dies with the loop's turn; simulate the
        # cancellation the RPC layer performs on its pending futures.
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        return await asking

    answer = asyncio.run(drive())
    assert answer.accepted is False
    assert answer.reason in (TURN_GONE, "")


# ─── The engine's own shortcuts, guarded at the source ────────────────


def test_the_notification_preview_shows_the_change_not_a_json_dump():
    """It is the first thing a human sees, and it used to include the nonce."""
    from zylch.services.mnemonic_approval import CONFIRM_MEMORY_WRITE
    from zylch.services.task_executor import format_approval_preview

    mutation = mutation_for()
    card = mutation.as_card()
    card["preview"] = describe(mutation)

    shown = format_approval_preview(CONFIRM_MEMORY_WRITE, card)
    assert "confirm the final change" in shown
    assert mutation.content in shown
    assert mutation.nonce not in shown
    assert not shown.lstrip().startswith("{")


def test_the_engine_never_session_grants_a_final_memory_mutation():
    from zylch.rpc import methods
    from zylch.services.mnemonic_approval import CONFIRM_MEMORY_WRITE

    methods._session_auto_approvals["conv-1"] = {CONFIRM_MEMORY_WRITE, "run_python"}
    assert methods._should_auto_approve("conv-1", CONFIRM_MEMORY_WRITE) is False
    # The guard is about this one name, not about disabling the feature.
    assert methods._should_auto_approve("conv-1", "run_python") is True
    methods._session_auto_approvals.pop("conv-1", None)


def test_chat_approve_refuses_to_register_a_session_grant_for_one():
    from zylch.rpc import methods
    from zylch.services.mnemonic_approval import CONFIRM_MEMORY_WRITE

    async def drive():
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        methods._pending_approvals["use-1"] = fut
        methods._approval_meta["use-1"] = ("conv-2", CONFIRM_MEMORY_WRITE)
        await methods.chat_approve({"tool_use_id": "use-1", "mode": "session"}, lambda *_a: None)
        return await fut

    approved, _edited = asyncio.run(drive())
    # Honoured for this one call...
    assert approved is True
    # ...and remembered for none.
    assert CONFIRM_MEMORY_WRITE not in methods._session_auto_approvals.get("conv-2", set())
    methods._session_auto_approvals.pop("conv-2", None)
