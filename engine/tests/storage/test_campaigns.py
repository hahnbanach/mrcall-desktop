"""Campaign tables + campaign.* RPC handlers (outreach state).

Locks the contract: create → add_contact (idempotent upsert on
campaign_id+email) → contacts listing → update_contact state flow
(sent stamps sent_at server-side). Owner-scoping enforced.
"""

import asyncio

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test SQLite DB. Disposes the engine on teardown."""
    db_path = tmp_path / "campaigns_test.db"
    monkeypatch.setenv("ZYLCH_DB_PATH", str(db_path))

    from zylch.storage import database as db_mod

    db_mod.dispose_engine()
    db_mod.init_db()
    yield db_path
    db_mod.dispose_engine()


@pytest.fixture
def owner(monkeypatch):
    """Pin the RPC owner resolution to a fixed test owner."""
    import zylch.rpc.campaign_actions as ca

    monkeypatch.setattr(ca, "_owner_id", lambda: "owner_test")
    return "owner_test"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _notify(method, params):  # noqa: ARG001 — unused test stub
    pass


def test_campaign_roundtrip(fresh_db, owner):
    from zylch.rpc import campaign_actions as ca

    camp = _run(ca.campaign_create({"name": "pilot", "brief": "test brief"}, _notify))
    assert camp["name"] == "pilot" and camp["owner_id"] == owner

    c1 = _run(
        ca.campaign_add_contact(
            {
                "campaign_id": camp["id"],
                "email": "A@Example.com",
                "stratum": "ex",
                "verdict": "legit",
                "language": "it",
                "draft_subject": "s",
                "draft_body": "b",
            },
            _notify,
        )
    )
    assert c1["email"] == "a@example.com"  # normalized
    assert c1["state"] == "drafted"

    # idempotent upsert: same email updates, no duplicate
    c1bis = _run(
        ca.campaign_add_contact(
            {"campaign_id": camp["id"], "email": "a@example.com", "language": "fr"},
            _notify,
        )
    )
    assert c1bis["id"] == c1["id"] and c1bis["language"] == "fr"

    _run(
        ca.campaign_add_contact(
            {
                "campaign_id": camp["id"],
                "email": "skip@example.com",
                "state": "skipped",
                "verdict": "skip:impersonates-brand",
            },
            _notify,
        )
    )

    rows = _run(ca.campaign_contacts({"campaign_id": camp["id"]}, _notify))
    assert len(rows) == 2
    skipped = _run(
        ca.campaign_contacts({"campaign_id": camp["id"], "state": "skipped"}, _notify)
    )
    assert len(skipped) == 1

    # state flow: sent stamps sent_at
    upd = _run(
        ca.campaign_update_contact(
            {"contact_id": c1["id"], "state": "sent", "message_id": "<m@x>"}, _notify
        )
    )
    assert upd["ok"] and upd["contact"]["sent_at"] is not None
    assert upd["contact"]["message_id"] == "<m@x>"

    lst = _run(ca.campaign_list({}, _notify))
    assert lst[0]["contacts_by_state"] == {"sent": 1, "skipped": 1}


def test_invalid_state_rejected(fresh_db, owner):
    from zylch.rpc import campaign_actions as ca

    camp = _run(ca.campaign_create({"name": "x"}, _notify))
    with pytest.raises(ValueError):
        _run(
            ca.campaign_add_contact(
                {"campaign_id": camp["id"], "email": "a@b.c", "state": "nonsense"},
                _notify,
            )
        )


def test_owner_scoping(fresh_db, owner, monkeypatch):
    from zylch.rpc import campaign_actions as ca

    camp = _run(ca.campaign_create({"name": "mine"}, _notify))
    monkeypatch.setattr(ca, "_owner_id", lambda: "someone_else")
    with pytest.raises(ValueError, match="campaign not found"):
        _run(
            ca.campaign_add_contact(
                {"campaign_id": camp["id"], "email": "a@b.c"}, _notify
            )
        )
    assert _run(ca.campaign_list({}, _notify)) == []
