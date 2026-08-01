"""Both directions of the urgency policy: who is waiting decides.

The bug this locks down (support@, 2026-08-01 00:15): an 8-week
unanswered cancellation request was demoted to ``low`` because the
TRAINED task-detection prompt — reused verbatim as the reanalysis system
prompt — carries a self-extrapolated rule, "Emails older than 30 days are
at most LOW unless there's an explicit unfulfilled commitment". That rule
is right for first-time detection and inverted for reanalysis of a task
that exists precisely because nobody answered.

Three contracts:

- the deterministic resolver names WHO is waiting and for how long;
- the FLOOR refuses to persist a lower urgency on an unanswered inbound,
  whatever the model proposes;
- the CAP still demotes a genuine we-spoke-last follow-up, and stands
  down when model and parser disagree about who is waiting.
"""

import asyncio

import pytest

from zylch.workers.thread_presenter import (
    WAITING_ON_CONTACT,
    WAITING_ON_US,
    WAITING_UNKNOWN,
    cap_urgency_for_silent_followup,
    describe_waiting_state,
    floor_urgency_for_unanswered_inbound,
    is_last_turn_user_reply,
    resolve_waiting_state,
)

CONTACT_LAST = (
    "THREAD HISTORY (chronological):\n"
    "[2026-06-04 12:07] CONTACT luna@example.com:\nVorrei disdire il servizio.\n\n"
    "[2026-06-04 12:07] AUTO-REPLY (system, not user engagement) support@example.com:\n"
    "Ciao MrCaller! Abbiamo preso in carico la tua richiesta."
)

USER_LAST = (
    "THREAD HISTORY (chronological):\n"
    "[2026-07-31 17:23] CONTACT cliente@example.com:\nCome procedo?\n\n"
    "[2026-08-01 11:15] USER REPLY ✓ support@example.com:\nEcco i passaggi, mi faccia sapere."
)


# ── the shared resolution ──────────────────────────────────────────


def test_contact_spoke_last_means_waiting_on_us():
    state = resolve_waiting_state(CONTACT_LAST)
    assert state.who == WAITING_ON_US
    assert state.last_turn_at is not None
    assert state.age_days is not None and state.age_days > 0


def test_user_spoke_last_means_waiting_on_contact():
    assert resolve_waiting_state(USER_LAST).who == WAITING_ON_CONTACT
    assert is_last_turn_user_reply(USER_LAST) is True
    assert is_last_turn_user_reply(CONTACT_LAST) is False


def test_auto_reply_is_not_an_answer():
    """The auto-ack is the NEWEST line, and must not flip ownership."""
    assert resolve_waiting_state(CONTACT_LAST).who == WAITING_ON_US


def test_empty_history_is_unknown():
    state = resolve_waiting_state("")
    assert state.who == WAITING_UNKNOWN
    assert "unknown" in describe_waiting_state(state)


def test_description_states_who_and_how_long():
    text = describe_waiting_state(resolve_waiting_state(CONTACT_LAST))
    assert "WAITING ON US" in text
    assert "days ago" in text


# ── the floor ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "current,proposed,expect_urgency,expect_floored",
    [
        ("critical", "low", "critical", True),
        ("high", "medium", "high", True),
        ("medium", "low", "medium", True),
        ("low", "low", "low", False),  # equal — nothing to refuse
        ("medium", "high", "high", False),  # raising is always allowed
    ],
)
def test_floor_refuses_demotion_when_waiting_on_us(
    current, proposed, expect_urgency, expect_floored
):
    urgency, floored = floor_urgency_for_unanswered_inbound(current, proposed, CONTACT_LAST)
    assert (urgency, floored) == (expect_urgency, expect_floored)


def test_floor_stays_out_of_we_spoke_last_threads():
    """The floor is not a global no-demotion rule — the cap must still work."""
    assert floor_urgency_for_unanswered_inbound("high", "low", USER_LAST) == ("low", False)


def test_floor_ignores_missing_values():
    assert floor_urgency_for_unanswered_inbound(None, "low", CONTACT_LAST) == ("low", False)
    assert floor_urgency_for_unanswered_inbound("high", None, CONTACT_LAST) == (None, False)


# ── the cap (unchanged direction) ──────────────────────────────────


def test_cap_demotes_silent_followup():
    assert cap_urgency_for_silent_followup("high", USER_LAST) == ("low", True)
    assert cap_urgency_for_silent_followup("medium", USER_LAST) == ("low", True)


def test_cap_leaves_unanswered_inbound_alone():
    assert cap_urgency_for_silent_followup("high", CONTACT_LAST) == ("high", False)


# ── end-to-end through reanalyze_task ──────────────────────────────


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "urgency_policy.db"))
    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield
    db_mod.dispose_engine()


OWNER = "owner-urgency-policy"


class _Block:
    type = "tool_use"
    name = "reanalyze_decision"

    def __init__(self, payload):
        self.input = payload


class _Resp:
    def __init__(self, payload):
        self.content = [_Block(payload)]
        self.usage = {"input_tokens": 0, "output_tokens": 0}


class _Client:
    def __init__(self, payload):
        self._payload = payload

    async def create_message(self, **kwargs):
        return _Resp(self._payload)


def _seed_task(urgency: str, history: str, monkeypatch):
    """One open task whose thread history renders as ``history``."""
    from zylch.storage.storage import Storage
    from zylch.workers import task_reanalyze as mod

    store = Storage()
    store.store_task_item(
        OWNER,
        {
            "event_type": "email",
            "event_id": "<seed@example.com>",
            "contact_email": "luna@example.com",
            "contact_name": "Luna",
            "title": "Disdetta",
            "action_required": True,
            "urgency": urgency,
            "reason": "seed",
            "sources": {"thread_id": "thread-seed", "emails": []},
        },
    )
    task = store.get_task_by_event(OWNER, "email", "<seed@example.com>")
    monkeypatch.setattr(mod, "_resolve_thread_id", lambda *a, **k: "thread-seed")
    import zylch.workers.thread_presenter as tp

    monkeypatch.setattr(tp, "build_thread_history", lambda **k: history)
    return store, task


def test_reanalyze_floor_blocks_the_age_decay_demotion(fresh_db, monkeypatch):
    import zylch.llm as zllm
    from zylch.workers.task_reanalyze import reanalyze_task

    store, task = _seed_task("critical", CONTACT_LAST, monkeypatch)
    monkeypatch.setattr(
        zllm,
        "try_make_llm_client",
        lambda model=None: _Client(
            {
                "action": "update",
                "urgency": "low",
                "reason": "Older than 30 days, age decay to low.",
                "waiting_on": "us",
            }
        ),
    )
    asyncio.run(reanalyze_task(task["id"], OWNER))
    after = store.get_task_by_id(OWNER, task["id"])
    assert after["urgency"] == "critical"
    assert "urgency floor" in (after["reason"] or "")


def test_reanalyze_cap_still_demotes_we_spoke_last(fresh_db, monkeypatch):
    import zylch.llm as zllm
    from zylch.workers.task_reanalyze import reanalyze_task

    store, task = _seed_task("medium", USER_LAST, monkeypatch)
    monkeypatch.setattr(
        zllm,
        "try_make_llm_client",
        lambda model=None: _Client(
            {"action": "keep", "reason": "waiting on them", "waiting_on": "contact"}
        ),
    )
    asyncio.run(reanalyze_task(task["id"], OWNER))
    assert store.get_task_by_id(OWNER, task["id"])["urgency"] == "low"


def test_reanalyze_cap_stands_down_on_a_disputed_read(fresh_db, monkeypatch):
    import zylch.llm as zllm
    from zylch.workers.task_reanalyze import reanalyze_task

    store, task = _seed_task("medium", USER_LAST, monkeypatch)
    monkeypatch.setattr(
        zllm,
        "try_make_llm_client",
        lambda model=None: _Client(
            {"action": "keep", "reason": "I read it as unanswered", "waiting_on": "us"}
        ),
    )
    asyncio.run(reanalyze_task(task["id"], OWNER))
    assert store.get_task_by_id(OWNER, task["id"])["urgency"] == "medium"
