"""Durable source coverage through real dispatch and HTTP transport fixtures."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from zylch.qonto import repository, sync
from zylch.qonto.amounts import utc
from zylch.qonto.models import QontoAccount, QontoConnection, QontoSyncWindow, QontoTransaction
from zylch.storage import database as dbm

STARTED = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def raw(
    key="movement",
    *,
    emitted="2026-10-03T13:00:00Z",
    updated="2026-10-03T12:00:00Z",
    status="completed",
    amount="0.43",
):
    return dict(
        transaction_id=key,
        id="provider-" + key,
        bank_account_id="account-eur",
        amount=amount,
        amount_cents=int(float(amount) * 100),
        currency="EUR",
        local_amount="0.35",
        local_amount_cents=35,
        local_currency="GBP",
        side="debit",
        status=status,
        emitted_at=emitted,
        settled_at=None,
        updated_at=updated,
        label="Fixture movement",
        attachment_ids=["excluded"],
    )


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(sync, "now", lambda: STARTED)


def transactions():
    with repository.profile_transaction() as session:
        return session.query(QontoTransaction).all()


def manual(env):
    response = env.rpc("qonto.sync")
    assert "result" in response, response
    return response["result"]


def test_initial_daily_utc_multipage_idempotent_and_original_currency(env, http_api):
    http_api.rows = [raw(str(i)) for i in range(205)]
    result = env.connect()["result"]["initial_sync"]
    assert result["status"] == "completed" and result["requests"] == 32
    assert len(transactions()) == 205
    row = transactions()[0]
    assert row.amount_minor == 43 and row.original_amount_minor == 35
    assert row.original_currency == "GBP" and row.settled_at is None
    assert not hasattr(row, "attachment_ids")
    before = {row.source_id: (row.source_revision, row.retrieved_at) for row in transactions()}
    result = manual(env)
    assert result["status"] == "completed"
    assert before == {
        row.source_id: (row.source_revision, row.retrieved_at) for row in transactions()
    }
    emitted = [
        request
        for request in http_api.requests
        if request.url.path.endswith("transactions")
        and request.url.params["sort_by"] == "emitted_at:asc"
    ]
    assert emitted[0].url.params["emitted_at_from"] == "2026-09-04T12:00:00.000000Z"
    assert emitted[0].url.params["emitted_at_to"] == "2026-09-05T12:00:00.000000Z"
    assert result["accounts"][0]["updated_watermark"] == utc(STARTED)


def test_partial_page_failure_restart_from_page_one_and_no_watermark(env, http_api):
    http_api.rows = [raw(str(i)) for i in range(150)]

    def fail(request):
        if request.url.path.endswith("transactions") and request.url.params["page"] == "2":
            return httpx.Response(503)

    http_api.callback = fail
    result = env.connect()["result"]["initial_sync"]
    assert result["status"] == "partial" and result["error"] == "network"
    assert len(transactions()) == 100
    with repository.profile_transaction() as session:
        row = session.query(QontoSyncWindow).filter_by(status="partial").one()
        assert row.next_page == 2 and row.observed_count == 100 and not row.completed_at
        account = session.query(QontoAccount).one()
        assert account.updated_watermark is None
        row.retry_at = 0
    dbm.dispose_engine()
    dbm.init_db()
    http_api.callback = None
    before = len(http_api.requests)
    assert manual(env)["status"] == "completed"
    assert len(transactions()) == 150
    replay = [
        r
        for r in http_api.requests[before:]
        if r.url.params.get("emitted_at_from") == "2026-10-03T12:00:00.000000Z"
    ]
    assert replay[0].url.params["page"] == "1"


def test_updated_watermark_has_overlap_no_emitted_filter_and_old_revisions(
    env, http_api, monkeypatch
):
    env.connect()
    monkeypatch.setattr(sync, "now", lambda: STARTED + timedelta(hours=2))
    http_api.rows = [
        raw(emitted="2020-01-01T00:00:00Z", updated="2026-10-04T13:00:00Z", status="reversed")
    ]
    result = manual(env)
    assert result["status"] == "completed"
    assert transactions()[0].status == "reversed"
    updated = [r for r in http_api.requests if r.url.params.get("sort_by") == "updated_at:asc"][-1]
    assert updated.url.params["updated_at_from"] == "2026-10-02T12:00:00.000000Z"
    assert "emitted_at_from" not in updated.url.params
    http_api.rows[0].update(updated_at="2026-10-04T12:30:00Z", status="completed")
    manual(env)
    assert transactions()[0].status == "reversed"
    http_api.rows[0].update(updated_at="2026-10-04T13:00:00Z", status="completed")
    manual(env)
    assert transactions()[0].status == "completed"


def test_rate_limit_persists_eligibility_no_automatic_retry(env, http_api):
    def limit(request):
        if request.url.path.endswith("transactions"):
            return httpx.Response(429, headers={"Retry-After": "3600"}, text="private")

    http_api.callback = limit
    result = env.connect()["result"]["initial_sync"]
    assert result["error"] == "rate_limited" and result["remaining_backfill_windows"] == 30
    with repository.profile_transaction() as session:
        row = session.query(QontoSyncWindow).filter_by(status="partial").one()
        assert row.retry_at - row.retrieved_at if row.retrieved_at else row.retry_at
        assert row.attempts == 1 and row.observed_count == 0
        assert session.query(QontoAccount).one().updated_watermark is None
    http_api.callback = None
    result = manual(env)
    assert result["status"] == "partial" and result["retry_at"]
    with repository.profile_transaction() as session:
        row = session.query(QontoSyncWindow).filter_by(status="partial").one()
        assert row.attempts == 1
        row.retry_at = 0
        session.query(QontoConnection).one().provider_retry_at = 0
    assert manual(env)["status"] == "completed"


def test_moving_totals_retried_bounded_partial_then_recover(env, http_api):
    http_api.rows = [raw(str(i)) for i in range(150)]
    second_pages = []

    def move(request):
        if request.url.path.endswith("transactions") and request.url.params["page"] == "2":
            second_pages.append(request)
            return httpx.Response(
                200,
                json={
                    "transactions": http_api.rows[100:],
                    "meta": {
                        "current_page": 2,
                        "next_page": None,
                        "total_pages": 2,
                        "total_count": 151,
                        "per_page": 100,
                    },
                },
            )

    http_api.callback = move
    result = env.connect()["result"]["initial_sync"]
    assert result["status"] == "partial" and result["error"] == "pagination_changed"
    assert len(second_pages) == 2 and len(transactions()) == 100
    with repository.profile_transaction() as session:
        row = session.query(QontoSyncWindow).filter_by(status="partial").one()
        assert row.attempts == 2 and row.completed_at is None
        row.retry_at = 0
    http_api.callback = None
    assert manual(env)["status"] == "completed"
    assert len(transactions()) == 150


@pytest.mark.parametrize("next_page", ["2", True, 1, "https://evil.test/page", 51])
def test_invalid_paging_has_no_cursor_advance(env, http_api, next_page):
    def invalid(request):
        if request.url.path.endswith("transactions"):
            return httpx.Response(
                200,
                json={
                    "transactions": [],
                    "meta": {
                        "current_page": 1,
                        "next_page": next_page,
                        "total_pages": 2,
                        "total_count": 150,
                    },
                },
            )

    http_api.callback = invalid
    result = env.connect()["result"]["initial_sync"]
    assert result["status"] == "partial" and result["error"] == "invalid_response"
    assert not transactions()
    with repository.profile_transaction() as session:
        assert session.query(QontoAccount).one().updated_watermark is None


def test_pending_repair_rotation_revisits_completed_days(env, http_api, monkeypatch):
    http_api.rows = [
        raw(
            str(i),
            emitted=utc(STARTED - timedelta(days=20 - i)),
            updated=utc(STARTED - timedelta(days=20 - i)),
            status="pending",
        )
        for i in range(12)
    ]
    env.connect()
    manual(env)
    http_api.rows[10]["status"] = "completed"
    http_api.rows[0]["status"] = "reversed"
    monkeypatch.setattr(sync, "now", lambda: STARTED + timedelta(minutes=1))
    manual(env)
    assert {row.transaction_id: row.status for row in transactions()}["10"] == "completed"
    assert {row.transaction_id: row.status for row in transactions()}["0"] == "reversed"
    http_api.rows[1]["status"] = "completed"
    manual(env)
    assert {row.transaction_id: row.status for row in transactions()}["1"] == "completed"
    repaired = [
        r
        for r in http_api.requests
        if r.url.params.get("emitted_at_from")
        == utc((STARTED - timedelta(days=20)).replace(hour=0))
    ]
    assert len(repaired) >= 2


def test_sync_single_flight_and_disconnect_fences_blocked_http(env, http_api):
    env.connect()

    async def scenario():
        waiting, released = asyncio.Event(), asyncio.Event()

        async def blocked(request):
            if request.url.path.endswith("transactions"):
                waiting.set()
                await released.wait()
                return httpx.Response(
                    200,
                    json={
                        "transactions": [raw()],
                        "meta": {
                            "current_page": 1,
                            "next_page": None,
                            "total_pages": 1,
                            "total_count": 1,
                        },
                    },
                )

        http_api.callback = blocked
        task = asyncio.create_task(env.arpc("qonto.sync"))
        await waiting.wait()
        busy = await env.arpc("qonto.sync")
        assert busy["error"]["message"].split(":", 1)[0] == "busy"
        disconnected = await env.arpc("qonto.disconnect")
        assert disconnected["result"]["status"] == "disconnected"
        released.set()
        return await task

    result = asyncio.run(scenario())
    assert result["error"]["message"].split(":", 1)[0] == "generation_changed"
    assert not transactions()
    with repository.profile_transaction() as session:
        assert session.query(QontoConnection).one().sync_token is None


def test_auth_failure_erases_app_credentials_and_org_mismatch_blocks_rows(env, http_api):
    env.connect()
    http_api.organization["id"] = "other-company"
    assert env.rpc("qonto.sync")["error"]["message"].split(":", 1)[0] == "binding_changed"
    assert not transactions()
    http_api.callback = lambda _: httpx.Response(401)
    assert env.rpc("qonto.sync")["error"]["message"].split(":", 1)[0] == "auth"
    with repository.profile_transaction() as session:
        row = session.query(QontoConnection).one()
        assert row.status == "auth_failed" and row.encrypted_credentials is None


def test_null_dates_all_statuses_distinct_accounts_and_bounded_work(env, http_api, monkeypatch):
    http_api.rows = [
        raw(str(i), emitted=None, updated=None, status=status)
        for i, status in enumerate(("pending", "completed", "declined", "reversed"))
    ]
    monkeypatch.setattr(sync, "MAX_REQUESTS", 2)
    result = env.connect()["result"]["initial_sync"]
    assert result["status"] == "partial" and result["requests"] == 2
    assert {row.status for row in transactions()} == {
        "pending",
        "completed",
        "declined",
        "reversed",
    }
    assert all(row.emitted_at is None for row in transactions())


def test_connection_throttle_blocks_all_early_http_requests_across_restart(env, http_api):
    def limit(request):
        if request.url.path.endswith("transactions"):
            return httpx.Response(429, headers={"Retry-After": "3600"})

    http_api.callback = limit
    assert env.connect()["result"]["initial_sync"]["error"] == "rate_limited"
    before = len(http_api.requests)
    dbm.dispose_engine()
    dbm.init_db()
    http_api.callback = None
    result = manual(env)
    assert result["status"] == "partial" and result["requests"] == 0
    assert len(http_api.requests) == before
    with repository.profile_transaction() as session:
        session.query(QontoConnection).one().provider_retry_at = 0
        session.query(QontoSyncWindow).filter_by(status="partial").one().retry_at = 0
    assert manual(env)["status"] == "completed"


@pytest.mark.parametrize("code,outcome", [(503, "network"), (429, "rate_limited")])
def test_initial_probe_failure_remains_partial_after_restart(env, http_api, code, outcome):
    organizations = []

    def fail_initial_probe(request):
        if request.url.path.endswith("organization"):
            organizations.append(request)
            if len(organizations) == 3:
                return httpx.Response(code, headers={"Retry-After": "3600"})

    http_api.callback = fail_initial_probe
    result = env.connect()["result"]["initial_sync"]
    assert result["status"] == "partial" and result["error"] == outcome
    assert result["remaining_backfill_windows"] == 30
    assert not result["history_planned"]
    dbm.dispose_engine()
    dbm.init_db()
    status = env.rpc("qonto.status")["result"]["sync"]
    assert status["status"] == "partial" and status["remaining_backfill_windows"] == 30
    http_api.callback = None
    with repository.profile_transaction() as session:
        session.query(QontoConnection).one().provider_retry_at = 0
    assert manual(env)["status"] == "completed"


def test_source_sync_leaves_real_paid_ledger_unchanged(env, http_api):
    import json
    from sqlalchemy import text

    with dbm.get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO llm_reservations (id, owner_id, created_at, model, transport, call_site, reserved_micro_usd) VALUES ('existing', :uid, '2026-10-01', 'fixture', 'direct', 'fixture', 1234)"
            ),
            {"uid": "fixtureFirebaseUid"},
        )
        conn.execute(
            text(
                "INSERT INTO llm_billing_authorizations (reservation_id, quote) VALUES ('existing', :quote)"
            ),
            {"quote": json.dumps({"fixture": "keep"})},
        )

    def ledger():
        with dbm.get_engine().begin() as conn:
            return [
                conn.exec_driver_sql("SELECT * FROM " + name).fetchall()
                for name in ("llm_reservations", "llm_billing_authorizations")
            ]

    before = ledger()
    http_api.rows = [raw()]
    assert env.connect()["result"]["ok"]
    manual(env)
    assert ledger() == before


def test_profile_additive_source_migration_preserves_m1_binding_and_rows(env):
    import sqlite3

    assert env.connect()["result"]["ok"]
    before = repository.read_binding("fixtureFirebaseUid")
    additions = {
        "qonto_connections": ("sync_token", "sync_expires_at", "last_sync_at", "provider_retry_at"),
        "qonto_accounts": (
            "balance_provider_at",
            "authorized_balance_minor",
            "authorized_balance_scale",
            "authorized_balance_decimal",
            "initial_from",
            "initial_to",
            "emitted_watermark",
            "updated_watermark",
            "pending_repair_cursor",
        ),
        "qonto_sync_windows": (
            "observed_count",
            "total_count",
            "total_pages",
            "attempts",
            "retry_at",
            "purpose",
        ),
    }
    dbm.dispose_engine()
    with sqlite3.connect(env.directory / "zylch.db") as conn:
        for table, columns in additions.items():
            for column in columns:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.execute("DELETE FROM schema_version WHERE id='0004_qonto_source_sync'")
    dbm.init_db()
    assert repository.read_binding("fixtureFirebaseUid") == before
    with repository.profile_transaction() as session:
        assert session.query(QontoAccount).count() == 1
    dbm.init_db()
    assert repository.read_binding("fixtureFirebaseUid") == before


def test_numeric_json_money_distinct_account_identity_and_independent_balances(env, http_api):
    http_api.organization["bank_accounts"][0].update(balance=0.43, balance_cents=43)
    http_api.rows = [
        raw("same-provider-id", amount="100.00"),
        {
            **raw("same-provider-id", amount="0.10"),
            "bank_account_id": "account-gbp",
            "currency": "GBP",
            "local_currency": "USD",
            "local_amount": 0.35,
        },
    ]
    http_api.rows[0]["amount"] = 100.0
    http_api.rows[1]["amount"] = 0.1
    result = env.connect(account_ids=["account-eur", "account-gbp"])["result"]
    assert result["initial_sync"]["status"] == "completed"
    assert len(transactions()) == 2
    assert len({row.source_id for row in transactions()}) == 2
    assert {row.currency for row in transactions()} == {"EUR", "GBP"}
    with repository.profile_transaction() as session:
        eur = session.query(QontoAccount).filter_by(account_id="account-eur").one()
        assert eur.balance_minor == 43 and eur.balance_minor != 10000
        assert eur.authorized_balance_minor == 9900


def test_cancellation_replays_running_window_from_page_one(env, http_api):
    env.connect()
    http_api.rows = [raw(str(i)) for i in range(150)]

    async def scenario():
        waiting = asyncio.Event()

        async def block_second_page(request):
            if request.url.path.endswith("transactions") and request.url.params["page"] == "2":
                waiting.set()
                await asyncio.Event().wait()

        http_api.callback = block_second_page
        task = asyncio.create_task(env.arpc("qonto.sync"))
        await asyncio.wait_for(waiting.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(transactions()) == 100
    with repository.profile_transaction() as session:
        assert session.query(QontoSyncWindow).filter_by(status="running").count() == 1
        assert session.query(QontoConnection).one().sync_token is None
    http_api.callback = None
    before = len(http_api.requests)
    assert manual(env)["status"] == "completed"
    assert len(transactions()) == 150
    assert http_api.requests[before + 1].url.params["page"] == "1"
