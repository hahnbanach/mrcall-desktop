"""The merge gate's canary asks the mnemonic role, and its verdicts mean what they say.

The gate exists for the 2026-06 universal-'John'-sink: a model that folds
unrelated contacts into one memory, with nothing to say so. These lock in,
without a live LLM, the invariants the canary and the pair decision stand on:

- the role's whole rule set travels in the cached system block, and the two
  memories only in the user turn — the split whose loss caused the sink;
- a consolidation pair reaches the harness through ``decide_pair``, with the
  merge-routed client;
- the canary's verdicts: ``refused`` when the role does not propose to fold
  the two; ``merged`` when it answers MERGE, or an UPDATE that absorbs the
  other memory, whatever the validator says; ``error`` — never disabling —
  when the call fails or the answer is unusable.

Each case runs the canary against a recording client: the canary's own
logic, the role's prompt builders, the response adapter and the validator are
the real ones. The paid path — the real ``LLMClient`` inside a preparation
run — is ``tests/memory/test_consolidation.py``'s canary cases.
"""

import json

import pytest

from zylch.memory import llm_merge
from zylch.memory.llm_merge import LLMMergeService, merge_gate_selfcheck
from zylch.memory.mnemonic import prompts

from tests.memory.consolidation_env import CANARY_FOLDS, CANARY_REFUSES
from tests.memory.mnemonic_env import text_response

ABSORBING_UPDATE = json.dumps(
    {
        "action": "UPDATE",
        "entity_type": "PERSON",
        "scope": "entity",
        "content": "#IDENTIFIERS\nEntity type: PERSON\nScope: entity\nName: Aldo Bianchi\n"
        "#ABOUT\nA customer; also Zeta Logistics.",
        "write_set": [{"blob_id": "canary-person", "expected_version": "canary", "role": "target"}],
        "declared_effects": ["alias:canary-company->canary-person", "delete:canary-company"],
        "reason": "the same subject",
    }
)


class RecordingClient:
    """The client protocol the canary uses: answers in order, records each request."""

    model = "fake-model"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def create_message_sync(self, **request):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return text_response(answer)


def service(monkeypatch, *answers):
    """An ``LLMMergeService`` whose routed client is a recording client."""
    recording = RecordingClient(*answers)
    monkeypatch.setattr(llm_merge, "make_llm_client", lambda model=None: recording)
    return LLMMergeService(), recording


def test_the_role_rules_ride_the_cached_block_and_the_memories_the_user_turn(monkeypatch):
    svc, recording = service(monkeypatch, CANARY_REFUSES)

    merge_gate_selfcheck(svc)

    (sent,) = recording.requests
    system_text = "".join(block["text"] for block in sent["system"])
    assert system_text == prompts.MNEMONIC_INSTRUCTIONS
    assert sent["system"][-1]["cache_control"] == {"type": "ephemeral"}
    user_text = json.dumps(sent["messages"])
    for address in ("aldo.bianchi@canary-person.example", "info@canary-company.example"):
        assert address not in system_text and address in user_text


def test_a_pair_reaches_the_harness_through_decide_pair(monkeypatch):
    from zylch.memory.mnemonic import pairs

    svc, _ = service(monkeypatch)
    seen = {}

    def decide(pair_, *, client):
        seen.update(pair=pair_, client=client)
        return "the harness's result"

    monkeypatch.setattr(pairs, "decide", decide)
    assert svc.decide_pair({"id": "a|b"}) == "the harness's result"
    assert seen == {"pair": {"id": "a|b"}, "client": svc.client}


@pytest.mark.parametrize(
    "answer",
    [CANARY_REFUSES, json.dumps({"action": "REVIEW", "reason": "cannot tell"})],
    ids=["skip", "review"],
)
def test_the_canary_is_healthy_when_the_role_does_not_fold_them(monkeypatch, answer):
    svc, _ = service(monkeypatch, answer)
    result = merge_gate_selfcheck(svc)
    assert result["healthy"] is True and result["verdict"] == "refused"


BARE_MERGE = json.dumps({**json.loads(CANARY_FOLDS), "declared_effects": []})


@pytest.mark.parametrize("answer", [CANARY_FOLDS, BARE_MERGE], ids=["declared", "bare"])
def test_the_canary_is_broken_open_when_the_role_answers_merge(monkeypatch, answer):
    svc, _ = service(monkeypatch, answer)
    result = merge_gate_selfcheck(svc)
    # The validator refuses this merge — no evidence ties the two — and the
    # verdict is still broken open: the gate guards the model's judgment. A
    # MERGE is broken open whether or not it declares what it absorbs.
    assert result["healthy"] is False and result["verdict"] == "merged"
    assert result["validator"] == "refused"


def test_the_canary_is_broken_open_when_an_update_absorbs_the_other(monkeypatch):
    svc, _ = service(monkeypatch, ABSORBING_UPDATE)
    result = merge_gate_selfcheck(svc)
    assert result["healthy"] is False and result["verdict"] == "merged"


def test_the_canary_is_unknown_and_never_disabling_when_it_cannot_judge(monkeypatch):
    down, _ = service(monkeypatch, RuntimeError("api down"))
    assert merge_gate_selfcheck(down)["healthy"] is None

    unusable, _ = service(monkeypatch, "I think they are different people.")
    result = merge_gate_selfcheck(unusable)
    # healthy=None means "couldn't check" — never broken, so a flaky call or
    # an unusable answer does not disable merging for a whole build.
    assert result["healthy"] is None and result["verdict"] == "error"
