"""The solve loop's memory write, and the authority it is not allowed to claim.

``_update_memory`` used to take a ``query``, search with ``limit=1``, and
overwrite whatever came back first. So the tool picked the victim from a
similarity ranking, and the text the model passed became the stored bytes. This
suite is about the three separate claims that path made and no longer does:

1. **The query does not select the target.** It is a retrieval hint, and because
   the caller names no blob, every proposal writes to a subject the caller did
   not choose — which is what puts the change in front of a human.
2. **A task's own text is not an instruction.** Extracted content is an
   observation; only what the human typed into the solve box this run is theirs.
   Calling the same tool does not promote one into the other.
3. **An interactive correction is not preparation work.** It rides the caller's
   turn and leaves bounded preparation exactly as it found it.

The executor tests run the real thing: the real ``TaskExecutor``, the real
``LLMClient`` and the real reservation ledger, with only the provider transport
replaced. Nothing here stubs ``check_dispatch``, supplies a preparation context
or fakes a reservation — those are the guards under test.
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from zylch.memory.mnemonic.contracts import (
    AUTOMATIC_OBSERVATION,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    VERIFIED_HUMAN_CORRECTION,
)
from zylch.services import solve_memory
from zylch.services.solve_context import SolveContext, solve_scope
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
    text_response,
    with_client,
)

BETA = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n"
    "Email: info@beta.test\n#ABOUT\nPackaging supplier in Turin."
)
BETA_CORRECTED = BETA.replace("info@beta.test", "orders@beta.test")
# Shares the word "beta" with the query, so the legacy `limit=1` search ranks it
# first — and it is the wrong memory to write.
DECOY = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Logistica\n"
    "Email: info@betalog.test\n#ABOUT\nHauls for Beta Spa. beta beta beta."
)
SAID = "L'indirizzo ordini di Beta Spa ora è orders@beta.test"


# ─── Wiring ───────────────────────────────────────────────────────────


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def supervised(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    monkeypatch.setenv("MNEMONIC_WRITE_PATH", "supervised")
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


@pytest.fixture
def legacy(tmp_path, monkeypatch, embedder):
    """The shipped default: the direct top-hit replace, untouched."""
    stub_embedder(monkeypatch, embedder)
    monkeypatch.delenv("MNEMONIC_WRITE_PATH", raising=False)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
    yield owner
    dbm.dispose_engine()
    clear_process_state()


def seed(content, embedder):
    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    blob = storage.store_blob(
        owner_id=OWNER_A,
        namespace=f"user:{COMPANY_A}",
        content=content,
        event_description="seed",
    )
    return blob["id"], storage.get_blob(blob["id"], OWNER_A)["updated_at"]


def blobs():
    with get_session() as session:
        return {b.id: b.content for b in session.query(Blob).all()}


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


class Accepting:
    """A human who reads every card and accepts it."""

    def __init__(self):
        self.cards = []

    def request(self, mutation):
        from zylch.services.mnemonic_approval import acceptance_payload

        from zylch.memory.mnemonic.approval import Acceptance

        card = mutation.as_card()
        self.cards.append(card)
        return Acceptance.from_payload(acceptance_payload(card))


def run_solve_tool(monkeypatch, *, context, channel, responses, query="Beta"):
    """The real solve tool inside one solve scope, under one acceptance channel."""
    from zylch.memory.mnemonic.approval import install_channel
    from zylch.memory.mnemonic.turn import revocable_turn

    with_client(monkeypatch, client(*responses))
    with revocable_turn(), solve_scope(context), install_channel(channel):
        return solve_memory.update_memory(
            {"query": query, "new_content": BETA_CORRECTED}, None, OWNER_A
        )


# ─── The solve context keeps the two kinds of text apart ──────────────


def test_a_typed_instruction_is_the_observation_and_the_task_text_is_not():
    context = SolveContext(
        task_id="t1",
        instruction="Correggi l'indirizzo ordini di Beta",
        task_text="Beta Spa chiede un preventivo entro venerdì.",
    )
    assert context.observation == "Correggi l'indirizzo ordini di Beta"
    assert context.human_asked is True
    assert context.source_kind == "task_instruction"


def test_with_nothing_typed_the_task_text_is_the_observation():
    context = SolveContext(task_id="t1", task_text="Beta Spa chiede un preventivo.")
    assert context.observation == "Beta Spa chiede un preventivo."
    assert context.human_asked is False
    assert context.source_kind == "task"


def test_whitespace_is_not_an_instruction():
    context = SolveContext(task_id="t1", instruction="   \n ", task_text="observed")
    assert context.human_asked is False
    assert context.observation == "observed"


def test_task_text_versions_by_the_rows_change_marker_and_an_instruction_by_itself():
    """A task row has a version; a typed sentence does not, so its text is one."""
    observed = SolveContext(task_id="t1", task_text="x", task_revision="2026-09-23T08:00:00")
    assert observed.source_revision == "2026-09-23T08:00:00"
    # Absent marker still yields a non-empty revision — the field is required.
    assert SolveContext(task_id="t1", task_text="x").source_revision
    typed = SolveContext(task_id="t1", instruction="fix it")
    assert typed.source_revision == SolveContext(task_id="t1", instruction="fix it").source_revision
    assert (
        typed.source_revision != SolveContext(task_id="t1", instruction="fix that").source_revision
    )


def test_the_context_is_built_from_the_task_rows_own_columns():
    """`description` is not a column; inventing one would silently observe nothing."""
    context = solve_memory.solve_context_from_task(
        {
            "id": "t1",
            "title": "Preventivo Beta",
            "suggested_action": "Rispondi con i termini",
            "reason": "Chiede entro venerdì",
            "analyzed_at": "2026-09-23T08:00:00",
        },
        instructions="",
    )
    assert "Preventivo Beta" in context.task_text
    assert "Rispondi con i termini" in context.task_text
    assert "Chiede entro venerdì" in context.task_text
    assert context.task_revision == "2026-09-23T08:00:00"
    assert context.task_id == "t1"


def test_the_mail_body_is_not_copied_into_the_context():
    """It has a row and a retention policy of its own; a copy would have two."""
    context = solve_memory.solve_context_from_task(
        {"id": "t1", "title": "Preventivo", "body_plain": "SEGRETO", "snippet": "SEGRETO"},
    )
    assert "SEGRETO" not in context.task_text


# ─── The query stopped being authority ────────────────────────────────


def test_the_shipped_default_still_overwrites_whatever_the_ranking_put_first(
    legacy, monkeypatch, embedder
):
    """The defect, still reproducible under the shipped default.

    The decoy shares more tokens with "Beta" than Beta Spa does, so the ranking
    puts it first and the legacy writer replaces it — a memory about hauling
    becomes a memory about an ordering address, and nobody was asked.
    """
    _beta, _v = seed(BETA, embedder)
    decoy, _ = seed(DECOY, embedder)

    out = solve_memory.update_memory(
        {"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A
    )

    assert "Memory updated" in out
    # Whichever row the ranking chose, it was chosen by the tool, not a human.
    written = [bid for bid, content in blobs().items() if content == BETA_CORRECTED]
    assert len(written) == 1
    assert decoy in blobs()


def test_the_semantic_path_asks_before_writing_anything(supervised, monkeypatch, embedder):
    target, version = seed(BETA, embedder)
    seed(DECOY, embedder)
    surface = Accepting()

    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        channel=surface,
        responses=[update_decision(target, version)],
    )

    assert len(surface.cards) == 1
    card = surface.cards[0]
    # The caller named no blob, so the subject was chosen for it — always shown.
    assert "unnamed_subject" in card["flags"]
    assert card["write_set"][0]["blob_id"] == target
    assert "Memory updated" in out
    assert "orders@beta.test" in blobs()[target]


def test_with_no_acceptance_channel_the_solve_writes_nothing(supervised, monkeypatch, embedder):
    """A headless solve — a cron, a scheduled operator — returns review."""
    target, version = seed(BETA, embedder)
    before = blobs()

    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        channel=None,
        responses=[update_decision(target, version)],
    )

    assert "Not written" in out
    assert "approval channel" in out
    assert blobs() == before


def test_outside_a_solve_the_tool_refuses_rather_than_inventing_a_task(
    supervised, monkeypatch, embedder
):
    seed(BETA, embedder)
    before = blobs()
    out = solve_memory.update_memory(
        {"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A
    )
    assert out == solve_memory.NO_SOLVE_CONTEXT
    assert blobs() == before


def test_a_task_with_no_text_at_all_is_refused(supervised, monkeypatch, embedder):
    seed(BETA, embedder)
    with solve_scope(SolveContext(task_id="t1")):
        out = solve_memory.update_memory(
            {"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A
        )
    assert out == solve_memory.NO_OBSERVATION


def test_its_own_missing_arguments_are_still_refused_first(supervised):
    assert "Missing query or new_content" in solve_memory.update_memory(
        {"query": "", "new_content": ""}, None, OWNER_A
    )


# ─── Observation-only content cannot acquire an instruction's authority ─


def submitted_event(monkeypatch, context, embedder, target, version):
    """Capture the event the solve adapter builds, without writing."""
    from zylch.memory.mnemonic import commit as commit_mod

    seen = {}

    def capture(event, **kwargs):
        seen["event"] = event
        seen["requested"] = kwargs.get("requested")
        from zylch.memory.mnemonic.proposals import MnemonicResult

        return MnemonicResult.review_needed(event.event_id, "captured")

    monkeypatch.setattr(commit_mod, "submit", capture)
    import zylch.memory.mnemonic as pkg

    monkeypatch.setattr(pkg, "submit", capture)
    with solve_scope(context):
        solve_memory.update_memory({"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A)
    return seen


def test_a_typed_correction_is_operator_delegated_and_never_a_human_correction(
    supervised, monkeypatch, embedder
):
    seen = submitted_event(
        monkeypatch, SolveContext(task_id="t1", instruction=SAID), embedder, None, None
    )
    event = seen["event"]
    assert event.caller_class == OPERATOR_DELEGATED
    assert event.caller_class != VERIFIED_HUMAN_CORRECTION
    assert event.observation == SAID
    assert event.explicit_request is True


def test_observation_only_task_content_is_an_automatic_observation(
    supervised, monkeypatch, embedder
):
    """The same tool, the same call, a different authority — decided by the field.

    This is the case the plan names: task content cannot acquire the authority of
    a human instruction merely by being passed to the tool a human also uses.
    """
    seen = submitted_event(
        monkeypatch,
        SolveContext(task_id="t1", task_text="Beta Spa scrive per un preventivo."),
        embedder,
        None,
        None,
    )
    event = seen["event"]
    assert event.caller_class == AUTOMATIC_OBSERVATION
    assert event.caller_class != VERIFIED_HUMAN_CORRECTION
    assert event.observation == "Beta Spa scrive per un preventivo."
    assert event.explicit_request is False


def test_the_solve_is_interactive_either_way_because_a_human_pressed_solve(
    supervised, monkeypatch, embedder
):
    """Origin is the paid-admission contract, not the authority.

    An interactive grant rides the caller's turn; an automatic one must match an
    admitted preparation item. A solve has no preparation item, so calling it
    automatic would refuse it outright — and calling the *authority* interactive
    would be the real mistake, which is why the two are separate fields.
    """
    for context in (
        SolveContext(task_id="t1", instruction=SAID),
        SolveContext(task_id="t1", task_text="observed"),
    ):
        assert (
            submitted_event(monkeypatch, context, embedder, None, None)["event"].origin
            == INTERACTIVE
        )


def test_the_query_reaches_the_decision_as_nothing_at_all(supervised, monkeypatch, embedder):
    """It selects nothing, and it is not a subject hint either.

    It was one, briefly: ``SubjectHint(name=query)``, on the theory that a name
    hint widens retrieval. It does not — see the two tests below — and it made
    the validator read every solve as a caller-resolved entity subject.
    """
    seen = submitted_event(
        monkeypatch, SolveContext(task_id="t1", instruction=SAID), embedder, None, None
    )
    event = seen["event"]
    assert event.subject_hint is None
    assert event.suggestion == BETA_CORRECTED
    assert seen["requested"].subject_is_authoritative is False
    assert seen["requested"].blob_id is None


def test_a_name_hint_would_not_have_widened_retrieval(supervised, embedder):
    """The reason the query is not passed as one: it surfaces nothing.

    ``candidates.gather`` searches ``event.observation``, and the identifier
    index stores no names, so a name hint reaches neither. Only
    ``target_blob_id`` pins a row.
    """
    from zylch.memory.mnemonic.candidates import gather
    from zylch.memory.mnemonic.contracts import (
        INTERACTIVE,
        OPERATOR_DELEGATED,
        MemoryEvent,
        SubjectHint,
    )

    target, _ = seed(BETA, embedder)
    queries: list = []

    def searched(query, limit):
        queries.append(query)
        return ()

    def event_with(hint):
        return MemoryEvent(
            owner_id=OWNER_A,
            company_key=COMPANY_A,
            caller_class=OPERATOR_DELEGATED,
            origin=INTERACTIVE,
            source_kind="task",
            source_id="task:t1",
            source_revision="r1",
            observation="Da lunedì apriamo alle 8",
            subject_hint=hint,
        )

    from zylch.memory.blob_storage import BlobStorage

    storage = BlobStorage(get_session, embedder)
    by_name = gather(
        event_with(SubjectHint(name="Beta Spa")),
        get_blob=lambda bid: storage.get_blob(bid, OWNER_A),
        search=searched,
    )
    by_id = gather(
        event_with(SubjectHint(target_blob_id=target)),
        get_blob=lambda bid: storage.get_blob(bid, OWNER_A),
        search=searched,
    )

    # The search never sees the name — only the observation.
    assert queries == ["Da lunedì apriamo alle 8"] * 2
    assert [c.blob_id for c in by_name] == []
    assert [c.blob_id for c in by_id] == [target]


def test_a_solve_can_still_propose_company_wide_knowledge(supervised, monkeypatch, embedder):
    """The defect the hint caused: a FACT was refused before anyone was asked.

    ``SubjectHint(name=...)`` makes ``names_entity_subject`` true, and the
    validator then forbids a company FACT outright — so "from Monday we open at
    8" could never be stored by a solve, whatever the human said.
    """
    from zylch.memory.mnemonic.approval import install_channel
    from zylch.memory.mnemonic.turn import revocable_turn

    fact = json.dumps(
        {
            "action": "CREATE",
            "entity_type": "FACT",
            "scope": "company",
            "content": (
                "#IDENTIFIERS\nEntity type: FACT\nScope: company\n"
                "Key: opening hours\n#ABOUT\nOpen 08:00-19:00 from Monday."
            ),
            "reason": "this is company-wide knowledge, not a fact about a contact",
        }
    )
    surface = Accepting()
    with_client(monkeypatch, client(fact))
    with (
        revocable_turn(),
        solve_scope(
            SolveContext(task_id="t1", instruction="Da lunedì apriamo alle 8 e chiudiamo alle 19")
        ),
        install_channel(surface),
    ):
        out = solve_memory.update_memory(
            {"query": "orario", "new_content": "Open 08:00-19:00 from Monday"},
            None,
            OWNER_A,
        )

    assert "Memory updated" in out, out
    stored = [c for c in blobs().values() if "08:00-19:00" in c]
    assert len(stored) == 1


# ─── An interactive correction is not preparation work ─────────────────


#: The fields an interactive turn may not move. ``preparation.status`` is the
#: real reader the engine itself uses; a helper that invented its own view could
#: agree with itself while the row underneath changed.
PREPARATION_FIELDS = ("paused", "running", "attempted", "completed", "failed", "limit")


def test_an_interactive_correction_with_no_preparation_leaves_it_untouched(
    supervised, monkeypatch, embedder
):
    """Its pause, its busy flag, its batch allowance and its retry state.

    A solve that quietly consumed preparation's allowance would make an
    interactive correction compete with background work it has nothing to do
    with — and would then be refused by a limit meant for automatic runs.
    """
    from zylch.services import preparation

    target, version = seed(BETA, embedder)
    before = preparation.status(OWNER_A)
    assert set(PREPARATION_FIELDS) <= set(before), before

    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        channel=Accepting(),
        responses=[update_decision(target, version)],
    )

    assert "Memory updated" in out
    after = preparation.status(OWNER_A)
    for field in PREPARATION_FIELDS:
        assert after[field] == before[field], field


def test_a_refused_correction_leaves_preparation_untouched_too(supervised, monkeypatch, embedder):
    """A declined card must not cost the background work anything either."""
    from zylch.services import preparation

    target, version = seed(BETA, embedder)
    before = preparation.status(OWNER_A)

    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        channel=None,
        responses=[update_decision(target, version)],
    )

    assert "Not written" in out
    after = preparation.status(OWNER_A)
    for field in PREPARATION_FIELDS:
        assert after[field] == before[field], field


# ─── The real executor, both thread hops, and cancellation ─────────────


def tool_use_response(tool_id="tu-1", query="Beta"):
    from types import SimpleNamespace

    block = SimpleNamespace(
        type="tool_use",
        id=tool_id,
        name="update_memory",
        input={"query": query, "new_content": BETA_CORRECTED},
    )
    return SimpleNamespace(
        content=[block],
        model="claude-haiku-4-5",
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=300, output_tokens=90),
        refusal=None,
    )


def executor_with(monkeypatch, *, responses, notify):
    """The real ``TaskExecutor`` over the real client, transport replaced only."""
    from unittest.mock import Mock

    from zylch.llm.client import LLMClient
    from zylch.services.solve_constants import SOLVE_TOOLS
    from zylch.services.task_executor import TaskExecutor

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(side_effect=responses)
    with_client(monkeypatch, llm)
    return TaskExecutor(
        llm,
        "you are a test",
        [{"role": "user", "content": "fix Beta's ordering address"}],
        None,
        OWNER_A,
        SOLVE_TOOLS,
        notify=notify,
    )


async def drive(executor, *, answer_final, cards):
    """Iterate the real event stream, answering both gates the way a client does.

    The tool-call gate arrives through the generator. The final-mutation card
    cannot — it is decided inside the tool, on a worker thread — so it arrives
    through ``notify`` and is answered on the loop, exactly as the renderer's
    approve call does.
    """
    events = []
    async for event in executor.run():
        events.append(event)
        if event["type"] == "tool_call_pending":
            await executor.approve(event["tool_use_id"], True)
        if event["type"] == "done":
            break
    return events


def test_the_real_executor_carries_a_solve_through_both_gates_and_writes(
    supervised, monkeypatch, embedder
):
    """Model hop → tool hop → role hop → acceptance → commit, all real.

    Two thread boundaries are crossed: the executor runs the tool in an executor
    thread with a copied context, and the client runs its sync call in another.
    The dispatch grant is an object in that context, so it survives both — which
    is why the role's paid call is admitted at all.
    """
    from zylch.memory.mnemonic.approval import install_channel
    from zylch.memory.mnemonic.turn import revocable_turn

    target, version = seed(BETA, embedder)
    surface = Accepting()
    cards: list = []
    answered: list = []

    def notify(event):
        cards.append(event)
        if event["type"] == "tool_call_pending":
            answered.append(asyncio.ensure_future(executor.approve(event["tool_use_id"], True)))

    executor = executor_with(
        monkeypatch,
        responses=[
            tool_use_response(),
            text_response(update_decision(target, version)),
            text_response("Done — Beta's ordering address is corrected."),
        ],
        notify=notify,
    )

    context = SolveContext(task_id="t1", instruction=SAID)
    with revocable_turn() as handle, solve_scope(context), install_channel(surface):
        events = asyncio.run(drive(executor, answer_final=True, cards=cards))

    outputs = [e for e in events if e["type"] == "tool_result"]
    assert outputs and "Memory updated" in outputs[0]["output"], outputs
    assert "orders@beta.test" in blobs()[target]
    # The acceptance was asked for, through the harness, once.
    assert len(surface.cards) == 1
    # The grant was honoured across both hops: the role's call reached a provider.
    assert handle.dispatched >= 1
    assert executor.mutating_actions_taken == 1


def test_a_live_cancellation_revokes_a_grant_and_frees_the_parked_thread(
    supervised, monkeypatch, embedder
):
    """Through the production path: the executor's own cancellation handler.

    An earlier version of this test revoked the handle itself, which proved only
    that `Cancellation` works. What has to hold is that `TaskExecutor`'s
    `CancelledError` branch does it — `revoke()` for the grant a worker thread
    holds by reference, and `_fail_pending()` for the acceptance that thread is
    parked on. Without the second, the thread sits in
    `future.result(timeout=600)` for ten minutes after the solve is gone.
    """
    from zylch.memory.mnemonic.approval import install_channel
    from zylch.memory.mnemonic.turn import revocable_turn
    from zylch.services.mnemonic_approval import TURN_GONE, CallbackChannel

    target, version = seed(BETA, embedder)
    before = blobs()
    asked = threading.Event()
    answered: dict = {}

    executor = executor_with(
        monkeypatch,
        responses=[
            tool_use_response(),
            text_response(update_decision(target, version)),
            text_response("done"),
        ],
        # `notify` carries only the memory card: the executor yields its own
        # tool-call gate through the event stream, and `drive` answers that.
        notify=lambda event: asked.set(),
    )

    async def run_and_cancel():
        loop = asyncio.get_running_loop()
        # The real bridge over the executor's real approval surface — nobody
        # answers the memory card, so the worker thread parks on it.
        # A long channel timeout on purpose: what is under test is that the
        # executor frees the thread, not that the timeout eventually does.
        channel = CallbackChannel(executor.request_final_mutation, loop=loop, timeout=60)
        recording = _Recording(channel, answered)
        with (
            revocable_turn() as handle,
            solve_scope(SolveContext(task_id="t1", instruction=SAID)),
            install_channel(recording),
        ):
            runner = asyncio.ensure_future(drive(executor, answer_final=False, cards=[]))
            await asyncio.to_thread(asked.wait, 15)
            assert asked.is_set(), "the card was never presented"
            # What `tasks.solve.cancel` does: cancel the task running the solve.
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
            # The thread must be free within seconds, and it must be freed HERE
            # — asserted inside the loop, before `asyncio.run` tears it down.
            # Teardown cancels the pending `_ask` and joins the executor anyway,
            # so an assertion made after it would pass with or without the fix:
            # the only thing that would differ is how long the run took, and a
            # duration is not an assertion.
            for _ in range(100):
                if "reason" in answered:
                    break
                await asyncio.sleep(0.05)
            assert "reason" in answered, (
                "the acceptance was still parked 5s after the solve was cancelled; "
                "the executor did not fail its pending approvals"
            )
            return handle

    handle = asyncio.run(run_and_cancel())

    assert handle.cancelled is True, "the executor did not revoke the turn"
    assert answered.get("reason") == TURN_GONE, answered
    assert blobs() == before


class _Recording:
    """Wraps the real channel and records what the harness was told."""

    def __init__(self, channel, sink):
        self._channel = channel
        self._sink = sink

    def request(self, mutation):
        answer = self._channel.request(mutation)
        self._sink["reason"] = answer.reason
        self._sink["accepted"] = answer.accepted
        return answer


def test_declining_a_memory_change_is_a_review_the_model_can_read(
    supervised, monkeypatch, embedder
):
    """Declining the change is not cancelling the solve.

    The engine answers a decline with a reason, so the loop can say something
    useful instead of dying. The Desktop renderer routes a memory-change decline
    to `tasks.solve.approve(approved=false)` for exactly this; sending
    `tasks.solve.cancel` instead would throw this answer away.
    """
    from zylch.memory.mnemonic.approval import NOT_ACCEPTED, install_channel
    from zylch.memory.mnemonic.turn import revocable_turn
    from zylch.services.mnemonic_approval import CallbackChannel

    target, version = seed(BETA, embedder)
    before = blobs()
    outputs: list = []

    executor = executor_with(
        monkeypatch,
        responses=[
            tool_use_response(),
            text_response(update_decision(target, version)),
            text_response("I could not change that memory."),
        ],
        # The memory card arrives here and is DECLINED. The tool call itself is
        # approved through the event stream by `drive`, exactly as a client does —
        # answering only this one would leave the executor waiting on its own
        # gate forever.
        notify=lambda event: asyncio.ensure_future(executor.approve(event["tool_use_id"], False)),
    )

    async def run():
        loop = asyncio.get_running_loop()
        channel = CallbackChannel(executor.request_final_mutation, loop=loop, timeout=30)
        with (
            revocable_turn(),
            solve_scope(SolveContext(task_id="t1", instruction=SAID)),
            install_channel(channel),
        ):
            events = await drive(executor, answer_final=False, cards=[])
        outputs.extend(e["output"] for e in events if e["type"] == "tool_result")

    asyncio.run(run())

    assert outputs, "the solve produced no tool result"
    assert "Not written" in outputs[0]
    assert NOT_ACCEPTED in outputs[0]
    assert blobs() == before


def test_the_executor_declines_a_final_mutation_when_its_driver_offers_no_card():
    """No notifier means no way to show the change, so it does not proceed."""
    from zylch.services.task_executor import TaskExecutor

    executor = TaskExecutor(None, "s", [], None, OWNER_A, [], notify=None)
    approved, edited = asyncio.run(
        executor.request_final_mutation("use-1", "confirm_memory_write", {"preview": "x"})
    )
    assert approved is False
    assert edited is None
