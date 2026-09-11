"""Real SQLite admission without network or provider credentials."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select

from zylch.llm import budget
from zylch.llm.budget_pricing import BudgetError, request_bound
from zylch.storage import database
from zylch.storage.models import LlmReservation, LlmUsage


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "profile.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 20})
    LlmUsage.__table__.create(engine)
    LlmReservation.__table__.create(engine)
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    monkeypatch.delenv("ZYLCH_PROFILE_DIR", raising=False)
    monkeypatch.setenv("OWNER_ID", "immutable-uid")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    yield engine
    engine.dispose()


def request(**extra):
    return {
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hello"}],
        "max_tokens": 100,
        **extra,
    }


def test_atomic_concurrent_admission(ledger, monkeypatch):
    amount = request_bound(request(), "direct")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", str(amount * 3 / 1e6))

    def attempt(_):
        try:
            return budget.reserve(request(), "direct")
        except BudgetError:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(24)))
    assert len([r for r in results if r]) == 3
    snapshot = budget.budget_snapshot("different-email")
    assert snapshot["reserved_usd"] == amount * 3 / 1e6
    assert snapshot["remaining_usd"] == 0


def test_settlement_atomic_idempotent(ledger):
    hold = budget.reserve(request(), "direct")
    usage = {"input_tokens": 50, "output_tokens": 10}
    budget.settle(hold, usage)
    budget.settle(hold, usage)
    state = budget.budget_snapshot("ignored-display-email")
    assert state["reserved_usd"] == 0
    assert state["spent_usd"] == 0.0001
    with ledger.connect() as conn:
        rows = conn.execute(select(LlmUsage.__table__)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["owner_id"] == "immutable-uid"


def test_legacy_email_totals_and_rounding(ledger):
    with ledger.begin() as conn:
        for owner in ("old-email", "new-email"):
            conn.execute(LlmUsage.__table__.insert().values(owner_id=owner, est_cost_usd=0.0000001))
    assert budget.budget_snapshot("immutable-uid")["spent_usd"] == 0.000002


def test_restart_and_midnight_preserve_uncertain_holds(ledger, monkeypatch):
    today = datetime(2026, 9, 11, 23, 59)  # noqa: DTZ001 — database stores naive UTC
    monkeypatch.setattr(budget, "_now", lambda: today)
    hold = budget.reserve(request(), "direct")
    # Fresh engine represents another process/restart on the same database.
    replacement = create_engine(ledger.url)
    monkeypatch.setattr(database, "get_engine", lambda: replacement)
    today += timedelta(minutes=2)
    state = budget.budget_snapshot("new-email")
    assert state["reserved_usd"] == hold.reserved_micro_usd / 1e6
    assert state["resets_at"] == "2026-09-13T00:00:00Z"
    budget.settle(hold, {"input_tokens": 50, "output_tokens": 10})
    assert budget.budget_snapshot("uid")["spent_usd"] == 0.0001
    replacement.dispose()


@pytest.mark.parametrize("raw", ["0", "-1", "NaN", "inf", "garbage"])
def test_invalid_or_zero_budget_blocks(ledger, monkeypatch, raw):
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", raw)
    with pytest.raises(BudgetError):
        budget.reserve(request(), "direct")


def test_missing_ledger_refuses(tmp_path, monkeypatch):
    empty = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    monkeypatch.setattr(database, "get_engine", lambda: empty)
    monkeypatch.setenv("OWNER_ID", "uid")
    with pytest.raises(BudgetError, match="ledger"):
        budget.reserve(request(), "direct")
    empty.dispose()


@pytest.mark.parametrize(
    "usage",
    [
        {},
        {"input_tokens": 1},
        {"input_tokens": -1, "output_tokens": 0},
        {"input_tokens": 0, "output_tokens": "4"},
    ],
)
def test_invalid_usage_preserves_hold(ledger, usage):
    hold = budget.reserve(request(), "direct")
    with pytest.raises(BudgetError):
        budget.settle(hold, usage)
    assert budget.budget_snapshot("uid")["reserved_usd"] > 0


def test_settlement_insert_failure_rolls_back(ledger):
    hold = budget.reserve(request(), "direct")
    with ledger.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TRIGGER no_usage BEFORE INSERT ON llm_usage BEGIN SELECT RAISE(ABORT, 'test'); END"
        )
    with pytest.raises(BudgetError):
        budget.settle(hold, {"input_tokens": 1, "output_tokens": 1})
    assert budget.budget_snapshot("uid")["reserved_usd"] > 0
    assert budget.budget_snapshot("uid")["spent_usd"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "unknown"},
        {"service_tier": "auto"},
        {"speed": "fast"},
        {"stream": True},
        {"tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]},
        {"messages": [{"role": "user", "content": [{"type": "image", "source": {}}]}]},
    ],
)
def test_unpriced_shapes_refused(ledger, kwargs):
    with pytest.raises(BudgetError):
        budget.reserve(request(**kwargs), "direct")


def test_proxy_requires_markup_pricing(ledger):
    with pytest.raises(BudgetError, match="markup"):
        budget.reserve(request(), "proxy")


def test_large_request_refused(ledger):
    with pytest.raises(BudgetError, match="200000-token"):
        budget.reserve(request(messages=[{"role": "user", "content": "x" * 3_000_000}]), "direct")


def test_missing_identity_refuses(ledger, monkeypatch):
    monkeypatch.delenv("OWNER_ID")
    with pytest.raises(BudgetError, match="identity"):
        budget.reserve(request(), "direct")


def _process_attempt(database_url, cap, queue):
    """Independent engine and connection, not an inherited transaction."""
    import os

    engine = create_engine(database_url, connect_args={"timeout": 20})
    database.get_engine = lambda: engine
    os.environ["OWNER_ID"] = "immutable-uid"
    os.environ["LLM_DAILY_BUDGET_USD"] = cap
    try:
        budget.reserve(request(), "direct")
        queue.put(True)
    except BudgetError:
        queue.put(False)
    finally:
        engine.dispose()


def test_independent_processes_share_allowance(ledger):
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    cap = str(request_bound(request(), "direct") * 2 / 1e6)
    processes = [
        ctx.Process(target=_process_attempt, args=(str(ledger.url), cap, queue)) for _ in range(4)
    ]
    for process in processes:
        process.start()
    outcomes = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    assert sum(outcomes) == 2


def test_changed_identity_does_not_reset_profile_budget(ledger, monkeypatch):
    amount = request_bound(request(), "direct")
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", str(amount / 1e6))
    budget.reserve(request(), "direct")
    monkeypatch.setenv("OWNER_ID", "changed-identity")
    with pytest.raises(BudgetError):
        budget.reserve(request(), "direct")


def test_corrupt_historical_cost_blocks(ledger):
    with ledger.begin() as conn:
        conn.execute(LlmUsage.__table__.insert().values(owner_id="old-email", est_cost_usd=-1))
    with pytest.raises(BudgetError):
        budget.reserve(request(), "direct")


def test_cache_writes_settle_conservatively(ledger):
    hold = budget.reserve(request(), "direct")
    budget.settle(
        hold,
        {
            "input_tokens": 0,
            "output_tokens": 1,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 1,
        },
    )
    assert budget.budget_snapshot("uid")["spent_usd"] == 0.000206


def test_live_profile_budget_beats_stale_environment(ledger, monkeypatch, tmp_path):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "5")
    settings = tmp_path / ".env"
    settings.write_text("LLM_DAILY_BUDGET_USD=5\n")
    budget.reserve(request(), "direct")
    settings.write_text("LLM_DAILY_BUDGET_USD=0\n")
    with pytest.raises(BudgetError):
        budget.reserve(request(), "direct")
    assert budget.budget_snapshot("uid")["budget_usd"] == 0


def test_profile_missing_setting_uses_default_not_ambient(ledger, monkeypatch, tmp_path):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_DAILY_BUDGET_USD", "999")
    (tmp_path / ".env").write_text("OWNER_ID=uid\n")
    assert budget.budget_snapshot("uid")["budget_usd"] == 10


def test_unreadable_profile_refuses(ledger, monkeypatch, tmp_path):
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path / "missing"))
    with pytest.raises(BudgetError, match="saved budget"):
        budget.reserve(request(), "direct")


def test_standard_tier_admitted_priority_retains_hold(ledger):
    hold = budget.reserve(request(service_tier="standard_only"), "direct")
    with pytest.raises(BudgetError, match="service-tier"):
        budget.settle(hold, {"input_tokens": 1, "output_tokens": 1, "service_tier": "priority"})
    assert budget.budget_snapshot("uid")["reserved_usd"] > 0


def test_output_included_in_context_bound(ledger):
    with pytest.raises(BudgetError, match="200000-token"):
        budget.reserve(
            request(
                model="claude-sonnet-4-5",
                max_tokens=100000,
                messages=[{"role": "user", "content": "x" * 100000}],
            ),
            "direct",
        )


def test_other_process_stale_cap_cannot_override_saved_pause(ledger, monkeypatch, tmp_path):
    import multiprocessing

    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(tmp_path))
    (tmp_path / ".env").write_text("LLM_DAILY_BUDGET_USD=0\n")
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    child = ctx.Process(target=_process_attempt, args=(str(ledger.url), "5", queue))
    child.start()
    assert queue.get(timeout=30) is False
    child.join(timeout=30)
    assert child.exitcode == 0


def test_malformed_saved_budget_does_not_default_open(tmp_path, monkeypatch):
    from zylch.llm.budget import _budget

    profile = tmp_path / "malformed-profile"
    profile.mkdir()
    (profile / ".env").write_text('LLM_DAILY_BUDGET_USD="0\n')
    monkeypatch.setenv("ZYLCH_PROFILE_DIR", str(profile))
    with pytest.raises(BudgetError, match="malformed"):
        _budget()


def test_bound_breach_persists_across_midnight_and_restart(ledger, monkeypatch):
    from datetime import timedelta

    from zylch.llm import budget
    from zylch.storage import database

    request = {
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    reservation = budget.reserve(request, "direct")
    with pytest.raises(BudgetError, match="exceeded"):
        budget.settle(reservation, {"input_tokens": 100000, "output_tokens": 1})
    assert budget.budget_snapshot("uid")["pricing_fault"] is True
    tomorrow = budget._now() + timedelta(days=1)
    monkeypatch.setattr(budget, "_now", lambda: tomorrow)
    ledger.dispose()
    reopened = create_engine(ledger.url)
    monkeypatch.setattr(database, "get_engine", lambda: reopened)
    with pytest.raises(BudgetError, match="reconciliation"):
        budget.reserve(request, "direct")
    assert budget.budget_snapshot("uid")["remaining_usd"] == 0
