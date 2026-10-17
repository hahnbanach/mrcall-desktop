"""Additional-spend admission against independent real SQLite connections."""

import importlib.util
import json
import random
import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from zylch.llm.budget_pricing import micro_usd
from zylch.storage.models import LlmBillingAuthorization, LlmReservation, LlmUsage

HELPER = Path(__file__).resolve().parents[2] / "scripts/m10_acceptance_budget.py"
spec = importlib.util.spec_from_file_location("acceptance_budget", HELPER)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def make_manifest(directory, amounts=(2_000_000, 2_000_000, 500_000, 500_000)):
    allocations = []
    for index, amount in enumerate(amounts):
        path = directory / f"ledger-{index}.db"
        engine = create_engine(f"sqlite:///{path}")
        for model in (LlmReservation, LlmUsage, LlmBillingAuthorization):
            model.__table__.create(engine)
        engine.dispose()
        stat = path.stat()
        allocations.append(
            dict(
                allocation_id=f"allocation-{index}",
                owner_id="test-owner",
                path=str(path),
                device=stat.st_dev,
                inode=stat.st_ino,
                micro_usd=amount,
            )
        )
    return dict(run_id="acceptance-run", allocations=allocations)


@pytest.fixture
def manifest(tmp_path):
    return make_manifest(tmp_path)


def sql(manifest, statement, args=(), index=0):
    with sqlite3.connect(manifest["allocations"][index]["path"], timeout=30) as conn:
        return conn.execute(statement, args).fetchall()


def reserve(manifest, identity, amount, index=0, age="2026-10-16", owner="test-owner"):
    return sql(
        manifest,
        "INSERT INTO llm_reservations VALUES(?,?,?,?,?,?,?,NULL)",
        (identity, owner, age, "test-model", "direct", "acceptance", amount),
        index,
    )


def usage(manifest, identity, amount, index=0, owner="test-owner", date="2026-10-16"):
    return sql(
        manifest,
        "INSERT INTO llm_usage(id,owner_id,ts,call_site,transport,model,est_cost_usd) VALUES(?,?,?,?,?,?,?)",
        (identity, owner, date, "acceptance", "direct", "test-model", amount),
        index,
    )


def settle(manifest, identity, cost, index=0):
    with sqlite3.connect(manifest["allocations"][index]["path"]) as conn:
        conn.execute(
            "INSERT INTO llm_usage(id,owner_id,ts,call_site,transport,model,est_cost_usd) VALUES(?,?,'2030-01-01','acceptance','direct','test-model',?)",
            (identity, "test-owner", cost),
        )
        conn.execute("UPDATE llm_reservations SET settled_at='2030-01-01' WHERE id=?", (identity,))


def active(manifest, index=0):
    return guard.activate(manifest, f"allocation-{index}", apply=True)


def state(manifest, index=0):
    return guard.inspect(manifest, f"allocation-{index}")


def attempt(args):
    manifest, identity, amount, index = args
    try:
        reserve(manifest, identity, amount, index)
        return True
    except sqlite3.DatabaseError:
        return False


def test_inspection_is_read_only_and_never_initializes(tmp_path, manifest):
    path = Path(manifest["allocations"][0]["path"])
    before = path.read_bytes()
    assert guard.activate(manifest, "allocation-0")["applied"] is False
    assert path.read_bytes() == before
    path.unlink()
    with pytest.raises(guard.Refused, match="Existing database"):
        state(manifest)
    assert not path.exists()


def test_historical_baseline_late_settlement_and_new_unbound_usage(manifest):
    reserve(manifest, "historical-hold", 30_000_000)
    usage(manifest, "historical-usage", 100)
    before = sql(manifest, "SELECT * FROM llm_reservations")
    assert active(manifest)["additional_committed_micro_usd"] == 0
    assert sql(manifest, "SELECT * FROM llm_reservations") == before
    assert state(manifest)["historical_open_max_micro_usd"] == 30_000_000
    settle(manifest, "historical-hold", 29)
    assert state(manifest)["additional_committed_micro_usd"] == 0
    assert state(manifest)["historical_open_count"] == 0
    usage(manifest, "new-unbound", 0.1, date="2000-01-01")
    assert state(manifest)["additional_committed_micro_usd"] == 100002
    assert active(manifest)["resumed"] is True


def test_old_unknown_hold_keeps_maximum_across_midnight_and_days(manifest):
    active(manifest)
    reserve(manifest, "unknown", 2_000_000, age="2000-01-01")
    with pytest.raises(sqlite3.IntegrityError):
        reserve(manifest, "later", 1, age="2035-01-01")
    assert state(manifest)["additional_committed_micro_usd"] == 2_000_000
    settle(manifest, "unknown", 0.01)
    assert state(manifest)["additional_committed_micro_usd"] == 10002
    reserve(manifest, "affordable", 1_989_998)


def test_missing_usage_cannot_close_hold(manifest):
    active(manifest)
    reserve(manifest, "unknown", 2_000_000)
    with pytest.raises(sqlite3.IntegrityError, match="settlement mismatch"):
        sql(manifest, "UPDATE llm_reservations SET settled_at='2030' WHERE id='unknown'")
    assert state(manifest)["remaining_micro_usd"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", "different"),
        ("model", "different"),
        ("transport", "proxy"),
        ("call_site", "different"),
    ],
)
def test_identity_mismatch_never_releases_hold(manifest, field, value):
    reserve(manifest, "old", 100)
    active(manifest)
    usage(manifest, "old", 0.01)
    with pytest.raises(sqlite3.IntegrityError):
        sql(manifest, f"UPDATE llm_usage SET {field}=? WHERE id='old'", (value,))
    with pytest.raises(sqlite3.IntegrityError):
        sql(manifest, f"UPDATE llm_reservations SET {field}=? WHERE id='old'", (value,))


def test_identity_mismatched_late_baseline_receipt_blocks(manifest):
    reserve(manifest, "old", 30_000_000)
    active(manifest)
    usage(manifest, "old", 1, owner="different")
    with pytest.raises(sqlite3.IntegrityError):
        reserve(manifest, "new", 1)
    assert sql(manifest, "SELECT settled_at FROM llm_reservations WHERE id='old'") == [(None,)]


def test_full_overrun_is_recorded_and_prevents_further_admission(manifest):
    active(manifest)
    reserve(manifest, "breach", 10)
    settle(manifest, "breach", 3)
    assert sql(manifest, "SELECT est_cost_usd FROM llm_usage") == [(3.0,)]
    assert state(manifest)["additional_committed_micro_usd"] == 3_000_002
    with pytest.raises(sqlite3.IntegrityError):
        reserve(manifest, "later", 0)
    with pytest.raises(sqlite3.IntegrityError):
        settle(manifest, "breach", 0)
    assert sql(manifest, "SELECT COUNT(*) FROM llm_usage") == [(1,)]


@pytest.mark.parametrize("cost", [None, -1, float("inf"), float("nan"), "bad", 1e30])
def test_invalid_new_usage_remains_recorded_but_blocks_dispatch(manifest, cost):
    active(manifest)
    usage(manifest, "unbound", cost)
    assert sql(manifest, "SELECT COUNT(*) FROM llm_usage") == [(1,)]
    with pytest.raises(sqlite3.IntegrityError):
        reserve(manifest, "next", 1)


def test_historical_invalid_usage_is_reported_separately(manifest):
    usage(manifest, "old-invalid", None)
    assert active(manifest)["historical_invalid_usage_rows"] == 1
    reserve(manifest, "new", 2_000_000)


def test_sql_conversion_never_understates_production_decimal():
    rng = random.Random(1042)
    values = [0, 1e-324, 1e-320, 1e-12, 0.000001, 0.001, 1, 2, 5, 1000000]
    import math

    for value in list(values):
        values.extend((math.nextafter(value, 0), math.nextafter(value, math.inf)))
    values.extend(rng.random() * rng.choice((1e-12, 1e-6, 1, 5, 1000000)) for _ in range(10000))
    with sqlite3.connect(":memory:") as conn:
        for value in values:
            if value > 1000000:
                continue
            actual = conn.execute(
                "SELECT " + guard._SQL.micros(":value"), {"value": value}
            ).fetchone()[0]
            assert micro_usd(value) <= actual <= micro_usd(value) + 2, value


@pytest.mark.parametrize("value", [None, -1, float("nan"), float("inf"), "NaN", "0.1", 1e30])
def test_sql_conversion_invalid_is_unaccountable(value):
    with sqlite3.connect(":memory:") as conn:
        assert (
            conn.execute("SELECT " + guard._SQL.micros(":value"), {"value": value}).fetchone()[0]
            is None
        )


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM llm_usage",
        "DELETE FROM llm_reservations",
        "DELETE FROM _m10_acceptance_usage",
        "DELETE FROM _m10_acceptance_reservations",
        "UPDATE _m10_acceptance_state SET allocation='new'",
        "DELETE FROM _m10_acceptance_objects",
        "DELETE FROM _m10_acceptance_events",
        "UPDATE llm_reservations SET reserved_micro_usd=0",
        "UPDATE llm_usage SET est_cost_usd=0",
    ],
)
def test_ordinary_destructive_changes_refuse(manifest, statement):
    active(manifest)
    reserve(manifest, "hold", 1000)
    usage(manifest, "unbound", 0.01)
    with pytest.raises(sqlite3.IntegrityError):
        sql(manifest, statement)
    assert state(manifest)["additional_committed_micro_usd"] == 11002


@pytest.mark.parametrize(
    "name", ["admit_a", "admit_b", "usage_capture", "state_update", "integrity"]
)
def test_missing_guard_or_view_refuses_from_independent_writer(manifest, name):
    active(manifest)
    kind = "VIEW" if name == "integrity" else "TRIGGER"
    sql(manifest, f"DROP {kind} _m10_acceptance_{name}")
    with pytest.raises((sqlite3.DatabaseError, guard.Refused)):
        reserve(manifest, "new", 1)
    with pytest.raises(guard.Refused):
        active(manifest)


def test_schema_drift_partial_run_and_allocation_changes_refuse(manifest):
    active(manifest)
    modified = json.loads(json.dumps(manifest))
    modified["allocations"][0]["micro_usd"] -= 1
    with pytest.raises(guard.Refused):
        active(modified)
    sql(manifest, "ALTER TABLE llm_usage ADD COLUMN unexpected TEXT")
    with pytest.raises(guard.Refused):
        active(manifest)
    with pytest.raises(sqlite3.DatabaseError):
        reserve(manifest, "new", 1)


def test_activated_copy_different_path_cannot_mint_allowance(manifest, tmp_path):
    active(manifest)
    reserve(manifest, "held", 2_000_000)
    copied = tmp_path / "copied.db"
    shutil.copy2(manifest["allocations"][0]["path"], copied)
    with sqlite3.connect(copied) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO llm_reservations VALUES('new','test-owner','2030','test-model','direct','acceptance',1,NULL)"
        )
    changed = json.loads(json.dumps(manifest))
    changed["allocations"][0].update(
        path=str(copied), device=copied.stat().st_dev, inode=copied.stat().st_ino
    )
    with pytest.raises(guard.Refused):
        active(changed)


def test_partial_activation_rolls_back_atomically(manifest, monkeypatch):
    original = guard._SQL.objects

    def broken(*args):
        result = original(*args)
        result["_m10_acceptance_forced_failure"] = ("trigger", "INVALID SQL")
        return result

    monkeypatch.setattr(guard._SQL, "objects", broken)
    with pytest.raises(sqlite3.DatabaseError):
        active(manifest)
    assert sql(
        manifest, "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE '_m10_acceptance_%'"
    ) == [(0,)]
    monkeypatch.setattr(guard._SQL, "objects", original)
    assert active(manifest)["resumed"] is False


def test_incompatible_partial_run_is_not_reconstructed(manifest):
    sql(manifest, "CREATE TABLE _m10_acceptance_state (bad TEXT)")
    with pytest.raises(guard.Refused):
        active(manifest)


def test_deactivation_retains_baseline_audit_and_cannot_reactivate(manifest):
    active(manifest)
    reserve(manifest, "uncertain", 2_000_000)
    with pytest.raises(guard.Refused, match="Stop and drain"):
        guard.deactivate(manifest, "allocation-0", apply=True)
    result = guard.deactivate(manifest, "allocation-0", apply=True, intake_stopped=True)
    assert result["audit_retained"] is True
    assert state(manifest)["active"] is False
    assert state(manifest)["reactivation_allowed"] is False
    assert sql(manifest, "SELECT COUNT(*) FROM llm_reservations") == [(1,)]
    assert sql(manifest, "SELECT COUNT(*) FROM _m10_acceptance_reservations") == [(1,)]
    with pytest.raises(guard.Refused, match="cannot reset"):
        active(manifest)


def test_invalid_duplicate_and_overbudget_manifests_refuse(manifest):
    manifest["allocations"][1]["allocation_id"] = "allocation-0"
    with pytest.raises(guard.Refused, match="Duplicate"):
        active(manifest)
    manifest["allocations"][1]["allocation_id"] = "allocation-1"
    manifest["allocations"][0]["micro_usd"] += 1
    with pytest.raises(guard.Refused, match="ceiling"):
        active(manifest)


@pytest.mark.parametrize("table", ["llm_reservations", "llm_usage"])
def test_sql_replace_cannot_bypass_delete_triggers(manifest, table):
    active(manifest)
    reserve(manifest, "hold", 2_000_000)
    usage(manifest, "unbound", 0)
    statement = (
        "INSERT OR REPLACE INTO llm_reservations VALUES('hold','test-owner','2000','test-model','direct','acceptance',0,NULL)"
        if table == "llm_reservations"
        else "INSERT OR REPLACE INTO llm_usage(id,owner_id,est_cost_usd) VALUES('unbound','test-owner',0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        sql(manifest, statement)
    assert state(manifest)["additional_committed_micro_usd"] == 2_000_000


def test_small_bound_breach_blocks_even_with_unspent_allocation(manifest):
    active(manifest)
    reserve(manifest, "breach", 1)
    settle(manifest, "breach", 0.001)
    assert state(manifest)["pricing_fault"] is True
    assert state(manifest)["remaining_micro_usd"] == 0
    with pytest.raises(sqlite3.IntegrityError):
        reserve(manifest, "later", 1)


def test_large_overrun_is_reported_in_full(manifest):
    active(manifest)
    reserve(manifest, "breach", 1)
    settle(manifest, "breach", 10)
    assert state(manifest)["additional_committed_micro_usd"] == 10_000_002


@pytest.mark.parametrize("cost", [None, -1, float("inf")])
def test_invalid_bound_receipt_cannot_close_new_maximum(manifest, cost):
    active(manifest)
    reserve(manifest, "unknown", 2_000_000)
    usage(manifest, "unknown", cost)
    with pytest.raises(sqlite3.IntegrityError):
        sql(manifest, "UPDATE llm_reservations SET settled_at='2030' WHERE id='unknown'")
    assert sql(manifest, "SELECT settled_at,reserved_micro_usd FROM llm_reservations") == [
        (None, 2_000_000)
    ]


@pytest.mark.parametrize(
    "removed",
    [
        ("admit_a", "admit_b"),
        ("admit_a", "admit_b", "usage_capture"),
        ("admit_a", "admit_b", "objects_update"),
        ("admit_a", "admit_b", "totals"),
        ("reservations_capture", "admit_a"),
        ("reservations_capture", "admit_b", "usage_no_update"),
    ],
)
@pytest.mark.parametrize("amount", [0, 2_000_000])
def test_multiple_object_drift_refuses_with_effective_insert_guard(manifest, removed, amount):
    active(manifest)
    reserve(manifest, "full-allocation", 2_000_000)
    for name in removed:
        kind = "VIEW" if name == "totals" else "TRIGGER"
        sql(manifest, f"DROP {kind} _m10_acceptance_{name}")
    with pytest.raises(sqlite3.DatabaseError):
        reserve(manifest, "independent-counterexample", amount)
    assert sql(manifest, "SELECT SUM(reserved_micro_usd) FROM llm_reservations") == [(2_000_000,)]
    assert sql(manifest, "SELECT COUNT(*) FROM _m10_acceptance_reservations") == [(1,)]
    with pytest.raises(guard.Refused):
        state(manifest)
    with pytest.raises(guard.Refused):
        active(manifest)


def test_helper_refuses_after_every_effective_insert_guard_is_removed(manifest):
    active(manifest)
    for name in ("admit_a", "admit_b", "reservations_capture"):
        sql(manifest, f"DROP TRIGGER _m10_acceptance_{name}")
    with pytest.raises(guard.Refused):
        state(manifest)
    with pytest.raises(guard.Refused):
        active(manifest)
