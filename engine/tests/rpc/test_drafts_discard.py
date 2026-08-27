"""What `drafts.discard` retires, and what it refuses to touch.

The method exists so a draft the conversation has moved past can leave
the listings — until it landed, the only way out of `status='draft'`
was being sent, so a stale draft kept presenting itself as work. Its
whole risk is the mirror image: destroying something that is not stale.
So most of what is asserted here is a refusal — another owner's draft
is invisible, a draft a transport is holding is left alone, a draft
already sent stays as the record that it was — and the one destructive
path is asserted to remove exactly one row and to say what it removed.

Storage is a fake keyed the way the real one is, `(owner_id, id)`;
`storage.delete_draft` itself is exercised against real SQLite by the
storage tests, and stubbing it here keeps these tests about the
handler's decisions.
"""

from __future__ import annotations

import asyncio

import pytest

from zylch.rpc import draft_actions

OWNER = "owner-uid"
OTHER_OWNER = "someone-else-uid"


def _notify(*_a, **_k):
    return None


class _Store:
    """Owner-scoped draft table, plus a switch for the lost-race case."""

    def __init__(self, drafts, delete_returns=None):
        # {(owner_id, draft_id): row}
        self.drafts = dict(drafts)
        self._delete_returns = delete_returns
        self.delete_calls: list = []

    def get_draft(self, owner_id, draft_id):
        row = self.drafts.get((owner_id, draft_id))
        return dict(row) if row else None

    def delete_draft(self, owner_id, draft_id):
        self.delete_calls.append((owner_id, draft_id))
        if self._delete_returns is not None:
            return self._delete_returns
        return self.drafts.pop((owner_id, draft_id), None) is not None


def _draft(draft_id, status="draft", owner=OWNER, to=None, subject="Re: your quote"):
    return {
        "id": draft_id,
        "owner_id": owner,
        "status": status,
        "to_addresses": to if to is not None else ["customer@example.test"],
        "subject": subject,
        "body": "…",
    }


@pytest.fixture
def wired(monkeypatch):
    """Install a fake store + owner; hand the store back to the test."""

    def _install(rows, delete_returns=None):
        store = _Store({(r["owner_id"], r["id"]): r for r in rows}, delete_returns)
        monkeypatch.setattr("zylch.storage.storage.Storage.get_instance", lambda: store)
        monkeypatch.setattr("zylch.cli.utils.get_owner_id", lambda: OWNER)
        return store

    return _install


def _call(params):
    return asyncio.run(draft_actions.drafts_discard(params, _notify))


# ─── the shape of the request ─────────────────────────────────────────


def test_draft_id_is_required():
    """Declared mandatory in the docstring, so the handler must RAISE
    without it — the rule `tests/rpc/test_contract_boundaries.py`
    enforces registry-wide."""
    with pytest.raises(ValueError):
        _call({})


def test_an_empty_draft_id_is_not_a_draft_id():
    with pytest.raises(ValueError):
        _call({"draft_id": ""})


# ─── what it refuses ──────────────────────────────────────────────────


def test_an_unknown_draft_is_a_refusal_not_an_error(wired):
    store = wired([])
    res = _call({"draft_id": "nope"})
    assert res == {
        "ok": False,
        "discarded": False,
        "draft_id": "nope",
        "reason": "not_found",
    }
    assert store.delete_calls == []


def test_another_owners_draft_is_invisible(wired):
    """Owner scoping is the whole protection here: the id alone must not
    be enough to destroy a row."""
    store = wired([_draft("d1", owner=OTHER_OWNER)])
    res = _call({"draft_id": "d1"})
    assert res["ok"] is False
    assert res["reason"] == "not_found"
    assert store.delete_calls == []
    assert (OTHER_OWNER, "d1") in store.drafts


def test_a_draft_a_transport_is_holding_is_left_alone(wired):
    """`sending` means a send is in flight; deleting the row underneath
    it would race the path that is about to stamp it sent."""
    store = wired([_draft("d1", status="sending")])
    res = _call({"draft_id": "d1"})
    assert res["ok"] is False
    assert res["reason"] == "send_in_flight"
    assert res["status"] == "sending"
    assert store.delete_calls == []
    assert (OWNER, "d1") in store.drafts


def test_a_sent_draft_stays_as_the_record_that_it_was_sent(wired):
    store = wired([_draft("d1", status="sent")])
    res = _call({"draft_id": "d1"})
    assert res["ok"] is False
    assert res["reason"] == "already_sent"
    assert store.delete_calls == []
    assert (OWNER, "d1") in store.drafts


def test_the_refused_set_is_exactly_the_one_send_draft_refuses():
    """`send_draft` refuses `sent` and `sending` and keeps `failed`
    sendable. Discard has to agree, or a row is both unsendable and
    unretirable."""
    assert set(draft_actions.UNDISCARDABLE) == {"sending", "sent"}


# ─── what it retires ──────────────────────────────────────────────────


def test_a_stale_draft_is_removed_and_named(wired):
    store = wired([_draft("d1", to=["ada@example.test"], subject="Re: the quote")])
    res = _call({"draft_id": "d1"})
    assert res["ok"] is True
    assert res["discarded"] is True
    assert res["draft_id"] == "d1"
    assert res["to"] == ["ada@example.test"]
    assert res["subject"] == "Re: the quote"
    assert (OWNER, "d1") not in store.drafts


def test_only_the_named_draft_goes(wired):
    store = wired([_draft("d1"), _draft("d2"), _draft("d3")])
    _call({"draft_id": "d2"})
    assert sorted(k[1] for k in store.drafts) == ["d1", "d3"]
    assert store.delete_calls == [(OWNER, "d2")]


def test_a_failed_draft_is_discardable(wired):
    """`failed` is a draft that could not be sent, not one that was —
    retiring it must stay possible."""
    store = wired([_draft("d1", status="failed")])
    res = _call({"draft_id": "d1"})
    assert res["ok"] is True
    assert res["status"] == "failed"
    assert store.drafts == {}


def test_a_draft_deleted_between_the_read_and_the_delete_is_not_claimed(wired):
    """Two callers, one draft: the loser must not report a deletion it
    did not perform."""
    wired([_draft("d1")], delete_returns=False)
    res = _call({"draft_id": "d1"})
    assert res["ok"] is False
    assert res["discarded"] is False
    assert res["reason"] == "not_found"


# ─── how the engine exposes it ────────────────────────────────────────


def _dispatch(params):
    """Drive the real dispatcher, not the handler — the param gates the
    docstring declares only exist on this path."""
    import json

    from zylch.rpc.dispatch import dispatch_raw

    request = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "drafts.discard", "params": params}
    )
    return asyncio.run(dispatch_raw(request, _notify))


def test_the_method_is_registered_under_its_wire_name():
    from zylch.rpc.methods import METHODS

    assert METHODS["drafts.discard"] is draft_actions.drafts_discard


def test_the_dispatcher_reaches_the_handler(wired):
    store = wired([_draft("d1")])
    assert _dispatch({"draft_id": "d1"})["result"]["discarded"] is True
    assert store.drafts == {}


def test_a_call_without_a_draft_id_is_refused_before_the_handler_runs(wired):
    from zylch.rpc.dispatch import INVALID_PARAMS

    store = wired([_draft("d1")])
    error = _dispatch({})["error"]
    assert error["code"] == INVALID_PARAMS
    assert store.delete_calls == []


def test_an_unknown_parameter_is_refused_rather_than_dropped(wired):
    """`drafts.discard(force=True)` must not silently discard anyway."""
    from zylch.rpc.dispatch import INVALID_PARAMS

    store = wired([_draft("d1", status="sent")])
    error = _dispatch({"draft_id": "d1", "force": True})["error"]
    assert error["code"] == INVALID_PARAMS
    assert "force" in error["message"]
    assert store.delete_calls == []
