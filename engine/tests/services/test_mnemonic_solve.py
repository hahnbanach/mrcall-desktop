"""The solve loop's memory write, and the authority it is not allowed to claim.

``_update_memory`` used to take a ``query``, search with ``limit=1``, and
overwrite whatever came back first. So the tool picked the victim from a
similarity ranking, and the text the model passed became the stored bytes. This
suite is about the three separate claims that path made and no longer does:

1. **The query does not select the target.** It is not passed into the decision
   at all, and because the caller names no blob, every proposal writes to a
   subject the caller did not choose — which is recorded as a departure in the
   journal and in the answer the model reads.
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

import pytest

from zylch.memory.mnemonic.approval import UNNAMED_SUBJECT
from zylch.memory.mnemonic.contracts import (
    AUTOMATIC_OBSERVATION,
    INTERACTIVE,
    OPERATOR_DELEGATED,
    UPDATE,
    VERIFIED_HUMAN_CORRECTION,
)
from zylch.memory.mnemonic.turn import revocable_turn
from zylch.services import solve_memory
from zylch.services.solve_context import SolveContext, solve_scope
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
    text_response,
    with_client,
)

BETA = (
    "#IDENTIFIERS\nEntity type: COMPANY\nScope: entity\nName: Beta Spa\n"
    "Email: info@beta.test\n#ABOUT\nPackaging supplier in Turin."
)
BETA_CORRECTED = BETA.replace("info@beta.test", "orders@beta.test")
SAID = "L'indirizzo ordini di Beta Spa ora è orders@beta.test"


# ─── Wiring ───────────────────────────────────────────────────────────


@pytest.fixture
def embedder():
    return BagOfWordsEmbedder()


@pytest.fixture
def profile(tmp_path, monkeypatch, embedder):
    stub_embedder(monkeypatch, embedder)
    owner = boot(monkeypatch, tmp_path, OWNER_A, COMPANY_A)
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


def journal_rows():
    with get_session() as session:
        return [r.to_dict() for r in session.query(MemoryOperation).all()]


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


def run_solve_tool(monkeypatch, *, context, responses, query="Beta"):
    """The real solve tool inside one solve scope."""
    with_client(monkeypatch, client(*responses))
    with revocable_turn(), solve_scope(context):
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
    observed = SolveContext(task_id="t1", task_text="x", task_revision="2026-09-23T08:00:00")
    assert observed.source_revision == "2026-09-23T08:00:00"
    assert SolveContext(task_id="t1", task_text="x").source_revision
    typed = SolveContext(task_id="t1", instruction="fix it")
    assert typed.source_revision == SolveContext(task_id="t1", instruction="fix it").source_revision
    assert (
        typed.source_revision != SolveContext(task_id="t1", instruction="fix that").source_revision
    )


def test_the_context_is_built_from_the_task_rows_own_columns():
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
    context = solve_memory.solve_context_from_task(
        {"id": "t1", "title": "Preventivo", "body_plain": "SEGRETO", "snippet": "SEGRETO"},
    )
    assert "SEGRETO" not in context.task_text


# ─── The query stopped being authority ────────────────────────────────


def submitted_event(monkeypatch, context):
    """Capture the event the solve adapter builds, without writing."""
    from zylch.memory.mnemonic import commit as commit_mod
    from zylch.memory.mnemonic.proposals import MnemonicResult

    seen = {}

    def capture(event, **kwargs):
        seen["event"] = event
        seen["requested"] = kwargs.get("requested")
        return MnemonicResult.review_needed(event.event_id, "captured")

    monkeypatch.setattr(commit_mod, "submit", capture)
    import zylch.memory.mnemonic as pkg

    monkeypatch.setattr(pkg, "submit", capture)
    with solve_scope(context):
        solve_memory.update_memory({"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A)
    return seen


def test_the_query_reaches_the_decision_as_nothing_at_all(profile, monkeypatch, embedder):
    """It selects nothing, and it is not a subject hint either.

    It was one, briefly: ``SubjectHint(name=query)``, on the theory that a name
    hint widens retrieval. It does not — see the next test — and it made the
    validator read every solve as a caller-resolved entity subject.
    """
    seen = submitted_event(monkeypatch, SolveContext(task_id="t1", instruction=SAID))
    event = seen["event"]
    assert event.subject_hint is None
    assert event.suggestion == BETA_CORRECTED
    assert seen["requested"].subject_is_authoritative is False
    assert seen["requested"].blob_id is None


def test_a_name_hint_would_not_have_widened_retrieval(profile, embedder):
    from zylch.memory.blob_storage import BlobStorage
    from zylch.memory.mnemonic.candidates import gather
    from zylch.memory.mnemonic.contracts import MemoryEvent, SubjectHint

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
    assert queries == ["Da lunedì apriamo alle 8"] * 2
    assert [c.blob_id for c in by_name] == []
    assert [c.blob_id for c in by_id] == [target]


def test_a_solve_can_propose_company_wide_knowledge(profile, monkeypatch, embedder):
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
    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(
            task_id="t1", instruction="Da lunedì apriamo alle 8 e chiudiamo alle 19"
        ),
        responses=[fact],
        query="orario",
    )
    assert "Memory updated" in out, out
    assert len([c for c in blobs().values() if "08:00-19:00" in c]) == 1


def test_the_write_lands_and_the_unnamed_subject_is_recorded(profile, monkeypatch, embedder):
    """Nobody is asked. The row the caller did not choose is written, and the
    departure says so — in the journal and in the answer the model reads."""
    target, version = seed(BETA, embedder)

    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        responses=[update_decision(target, version)],
    )

    assert "Memory updated" in out, out
    assert "Note:" in out
    assert "orders@beta.test" in blobs()[target]
    (row,) = journal_rows()
    assert UNNAMED_SUBJECT in row["departure"]["flags"]


def test_a_headless_caller_writes(profile, monkeypatch, embedder):
    """A cron, a scheduled operator: there is no channel to lack any more."""
    target, version = seed(BETA, embedder)
    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", task_text="Beta Spa: nuovo indirizzo ordini"),
        responses=[update_decision(target, version)],
    )
    assert "Memory updated" in out, out


def test_success_is_reported_only_after_the_row_reads_back(profile, monkeypatch, embedder):
    """A receipt is not a save the model may report.

    The commit succeeds; the read-back that follows it sees nothing. Only the
    reader is blinded, and only after the commit — the decision round and the
    CAS check read the same rows through the same method and must keep seeing
    them, or the test would be exercising a failed commit instead.
    """
    from zylch.memory import mnemonic as pkg
    from zylch.memory.blob_storage import BlobStorage

    target, version = seed(BETA, embedder)
    with_client(monkeypatch, client(update_decision(target, version)))
    routed = pkg.submit
    committed: dict = {}

    def submit_then_blind(event, **kwargs):
        result = routed(event, **kwargs)
        committed["done"] = bool(result.committed_ids)
        return result

    real_get_blob = BlobStorage.get_blob

    def get_blob(self, blob_id, owner_id):
        return None if committed.get("done") else real_get_blob(self, blob_id, owner_id)

    monkeypatch.setattr(pkg, "submit", submit_then_blind)
    monkeypatch.setattr(BlobStorage, "get_blob", get_blob)
    with revocable_turn(), solve_scope(SolveContext(task_id="t1", instruction=SAID)):
        out = solve_memory.update_memory(
            {"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A
        )

    assert committed.get("done") is True, out
    assert out.startswith("Not written"), out
    assert "cannot be read back" in out
    assert "orders@beta.test" in blobs()[target]


def test_outside_a_solve_the_tool_refuses_rather_than_inventing_a_task(
    profile, monkeypatch, embedder
):
    seed(BETA, embedder)
    before = blobs()
    out = solve_memory.update_memory(
        {"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A
    )
    assert out == solve_memory.NO_SOLVE_CONTEXT
    assert blobs() == before


def test_a_task_with_no_text_at_all_is_refused(profile, monkeypatch, embedder):
    seed(BETA, embedder)
    with solve_scope(SolveContext(task_id="t1")):
        out = solve_memory.update_memory(
            {"query": "Beta", "new_content": BETA_CORRECTED}, None, OWNER_A
        )
    assert out == solve_memory.NO_OBSERVATION


def test_its_own_missing_arguments_are_still_refused_first(profile):
    assert "Missing query or new_content" in solve_memory.update_memory(
        {"query": "", "new_content": ""}, None, OWNER_A
    )


# ─── Observation-only content cannot acquire an instruction's authority ─


def test_a_typed_correction_is_operator_delegated_and_never_a_human_correction(
    profile, monkeypatch, embedder
):
    event = submitted_event(monkeypatch, SolveContext(task_id="t1", instruction=SAID))["event"]
    assert event.caller_class == OPERATOR_DELEGATED
    assert event.caller_class != VERIFIED_HUMAN_CORRECTION
    assert event.observation == SAID
    assert event.explicit_request is True


def test_observation_only_task_content_is_an_automatic_observation(profile, monkeypatch, embedder):
    event = submitted_event(
        monkeypatch, SolveContext(task_id="t1", task_text="Beta Spa scrive per un preventivo.")
    )["event"]
    assert event.caller_class == AUTOMATIC_OBSERVATION
    assert event.observation == "Beta Spa scrive per un preventivo."
    assert event.explicit_request is False


def test_the_solve_is_interactive_either_way_because_a_human_pressed_solve(
    profile, monkeypatch, embedder
):
    for context in (
        SolveContext(task_id="t1", instruction=SAID),
        SolveContext(task_id="t1", task_text="observed"),
    ):
        assert submitted_event(monkeypatch, context)["event"].origin == INTERACTIVE


# ─── An interactive correction is not preparation work ─────────────────

PREPARATION_FIELDS = ("paused", "running", "attempted", "completed", "failed", "limit")


def test_an_interactive_correction_with_no_preparation_leaves_it_untouched(
    profile, monkeypatch, embedder
):
    from zylch.services import preparation

    target, version = seed(BETA, embedder)
    before = preparation.status(OWNER_A)
    assert set(PREPARATION_FIELDS) <= set(before), before

    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        responses=[update_decision(target, version)],
    )

    assert "Memory updated" in out
    after = preparation.status(OWNER_A)
    for field in PREPARATION_FIELDS:
        assert after[field] == before[field], field


def test_a_review_outcome_leaves_preparation_untouched_too(profile, monkeypatch, embedder):
    from zylch.services import preparation

    seed(BETA, embedder)
    before = preparation.status(OWNER_A)
    review = json.dumps({"action": "REVIEW", "reason": "two candidates could be the subject"})
    out = run_solve_tool(
        monkeypatch,
        context=SolveContext(task_id="t1", instruction=SAID),
        responses=[review],
    )
    assert out.startswith("Not written")
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


def executor_with(monkeypatch, *, responses):
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
        [{"role": "user", "content": "fix Beta's address"}],
        None,
        OWNER_A,
        SOLVE_TOOLS,
    )


async def drive(executor, *, approve=True, parked=None):
    """Iterate the real event stream, answering the tool-call gate as a client does.

    With ``approve=False`` nobody answers: the executor parks on its own
    approval future, ``parked`` is set, and the iteration stays inside the
    generator — which is where a cancellation has to land to reach its handler.
    """
    events = []
    async for event in executor.run():
        events.append(event)
        if event["type"] == "tool_call_pending":
            if approve:
                await executor.approve(event["tool_use_id"], True)
            elif parked is not None:
                parked.set()
        if event["type"] == "done":
            break
    return events


def test_the_real_executor_carries_a_solve_through_the_gate_and_writes(
    profile, monkeypatch, embedder
):
    """Model hop → tool hop → role hop → commit, all real.

    Two thread boundaries are crossed: the executor runs the tool in an executor
    thread with a copied context, and the client runs its sync call in another.
    The dispatch grant is an object in that context, so it survives both —
    which is why the role's paid call is admitted at all.
    """
    target, version = seed(BETA, embedder)
    executor = executor_with(
        monkeypatch,
        responses=[
            tool_use_response(),
            text_response(update_decision(target, version)),
            text_response("Done — Beta's ordering address is corrected."),
        ],
    )
    with revocable_turn() as handle, solve_scope(SolveContext(task_id="t1", instruction=SAID)):
        events = asyncio.run(drive(executor))

    outputs = [e for e in events if e["type"] == "tool_result"]
    assert outputs and "Memory updated" in outputs[0]["output"], outputs
    assert "orders@beta.test" in blobs()[target]
    assert handle.dispatched >= 1
    assert executor.mutating_actions_taken == 1


def test_a_live_cancellation_revokes_the_grant_and_fails_pending_approvals(
    profile, monkeypatch, embedder
):
    """The executor's own `CancelledError` branch: `revoke()` for the grant a
    worker thread would hold by reference, `_fail_pending()` for whatever is
    still waiting on an answer nobody will give.

    The solve is parked on its ordinary tool-call gate when it is cancelled —
    what `tasks.solve.cancel` does is cancel the task running it. Both effects
    are asserted inside the loop, before `asyncio.run` tears it down: teardown
    would fail the future and close the generator anyway, and an assertion made
    after it would pass with or without the handler.
    """
    target, version = seed(BETA, embedder)
    before = blobs()
    executor = executor_with(
        monkeypatch,
        responses=[tool_use_response(), text_response(update_decision(target, version))],
    )

    async def run_and_cancel():
        parked = asyncio.Event()
        with revocable_turn() as handle, solve_scope(SolveContext(task_id="t1", instruction=SAID)):
            runner = asyncio.ensure_future(drive(executor, approve=False, parked=parked))
            await asyncio.wait_for(parked.wait(), 15)
            assert executor._pending, "the executor never parked on its approval gate"
            runner.cancel()
            try:
                await runner
            except asyncio.CancelledError:
                pass
            assert handle.cancelled is True, "the executor did not revoke the turn"
            assert executor._pending == {}, "the parked approval was not failed"
            return handle

    handle = asyncio.run(run_and_cancel())
    assert handle.cancelled is True
    assert blobs() == before


def test_the_executor_has_no_card_surface_any_more():
    from zylch.services.task_executor import TaskExecutor

    assert not hasattr(TaskExecutor, "request_final_mutation")
    assert "notify" not in TaskExecutor.__init__.__code__.co_varnames
