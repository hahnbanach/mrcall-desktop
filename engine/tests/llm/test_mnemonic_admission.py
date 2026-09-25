"""Origin-bound paid admission for mnemonic work, at the real client boundary.

The contract these tests hold is that **the dispatch scope is the authority and
the usage label is not**. A usage tag exists so a spend audit can attribute
cost; it has never decided whether a call may happen, and relabelling an
unauthorized mnemonic call ``chat`` — or leaving it untagged — must change
nothing.

The two origins are separate contracts on purpose. An interactive grant rides
the caller's own turn and leaves bounded preparation exactly as it found it:
its pause, its busy flag, its batch allowance, its per-source retry state. An
automatic grant has no such turn behind it, so it must match the preparation
item that was actually admitted — otherwise background work could buy itself
the interactive contract simply by constructing an event.
"""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zylch.llm.budget import BudgetError, budget_snapshot
from zylch.llm.client import LLMClient
from zylch.llm.usage import call_site
from zylch.memory.mnemonic import contracts as c
from zylch.memory.mnemonic.authorization import (
    MnemonicAuthorizationError,
    dispatch_scope,
    issue_grant,
    revoke_grant,
)
from zylch.memory.mnemonic.contracts import MemoryEvent
from zylch.services import preparation
from zylch.services.preparation import PreparationStopped, bounded_item, preparation_run
from zylch.storage import database

OWNER = "uid-test"
COMPANY_KEY = "AAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ZYLCH_DB_PATH", str(tmp_path / "profile.db"))
    monkeypatch.setenv("OWNER_ID", OWNER)
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    database.dispose_engine()
    from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

    database.Base.metadata.create_all(
        database.get_engine(),
        tables=[
            LlmUsage.__table__,
            LlmReservation.__table__,
            # The metered path records a billing authorization alongside the
            # reservation; without it the proxy end-to-end test cannot reserve.
            LlmBillingAuthorization.__table__,
        ],
    )
    yield
    database.dispose_engine()


_serial = itertools.count(1)


def event(*, origin=c.INTERACTIVE, owner=OWNER, source_id="turn-1", stage=None, event_id=None):
    return MemoryEvent(
        event_id=event_id or f"evt-{next(_serial)}",
        owner_id=owner,
        company_key=COMPANY_KEY,
        caller_class=(
            c.VERIFIED_HUMAN_CORRECTION if origin == c.INTERACTIVE else c.AUTOMATIC_OBSERVATION
        ),
        origin=origin,
        source_kind="chat" if origin == c.INTERACTIVE else "email",
        source_id=source_id,
        source_revision="rev-1",
        observation="Ricordati che per Acme il forwarding è +39 02 123456.",
        stage=stage or (None if origin == c.INTERACTIVE else "email"),
    )


def client():
    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._client.messages.create = Mock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"action": "REVIEW", "reason": "x"}')],
            model="claude-haiku-4-5",
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=200, output_tokens=40),
        )
    )
    return llm


ARGS = {"messages": [{"role": "user", "content": "decide"}], "max_tokens": 256}


def dispatch(llm, grant, *, tag="memory.mnemonic", **extra):
    with dispatch_scope(grant), call_site(tag):
        return llm.create_message_sync(**{**ARGS, **extra})


# ─── An interactive grant never touches preparation ───────────────────


def test_an_interactive_grant_leaves_a_paused_preparation_paused():
    preparation.pause(OWNER)
    before = preparation.status(OWNER)
    assert before["paused"] is True

    llm = client()
    grant = issue_grant(event())
    dispatch(llm, grant)

    assert llm._client.messages.create.call_count == 1
    assert preparation.status(OWNER) == before


def test_an_interactive_grant_runs_while_a_preparation_run_is_busy():
    llm = client()
    with preparation_run(OWNER):
        during = preparation.status(OWNER)
        assert during["running"] is True

        dispatch(llm, issue_grant(event()))

        after = preparation.status(OWNER)
    assert llm._client.messages.create.call_count == 1
    # Not one counter of the running batch moved.
    assert (after["attempted"], after["completed"], after["failed"]) == (
        during["attempted"],
        during["completed"],
        during["failed"],
    )


def test_an_interactive_grant_runs_when_the_batch_allowance_is_exhausted(monkeypatch):
    monkeypatch.setenv("PREPARATION_BATCH_SIZE", "1")
    llm = client()
    with preparation_run(OWNER):
        preparation.check_dispatch()  # consumes the single admitted step
        with pytest.raises(PreparationStopped):
            preparation.check_dispatch()
        exhausted = preparation.status(OWNER)

        dispatch(llm, issue_grant(event()))

        assert preparation.status(OWNER) == exhausted
    assert llm._client.messages.create.call_count == 1


def test_an_interactive_grant_does_not_mark_an_automatic_source_dispatched():
    """``record_dispatch`` must not credit someone else's item with this call."""
    llm = client()
    with preparation_run(OWNER):
        dispatch(llm, issue_grant(event()))
        rows = _attempt_rows()
    assert rows == []


def _attempt_rows():
    with preparation._db() as conn:
        return [
            dict(row)
            for row in conn.exec_driver_sql(
                "SELECT stage, source, inflight, dispatched, failures FROM preparation_attempts"
            ).mappings()
        ]


# ─── An automatic grant must match its admitted item ──────────────────


def test_an_automatic_grant_without_any_admitted_item_is_refused():
    llm = client()
    grant = issue_grant(event(origin=c.AUTOMATIC, source_id="mail-1"))

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, grant)

    assert "admitted preparation item" in str(exc.value)
    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_an_automatic_grant_inside_a_run_but_outside_an_item_is_refused():
    """A run is not an item: the per-source retry and backoff state is the bound."""
    llm = client()
    with preparation_run(OWNER):
        with pytest.raises(MnemonicAuthorizationError):
            dispatch(llm, issue_grant(event(origin=c.AUTOMATIC, source_id="mail-1")))
    llm._client.messages.create.assert_not_called()


class _Worker:
    """The real admitted-item path, as the memory workers use it."""

    owner_id = OWNER

    def __init__(self, llm, grant_for):
        self.llm = llm
        self.grant_for = grant_for
        self.error = None

    @bounded_item("email")
    async def process(self, source):
        try:
            dispatch(self.llm, self.grant_for(source))
        except MnemonicAuthorizationError as exc:
            self.error = exc
            return False
        return True


def _run_admitted(llm, grant_for, source_id="mail-1"):
    worker = _Worker(llm, grant_for)
    with preparation_run(OWNER):
        asyncio.run(worker.process({"id": source_id}))
    return worker


def test_an_automatic_grant_matching_the_admitted_item_may_spend():
    llm = client()
    worker = _run_admitted(
        llm, lambda src: issue_grant(event(origin=c.AUTOMATIC, source_id=src["id"]))
    )

    assert worker.error is None
    assert llm._client.messages.create.call_count == 1


def test_an_automatic_grant_for_a_different_source_cannot_borrow_the_admitted_one():
    llm = client()
    worker = _run_admitted(
        llm, lambda _src: issue_grant(event(origin=c.AUTOMATIC, source_id="some-other-mail"))
    )

    assert "does not match the admitted preparation source" in str(worker.error)
    llm._client.messages.create.assert_not_called()


def test_an_automatic_grant_for_a_different_stage_cannot_borrow_the_admitted_one():
    llm = client()
    worker = _run_admitted(
        llm,
        lambda src: issue_grant(event(origin=c.AUTOMATIC, source_id=src["id"], stage="calendar")),
    )

    assert "does not match the admitted preparation stage" in str(worker.error)
    llm._client.messages.create.assert_not_called()


def test_a_grant_copy_with_a_widened_origin_fails_identity_first():
    """A value copy is not the grant that was issued, whatever it claims.

    This is about forgery, not about who may declare an origin — that one is
    `test_background_work_cannot_claim_the_interactive_contract_by_declaring_it`.
    """
    llm = client()
    automatic = event(origin=c.AUTOMATIC, source_id="mail-1")
    grant = issue_grant(automatic)
    assert grant.is_interactive is False

    widened = dataclasses.replace(grant, origin=c.INTERACTIVE)
    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, widened)

    # The copy is not the grant that was issued, so it fails identity first.
    assert "never issued" in str(exc.value)
    llm._client.messages.create.assert_not_called()


# ─── Forgery, cross-owner and relabelling ─────────────────────────────


def test_a_forged_grant_this_process_never_issued_is_refused():
    llm = client()
    real = issue_grant(event())
    forged = dataclasses.replace(real)  # value-identical, different object

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, forged)

    assert "never issued" in str(exc.value)
    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_a_revoked_grant_stops_working():
    llm = client()
    grant = issue_grant(event())
    dispatch(llm, grant)
    revoke_grant(grant)

    with pytest.raises(MnemonicAuthorizationError):
        dispatch(llm, grant)

    assert llm._client.messages.create.call_count == 1


def test_an_event_for_another_account_cannot_even_get_a_grant():
    """Authorization is inside `issue_grant`, not a line a caller may skip."""
    from zylch.memory.mnemonic.authorization import MnemonicRefusal

    with pytest.raises(MnemonicRefusal) as exc:
        issue_grant(event(owner="someone-else"))
    assert "does not match the event owner" in str(exc.value)


def test_a_read_only_origin_cannot_get_a_grant_either():
    from zylch.memory.mnemonic.authorization import MnemonicRefusal
    from zylch.services.request_policy import READ_ONLY_POLICY, policy_scope

    with policy_scope(READ_ONLY_POLICY), pytest.raises(MnemonicRefusal):
        issue_grant(event())
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_a_grant_stops_working_when_the_process_changes_account(monkeypatch):
    """Defense in depth: the grant was legitimate, the process is not any more."""
    llm = client()
    grant = issue_grant(event())
    monkeypatch.setenv("OWNER_ID", "another-account")

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, grant)

    assert "another account" in str(exc.value)
    llm._client.messages.create.assert_not_called()


def test_a_process_that_cannot_name_its_account_refuses(monkeypatch):
    from zylch.memory.mnemonic.authorization import MnemonicRefusal

    monkeypatch.delenv("OWNER_ID", raising=False)
    monkeypatch.setattr("zylch.memory.mnemonic.authorization._current_owners", lambda: frozenset())
    with pytest.raises(MnemonicRefusal) as exc:
        issue_grant(event())
    assert "cannot say which account" in str(exc.value)


def test_a_grant_stops_working_when_the_profile_joins_another_company(monkeypatch):
    llm = client()
    grant = issue_grant(event())
    monkeypatch.setenv("MEMORY_KEY", "BBBBBBBBBBBBBBBBBBBBBB")

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, grant)

    assert "different company memory" in str(exc.value)
    llm._client.messages.create.assert_not_called()


@pytest.mark.parametrize("tag", ["chat", "untagged", "memory.merge", "task.detect"])
def test_relabelling_an_unauthorized_call_does_not_get_it_past_check_dispatch(tag):
    llm = client()
    forged = dataclasses.replace(issue_grant(event()))

    with pytest.raises(MnemonicAuthorizationError):
        dispatch(llm, forged, tag=tag)

    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_the_label_is_diagnostics_and_the_scope_is_the_authority():
    """The same tag passes or fails purely on whether a valid grant is in scope."""
    llm = client()
    with call_site("chat"):
        llm.create_message_sync(**ARGS)  # ordinary chat: no mnemonic scope, no grant needed
    assert llm._client.messages.create.call_count == 1

    with pytest.raises(MnemonicAuthorizationError):
        dispatch(llm, dataclasses.replace(issue_grant(event())), tag="chat")
    assert llm._client.messages.create.call_count == 1


# ─── Cancellation, allowance and the shared budget ────────────────────


def test_a_cancelled_grant_refuses_further_dispatch():
    llm = client()
    e = event()
    grant = issue_grant(e)
    dispatch(llm, grant)

    e.cancellation.cancel("user pressed stop")

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, grant)
    assert "user pressed stop" in str(exc.value)
    assert llm._client.messages.create.call_count == 1
    assert e.cancellation.dispatched == 1  # the first call keeps its charge


def test_cancellation_reaches_a_grant_already_copied_into_a_worker_thread():
    """``create_message`` runs the sync call in an executor with a copied context.

    The copy shares the cancellation handle by reference, which is the whole
    point: revoking the caller's turn revokes the thread that is already
    holding the grant.
    """
    llm = client()
    e = event()
    grant = issue_grant(e)
    e.cancellation.cancel("cancelled while queued")

    async def run():
        with dispatch_scope(grant), call_site("memory.mnemonic"):
            return await llm.create_message(**ARGS)

    with pytest.raises(MnemonicAuthorizationError):
        asyncio.run(run())

    llm._client.messages.create.assert_not_called()


def test_the_event_dispatch_allowance_is_finite():
    llm = client()
    grant = issue_grant(event())

    for _ in range(c.EVENT_DISPATCH_ALLOWANCE):
        dispatch(llm, grant)

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, grant)

    assert "exhausted its bounded dispatch allowance" in str(exc.value)
    assert llm._client.messages.create.call_count == c.EVENT_DISPATCH_ALLOWANCE


def test_an_interactive_grant_still_faces_the_shared_dollar_budget(monkeypatch):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    llm = client()

    with pytest.raises(BudgetError):
        dispatch(llm, issue_grant(event()))

    llm._client.messages.create.assert_not_called()


def test_a_mnemonic_dispatch_cannot_carry_a_tool():
    llm = client()
    grant = issue_grant(event())

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(
            llm,
            grant,
            tools=[{"name": "update_memory", "description": "write", "input_schema": {}}],
        )

    assert "cannot carry tools" in str(exc.value)
    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_ordinary_paid_work_is_unaffected_by_the_new_check():
    """No mnemonic scope, no change: the existing admission rules still decide."""
    llm = client()
    with call_site("memory.merge"):
        with pytest.raises(PreparationStopped):
            llm.create_message_sync(**ARGS)

    with preparation_run(OWNER), call_site("memory.merge"):
        llm.create_message_sync(**ARGS)
    assert llm._client.messages.create.call_count == 1


# ─── The holes a first pass left open ─────────────────────────────────


def test_an_item_context_with_no_admitted_run_buys_nothing():
    """`bounded_item` sets an item context even when `_admit` found no run.

    Without checking the run id, that unadmitted context looked exactly like an
    admitted one, and an automatic grant spent outside any bounded run at all.
    """
    llm = client()
    worker = _Worker(llm, lambda src: issue_grant(event(origin=c.AUTOMATIC, source_id=src["id"])))

    asyncio.run(worker.process({"id": "mail-1"}))  # deliberately outside preparation_run

    assert "admitted preparation item" in str(worker.error)
    llm._client.messages.create.assert_not_called()


def test_background_work_cannot_claim_the_interactive_contract_by_declaring_it():
    """`origin` is adapter-set, so the refusal has to be structural.

    Inside an admitted preparation item the only contract available is the
    automatic one, whatever the event calls itself.
    """
    llm = client()
    worker = _Worker(llm, lambda _src: issue_grant(event(origin=c.INTERACTIVE)))

    with preparation_run(OWNER):
        asyncio.run(worker.process({"id": "mail-1"}))

    assert "cannot claim the interactive contract" in str(worker.error)
    llm._client.messages.create.assert_not_called()


def test_the_allowance_belongs_to_the_event_not_to_the_grant():
    """Resubmitting a stuck event must not buy it a fresh budget."""
    llm = client()
    stuck = event(event_id="evt-resubmitted")
    grant = issue_grant(stuck)
    dispatch(llm, grant)
    dispatch(llm, grant)
    revoke_grant(grant)

    again = issue_grant(event(event_id="evt-resubmitted"))
    assert again.remaining == c.EVENT_DISPATCH_ALLOWANCE - 2
    for _ in range(again.remaining):
        dispatch(llm, again)
    with pytest.raises(MnemonicAuthorizationError):
        dispatch(llm, again)
    assert llm._client.messages.create.call_count == c.EVENT_DISPATCH_ALLOWANCE


def test_a_refused_call_does_not_cost_the_event_an_attempt(monkeypatch):
    """The allowance is spent at the provider, not at the admission check."""
    llm = client()
    grant = issue_grant(event())
    before = grant.remaining

    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "0")
    with pytest.raises(BudgetError):
        dispatch(llm, grant)

    assert grant.remaining == before
    llm._client.messages.create.assert_not_called()


def test_a_process_that_cannot_name_its_account_refuses_at_the_dispatch_too(monkeypatch):
    """Not only when the grant is minted: the account can become unknowable after."""
    llm = client()
    grant = issue_grant(event())
    monkeypatch.setattr("zylch.memory.mnemonic.authorization._current_owners", lambda: frozenset())

    with pytest.raises(MnemonicAuthorizationError) as exc:
        dispatch(llm, grant)

    assert "cannot say which account" in str(exc.value)
    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_forgetting_an_event_prefers_one_that_has_spent_nothing():
    """A bounded table must not hand a spent event a fresh budget when it fills."""
    from zylch.memory.mnemonic import authorization as auth

    llm = client()
    spent = issue_grant(event(event_id="evt-spent"))
    dispatch(llm, spent)
    assert spent.remaining == c.EVENT_DISPATCH_ALLOWANCE - 1

    for i in range(auth._ALLOWANCE_TRACKED + 2):
        issue_grant(event(event_id=f"evt-filler-{i}"))

    assert auth._ALLOWANCE.get("evt-spent") == c.EVENT_DISPATCH_ALLOWANCE - 1
    assert issue_grant(event(event_id="evt-spent")).remaining == c.EVENT_DISPATCH_ALLOWANCE - 1


def test_a_revocation_between_reservation_and_dispatch_releases_the_hold():
    """Nothing reached a provider, so the money must not stay held for an hour."""
    llm = client()
    e = event()
    grant = issue_grant(e)
    original_reserve = None

    def cancel_during_reservation(*args, **kwargs):
        result = original_reserve(*args, **kwargs)
        e.cancellation.cancel("stopped mid-admission")
        return result

    import zylch.llm.budget as budget_module

    original_reserve = budget_module.reserve
    try:
        budget_module.reserve = cancel_during_reservation
        with pytest.raises(MnemonicAuthorizationError):
            dispatch(llm, grant)
    finally:
        budget_module.reserve = original_reserve

    llm._client.messages.create.assert_not_called()
    assert budget_snapshot(OWNER)["reserved_usd"] == 0


def test_an_undispatched_hold_goes_back_only_on_the_unmetered_transports():
    """A metered reservation is receipt-gated: settling it without one refuses.

    Releasing it here would free nothing and would replace the cancellation
    with "MrCall charge is unconfirmed" for a user who simply pressed stop.
    """
    released = []

    def spy(reservation, usage, **kwargs):
        released.append((reservation, usage))

    for transport in ("direct", "openrouter"):
        llm = LLMClient(transport=transport, api_key="fake", model="claude-haiku-4-5")
        llm._release_unused_reservation("res-1", spy)
    assert [usage for _res, usage in released] == [
        {"input_tokens": 0, "output_tokens": 0},
        {"input_tokens": 0, "output_tokens": 0},
    ]

    metered = LLMClient.__new__(LLMClient)
    metered.transport = "proxy"
    metered._release_unused_reservation("res-2", spy)
    assert len(released) == 2  # untouched


def test_a_failed_release_never_replaces_the_reason_the_dispatch_was_refused():
    def explode(*_args, **_kwargs):
        raise BudgetError("ledger unavailable")

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm._release_unused_reservation("res-3", explode)  # reported, not raised


def _metered_client():
    """A client on the metered transport, with only the proxy wire replaced.

    The reservation, the quote validation and the billing-authorization row are
    the real ones; what is stubbed is the HTTP the proxy would do.
    """
    from zylch.llm.bounded_proxy import PROTOCOL, digest, wire_request

    llm = LLMClient(transport="direct", api_key="fake", model="claude-haiku-4-5")
    llm.transport = "proxy"

    def quote_for(request):
        body = {
            "protocol": PROTOCOL,
            "currency": "USD",
            "account_id": OWNER,
            "model": request["model"],
            "payload_hash": digest(wire_request(request)),
            "business_id": "biz-test",
            "tariff_version": "v1",
            "credit_value_micro_usd": 100,
            "max_credits": 10,
            "max_debit_micro_usd": 1000,
        }
        return {**body, "quote_hash": digest(body)}

    llm._client.quote = quote_for
    llm._client.execute = Mock(side_effect=AssertionError("the proxy must not be reached"))
    return llm


def test_a_metered_dispatch_revoked_after_reservation_keeps_its_reason_and_its_hold():
    """End to end on MrCall credits: the outcome, not just which branch ran.

    A receipt-gated reservation cannot be settled without a receipt, so the
    hold stands on purpose. What must not happen is the refusal turning into
    "MrCall charge is unconfirmed" for a user who simply pressed stop.
    """
    llm = _metered_client()
    e = event()
    grant = issue_grant(e)
    import zylch.llm.budget as budget_module

    original_reserve = budget_module.reserve

    def cancel_during_reservation(*args, **kwargs):
        result = original_reserve(*args, **kwargs)
        e.cancellation.cancel("stopped mid-admission")
        return result

    try:
        budget_module.reserve = cancel_during_reservation
        with pytest.raises(MnemonicAuthorizationError) as exc:
            dispatch(llm, grant)
    finally:
        budget_module.reserve = original_reserve

    assert "stopped mid-admission" in str(exc.value)
    llm._client.execute.assert_not_called()
    # Receipt-gated by design: the hold stands until the in-flight horizon.
    assert budget_snapshot(OWNER)["reserved_usd"] > 0
