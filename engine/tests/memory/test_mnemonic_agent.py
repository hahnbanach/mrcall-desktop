"""The mnemonic role: what it will accept from a model, and what it costs.

Two halves. The prompt invariant — the complete identity and refusal rule set
in the cached system block, entity data only in the user turn — is the same
invariant ``tests/workers/test_merge_gate.py`` locks for the merge gate, and it
is locked here for the same reason: a cache refactor once dropped the refusal
rules and the model stopped refusing.

The second half runs the real ``LLMClient`` and the real durable budget ledger
with only the provider transport replaced, so budget refusal, truncation and
the bounded redecision loop are exercised through the boundary that actually
guards production.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zylch.llm.budget import BudgetError
from zylch.llm.client import LLMClient
from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic import prompts
from zylch.memory.mnemonic.agent import CALL_SITE, adapt_response, decide
from zylch.memory.mnemonic.contracts import MemoryEvent
from zylch.memory.response_validation import MemoryResponseError, strict_json_object
from zylch.storage import database

from .mnemonic_cases import COMPANY_KEY, OWNER, build, case, decision_text


def interactive(case_id):
    """The incident as a supervised request.

    These tests are about the decision round. Whether an automatic event
    may spend at all is a different contract, and it has its own file:
    ``tests/llm/test_mnemonic_admission.py``.
    """
    return build(case_id, origin=c.INTERACTIVE)


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    """A real reservation ledger on a temp database — no provider, real money rules."""
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", OWNER)
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    from zylch.storage.models import LlmReservation, LlmUsage

    database.Base.metadata.create_all(
        database.get_engine(), tables=[LlmUsage.__table__, LlmReservation.__table__]
    )
    yield
    database.dispose_engine()


def _usage():
    return SimpleNamespace(input_tokens=400, output_tokens=120)


def text_response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text, refusal=None)],
        model="claude-haiku-4-5",
        stop_reason=stop_reason,
        usage=_usage(),
        refusal=None,
    )


def tool_response():
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use",
                id="tu_1",
                name="update_memory",
                input={"content": "x"},
                refusal=None,
            )
        ],
        model="claude-haiku-4-5",
        stop_reason="end_turn",
        usage=_usage(),
        refusal=None,
    )


def client(*replies):
    """The real client, only its provider transport replaced."""
    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(side_effect=list(replies))
    return llm


# ─── The prompt invariant ─────────────────────────────────────────────


def test_the_whole_rule_set_is_in_the_cached_system_block():
    blocks = prompts.system_blocks()

    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == prompts.MNEMONIC_INSTRUCTIONS
    # The half a cache refactor once dropped.
    assert prompts.REFUSAL_SENTINEL in blocks[0]["text"]
    for rule in ("REVIEW", "SKIP", "MERGE", "corroborated identity evidence", "reclassification"):
        assert rule in blocks[0]["text"]


def test_the_prompt_never_asks_for_a_compressed_memory():
    text = prompts.MNEMONIC_INSTRUCTIONS.lower()
    for compressing in ("one sentence", "be brief", "as short as possible", "keep it short"):
        assert compressing not in text
    assert "do not compress a useful memory" in text


def test_the_user_turn_carries_data_and_no_instructions():
    event, candidates = interactive("corroborated_same_person")

    message = prompts.user_message(event, candidates)

    assert event.observation in message
    assert candidates[0].blob_id in message
    assert candidates[0].updated_at in message
    # Not one rule leaks out of the cached block into the per-call turn.
    assert prompts.REFUSAL_SENTINEL not in message
    assert "FAMILIES AND SCOPE" not in message


def test_the_role_is_never_shown_a_similarity_score():
    _, candidates = build("shared_switchboard")
    message = prompts.user_message(*build("shared_switchboard"))
    assert str(candidates[0].score) not in message
    assert "shared_identifiers" in message


def test_the_original_observation_and_the_caller_rewrite_stay_separate():
    event, candidates = build("customer_forwarding_number_correction")
    rewritten = event.with_model_arguments({"content": "Acme: +39 02 123456"})

    message = prompts.user_message(rewritten, candidates)

    assert '"observation"' in message and event.observation in message
    assert '"caller_suggestion"' in message and "Acme: +39 02 123456" in message


# ─── What a response must be before it is a proposal ──────────────────


def test_a_tool_call_is_not_a_decision():
    with pytest.raises(MemoryResponseError):
        adapt_response(tool_response())


def test_a_truncated_response_is_refused_rather_than_repaired():
    spec = case("malformed_output")
    with pytest.raises(MemoryResponseError):
        adapt_response(text_response(spec["model_response"], spec["transport_stop_reason"]))


def test_a_narrated_prefix_with_a_cut_off_object_is_refused():
    with pytest.raises(MemoryResponseError):
        adapt_response(text_response(case("malformed_output")["model_response"]))


def test_a_complete_object_followed_by_prose_is_refused():
    with pytest.raises(MemoryResponseError) as exc:
        adapt_response(text_response(decision_text("trailing_mixed_response")))
    assert "trailing content" in str(exc.value)


def test_an_empty_json_object_is_not_a_decision():
    with pytest.raises(MemoryResponseError):
        adapt_response(text_response(decision_text("empty_json_object")))


def test_malformed_json_is_refused():
    for body in ("", "   ", "not json at all", "{", '{"action": }', "[]", '["CREATE"]'):
        with pytest.raises(MemoryResponseError):
            strict_json_object(body)


def test_a_single_code_fence_is_tolerated_but_a_second_answer_is_not():
    proposal = adapt_response(text_response(decision_text("fenced_but_valid")))
    assert proposal.action == c.REVIEW

    with pytest.raises(MemoryResponseError):
        strict_json_object('```json\n{"action": "SKIP"}\n```\nand also this')


def test_an_out_of_contract_field_is_refused_not_coerced():
    with pytest.raises(MemoryResponseError):
        adapt_response(text_response('{"action": "OVERWRITE", "reason": "x"}'))
    with pytest.raises(MemoryResponseError):
        adapt_response(text_response('{"action": "CREATE", "entity_type": "PROJECT"}'))
    with pytest.raises(MemoryResponseError):
        adapt_response(
            text_response('{"action": "UPDATE", "write_set": [{"blob_id": "b", "role": "wipe"}]}')
        )


# ─── The decision round, through the real client ──────────────────────


def test_an_accepted_mutation_waits_for_a_commit_capability_and_keeps_its_proposal():
    event, candidates = build("customer_forwarding_number_correction")
    llm = client(text_response(decision_text("customer_forwarding_number_correction")))

    decision = decide(event, candidates, client=llm)

    assert decision.accepted is True
    assert decision.proposal.action == c.UPDATE
    assert decision.proposal.target.blob_id == "company-acme"
    # No commit module exists yet: nothing was written and nothing claims it was.
    assert decision.result.outcome == c.RETRYABLE_FAILURE
    assert decision.result.reason == c.NO_COMMIT_CAPABILITY
    assert decision.result.committed_ids == ()
    assert llm._client.messages.create.call_count == 1


def test_a_deliberate_skip_is_a_skip_and_advances_a_checkpoint():
    event, candidates = interactive("planned_not_completed")
    llm = client(text_response('{"action": "SKIP", "reason": "already recorded as planned"}'))

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.SKIPPED
    assert decision.result.advances_checkpoint is True
    assert decision.accepted is False


def test_a_refusal_to_remember_is_visible_as_review_not_a_hidden_skip():
    event, candidates = build("customer_forwarding_number_correction")
    assert event.explicit_request is True
    llm = client(
        text_response('{"action": "SKIP", "reason": "not worth it"}'),
        text_response('{"action": "SKIP", "reason": "still not worth it"}'),
        text_response('{"action": "REVIEW", "reason": "I will not overwrite this unasked"}'),
    )

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.REVIEW_NEEDED
    assert decision.result.advances_checkpoint is False
    assert "will not overwrite" in decision.result.reason


def test_a_rejected_decision_is_re_asked_with_its_reasons_and_never_becomes_a_create():
    event, candidates = build("customer_forwarding_number_correction")
    as_fact = (
        '{"action": "CREATE", "entity_type": "FACT", "scope": "company", '
        '"content": "#IDENTIFIERS\\nEntity type: FACT\\nScope: company\\nCategory: p\\nKey: k\\n'
        '#ABOUT\\nAcme forwards to +39 02 123456.", "reason": "global"}'
    )
    llm = client(*[text_response(as_fact)] * c.MAX_DECISION_ATTEMPTS)

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.REVIEW_NEEDED
    assert decision.accepted is False
    assert llm._client.messages.create.call_count == c.MAX_DECISION_ATTEMPTS

    second = llm._client.messages.create.call_args_list[1].kwargs["messages"]
    assert second[0]["content"] == prompts.user_message(event, candidates)
    assert "refused for these reasons" in second[-1]["content"]
    assert "company-wide knowledge" in second[-1]["content"]
    assert "Do not fall back to CREATE" in second[-1]["content"]


def test_the_decision_loop_stops_at_the_bounded_attempt_count():
    event, candidates = interactive("corroborated_same_person")
    llm = client(*[text_response("this is not json")] * 10)

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.REVIEW_NEEDED
    assert decision.attempts == c.MAX_DECISION_ATTEMPTS
    assert llm._client.messages.create.call_count == c.MAX_DECISION_ATTEMPTS


def test_a_recovered_decision_validates_on_the_second_round():
    event, candidates = interactive("corroborated_same_person")
    llm = client(
        text_response("{ broken"),
        text_response(decision_text("corroborated_same_person")),
    )

    decision = decide(event, candidates, client=llm)

    assert decision.accepted is True
    assert decision.attempts == 2
    assert llm._client.messages.create.call_count == 2


def test_truncation_costs_its_attempts_and_still_commits_nothing():
    event, candidates = build("customer_forwarding_number_correction")
    partial = decision_text("customer_forwarding_number_correction")[:120]
    llm = client(*[text_response(partial, "max_tokens")] * c.MAX_DECISION_ATTEMPTS)

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.REVIEW_NEEDED
    assert decision.result.committed_ids == ()
    assert decision.accepted is False


def test_zero_budget_refuses_before_the_provider_is_reached(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    event, candidates = build("customer_forwarding_number_correction")
    llm = client(text_response(decision_text("customer_forwarding_number_correction")))

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.RETRYABLE_FAILURE
    assert "paid decision unavailable" in decision.result.reason
    llm._client.messages.create.assert_not_called()


def test_a_read_only_request_is_refused_with_no_reservation_and_no_provider_call():
    from zylch.llm.budget import budget_snapshot
    from zylch.services.request_policy import READ_ONLY_POLICY, policy_scope

    event, candidates = build("customer_forwarding_number_correction")
    llm = client(text_response(decision_text("customer_forwarding_number_correction")))

    with policy_scope(READ_ONLY_POLICY):
        decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.REVIEW_NEEDED
    assert "read-only" in decision.result.reason
    assert decision.attempts == 0
    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0
    assert budget_snapshot(OWNER)["spent_usd"] == 0


def test_a_cancelled_event_stops_dispatching_and_keeps_what_it_already_spent():
    event, candidates = build("customer_forwarding_number_correction")
    llm = client(
        text_response("{ broken"),
        text_response(decision_text("customer_forwarding_number_correction")),
    )
    original = llm._client.messages.create

    def cancel_after_first(**kwargs):
        response = original(**kwargs)
        event.cancellation.cancel("user pressed stop")
        return response

    llm._client.messages.create = Mock(side_effect=cancel_after_first)

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.RETRYABLE_FAILURE
    assert decision.result.reason == "user pressed stop"
    assert llm._client.messages.create.call_count == 1
    assert event.cancellation.dispatched == 1  # the dispatched call keeps its charge


def test_the_decision_is_tagged_for_attribution_only():
    event, candidates = interactive("corroborated_same_person")
    seen = {}
    llm = client(text_response(decision_text("corroborated_same_person")))
    original = llm._client.messages.create

    def capture(**kwargs):
        from zylch.llm.usage import current_call_site

        seen["site"] = current_call_site()
        return original(**kwargs)

    llm._client.messages.create = Mock(side_effect=capture)
    decide(event, candidates, client=llm)

    assert seen["site"] == CALL_SITE


def test_the_role_is_never_handed_a_tool():
    event, candidates = interactive("corroborated_same_person")
    llm = client(text_response(decision_text("corroborated_same_person")))

    decide(event, candidates, client=llm)

    sent = llm._client.messages.create.call_args.kwargs
    assert "tools" not in sent and "tool_choice" not in sent
    assert sent["max_tokens"] == c.MNEMONIC_MAX_TOKENS


def test_an_event_for_another_account_is_refused_before_any_paid_work():
    event = MemoryEvent(
        owner_id="someone-else",
        company_key=COMPANY_KEY,
        caller_class=c.VERIFIED_HUMAN_CORRECTION,
        origin=c.INTERACTIVE,
        source_kind="chat",
        source_id="turn-1",
        source_revision="rev-1",
        observation="remember this for them",
    )
    llm = client(text_response('{"action": "SKIP", "reason": "x"}'))

    decision = decide(event, (), client=llm)

    assert decision.result.outcome == c.REVIEW_NEEDED
    assert "does not match the event owner" in decision.result.reason
    llm._client.messages.create.assert_not_called()


def test_a_budget_failure_mid_loop_is_retryable_not_a_refusal():
    event, candidates = interactive("corroborated_same_person")
    llm = client(text_response("{ broken"), BudgetError("daily limit reached"))

    decision = decide(event, candidates, client=llm)

    assert decision.result.outcome == c.RETRYABLE_FAILURE
    assert decision.result.advances_checkpoint is False


# ─── The cached block, over the whole conversation ────────────────────


def test_the_retry_turn_carries_reasons_and_never_the_rule_set():
    """A correction is per-call data; the rules stay in the cached block."""
    event, candidates = interactive("corroborated_same_person")
    llm = client(
        text_response("{ broken"),
        text_response(decision_text("corroborated_same_person")),
    )

    decide(event, candidates, client=llm)

    for call in llm._client.messages.create.call_args_list:
        assert call.kwargs["system"][0]["text"] == prompts.MNEMONIC_INSTRUCTIONS
        assert call.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
        for message in call.kwargs["messages"]:
            assert prompts.REFUSAL_SENTINEL not in str(message["content"])
            assert "FAMILIES AND SCOPE" not in str(message["content"])


def test_the_cached_block_survives_the_client_datetime_injection():
    """The datetime is appended PAST the breakpoint, so the cache still hits."""
    from zylch.llm.client import _with_datetime

    sent = _with_datetime(prompts.system_blocks())

    assert sent[0]["text"] == prompts.MNEMONIC_INSTRUCTIONS
    assert sent[0]["cache_control"] == {"type": "ephemeral"}
    assert sent[-1]["text"].startswith("Datetime=")
    assert "cache_control" not in sent[-1]
