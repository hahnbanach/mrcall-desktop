"""Persisted purpose and account fairness under real RPC/HTTP scan caps."""

from datetime import timedelta

import pytest

from zylch.qonto import repository, sync
from zylch.qonto.amounts import utc
from zylch.qonto.models import QontoSyncWindow, QontoTransaction
from zylch.storage import database as dbm

from .test_sync import STARTED, manual, raw


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(sync, "now", lambda: STARTED)


def accounts(api, count):
    prototype = api.organization["bank_accounts"][0]
    ids = [f"account-{index:03}" for index in range(count)]
    api.organization["bank_accounts"] = [{**prototype, "id": key, "name": key} for key in ids]
    return ids


def latest(ids):
    return [
        {
            **raw(
                "latest-" + key,
                emitted="2020-01-01T00:00:00Z",
                updated=utc(STARTED + timedelta(minutes=1)),
            ),
            "bank_account_id": key,
        }
        for key in ids
    ]


def test_history_progress_and_latest_account_updates_with_over_96_maintenance_windows(
    env, http_api, monkeypatch
):
    ids = accounts(http_api, 33)
    result = env.connect(account_ids=ids)["result"]["initial_sync"]
    remaining = result["remaining_backfill_windows"]
    assert remaining == 33 * 30 - 96
    http_api.rows = latest(ids)
    counts = []
    for index in range(4):
        monkeypatch.setattr(sync, "now", lambda index=index: STARTED + timedelta(minutes=index + 2))
        if index == 1:
            dbm.dispose_engine()
            dbm.init_db()
        result = manual(env)
        assert result["requests"] == 96
        assert result["remaining_backfill_windows"] < remaining
        remaining = result["remaining_backfill_windows"]
        counts.append(remaining)
    with repository.profile_transaction() as session:
        assert {row.account_id for row in session.query(QontoTransaction).all()} == set(ids)
        assert (
            session.query(QontoSyncWindow).filter_by(purpose="recent", status="completed").count()
            >= 33
        )
        assert (
            session.query(QontoSyncWindow)
            .filter_by(purpose="incremental", status="completed")
            .count()
            >= 33
        )
        assert all(
            row.completed_at
            for row in session.query(QontoSyncWindow).filter(QontoSyncWindow.attempts > 0)
        )
    assert counts == sorted(counts, reverse=True)


def test_reopened_pending_repairs_rotate_accounts_without_starving_history(
    env, http_api, monkeypatch
):
    ids = accounts(http_api, 33)
    old = utc(STARTED - timedelta(days=29, hours=23))
    http_api.rows = [
        {
            **raw("pending-" + key, emitted=old, updated=old, status="pending"),
            "bank_account_id": key,
        }
        for key in ids
    ]
    remaining = env.connect(account_ids=ids)["result"]["initial_sync"]["remaining_backfill_windows"]
    with repository.profile_transaction() as session:
        assert session.query(QontoTransaction).count() == 33
    monkeypatch.setattr(sync, "now", lambda: STARTED + timedelta(minutes=1))
    remaining = manual(env)["remaining_backfill_windows"]
    http_api.rows = [{**row, "status": "reversed"} for row in http_api.rows] + latest(ids)
    for index in range(3):
        monkeypatch.setattr(sync, "now", lambda index=index: STARTED + timedelta(minutes=index + 2))
        result = manual(env)
        assert result["remaining_backfill_windows"] < remaining
        remaining = result["remaining_backfill_windows"]
    with repository.profile_transaction() as session:
        pending = (
            session.query(QontoTransaction)
            .filter(QontoTransaction.transaction_id.like("pending-%"))
            .all()
        )
        assert len(pending) == 33 and {row.status for row in pending} == {"reversed"}
        latest_rows = (
            session.query(QontoTransaction)
            .filter(QontoTransaction.transaction_id.like("latest-%"))
            .all()
        )
        assert {row.account_id for row in latest_rows} == set(ids)
        repairs = (
            session.query(QontoSyncWindow).filter_by(purpose="pending", status="completed").all()
        )
        assert {row.account_id for row in repairs} == set(ids)
        assert any(row.attempts > 1 for row in repairs)


def test_purpose_and_account_rotation_survive_two_request_cap(env, http_api, monkeypatch):
    ids = accounts(http_api, 3)
    monkeypatch.setattr(sync, "MAX_REQUESTS", 2)
    initial = env.connect(account_ids=ids)["result"]["initial_sync"]["remaining_backfill_windows"]
    http_api.rows = latest(ids)
    for index in range(9):
        monkeypatch.setattr(sync, "now", lambda index=index: STARTED + timedelta(minutes=index + 2))
        result = manual(env)
        assert result["requests"] <= 2
        if index == 3:
            dbm.dispose_engine()
            dbm.init_db()
    assert result["remaining_backfill_windows"] < initial
    with repository.profile_transaction() as session:
        assert {row.account_id for row in session.query(QontoTransaction).all()} == set(ids)
        for purpose in ("incremental", "recent", "initial"):
            attempted = (
                session.query(QontoSyncWindow)
                .filter(QontoSyncWindow.purpose == purpose, QontoSyncWindow.attempts > 0)
                .all()
            )
            assert {row.account_id for row in attempted} == set(ids)


def test_reopened_early_pending_days_do_not_starve_later_days_under_request_cap(
    env, http_api, monkeypatch
):
    http_api.rows = [
        raw(
            str(index),
            emitted=utc(STARTED - timedelta(days=20 - index)),
            updated=utc(STARTED - timedelta(days=20 - index)),
            status="pending",
        )
        for index in range(12)
    ]
    assert env.connect()["result"]["initial_sync"]["status"] == "completed"
    http_api.rows[-1]["status"] = "reversed"
    monkeypatch.setattr(sync, "MAX_REQUESTS", 2)
    for index in range(18):
        monkeypatch.setattr(sync, "now", lambda index=index: STARTED + timedelta(minutes=index + 1))
        assert manual(env)["requests"] <= 2
    with repository.profile_transaction() as session:
        late = session.query(QontoTransaction).filter_by(transaction_id="11").one()
        assert late.status == "reversed"
        attempted = (
            session.query(QontoSyncWindow)
            .filter(QontoSyncWindow.purpose == "pending", QontoSyncWindow.attempts > 0)
            .count()
        )
        assert attempted == 12


def test_page_budget_does_not_always_interrupt_the_same_purpose(env, http_api, monkeypatch):
    import hashlib
    import httpx
    from zylch.qonto.amounts import instant

    def paged(request):
        if not request.url.path.endswith("transactions"):
            return None
        query = request.url.params
        basis = query["sort_by"].split(":")[0]
        value = utc(instant(query[basis + "_from"]) + timedelta(minutes=1))
        window = hashlib.sha256((basis + query[basis + "_from"]).encode()).hexdigest()
        page = int(query["page"])
        rows = [
            raw(window + str(index), emitted=value, updated=value, status="pending")
            for index in range((page - 1) * 100, min(page * 100, 150))
        ]
        return httpx.Response(
            200,
            json={
                "transactions": rows,
                "meta": {
                    "current_page": page,
                    "next_page": 2 if page == 1 else None,
                    "total_pages": 2,
                    "total_count": 150,
                    "per_page": 100,
                },
            },
        )

    http_api.callback = paged
    monkeypatch.setattr(sync, "MAX_REQUESTS", 1)
    initial = env.connect()["result"]["initial_sync"]["remaining_backfill_windows"]
    with repository.profile_transaction() as session:
        session.query(QontoSyncWindow).filter_by(status="partial").one().retry_at = 0
    monkeypatch.setattr(sync, "MAX_REQUESTS", 7)
    for index in range(4):
        monkeypatch.setattr(sync, "now", lambda index=index: STARTED + timedelta(minutes=index + 2))
        result = manual(env)
        assert result["requests"] <= 7
        with repository.profile_transaction() as session:
            session.query(QontoSyncWindow).filter_by(status="partial").update({"retry_at": 0})
    assert result["remaining_backfill_windows"] < initial
    with repository.profile_transaction() as session:
        for purpose in ("incremental", "recent", "pending", "initial"):
            assert (
                session.query(QontoSyncWindow)
                .filter_by(purpose=purpose, status="completed")
                .count()
            )
