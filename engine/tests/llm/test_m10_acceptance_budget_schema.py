"""Independent frozen-schema checks precede replaceable accounting views."""

import sqlite3

import pytest

from .test_m10_acceptance_budget import active, guard, reserve, sql, state
from .test_m10_acceptance_budget import manifest as manifest


def replace_views(manifest):
    sql(manifest, "DROP VIEW _m10_acceptance_integrity")
    sql(manifest, "CREATE VIEW _m10_acceptance_integrity AS SELECT 0 AS invalid")
    sql(manifest, "DROP VIEW _m10_acceptance_totals")
    sql(manifest, "CREATE VIEW _m10_acceptance_totals AS SELECT 0 AS committed")


@pytest.mark.parametrize(
    "removed",
    [
        (),
        ("admit_a", "admit_b"),
        ("admit_a", "reservations_capture"),
        ("admit_b", "reservations_capture"),
    ],
)
@pytest.mark.parametrize("amount", [0, 2_000_000])
def test_replaced_views_refuse_with_each_surviving_insert_guard(manifest, removed, amount):
    active(manifest)
    reserve(manifest, "original-max", 2_000_000)
    guards = sql(
        manifest,
        "SELECT name,sql FROM sqlite_master WHERE name IN ('_m10_acceptance_admit_a','_m10_acceptance_admit_b','_m10_acceptance_reservations_capture') ORDER BY name",
    )
    replace_views(manifest)
    assert (
        sql(
            manifest,
            "SELECT name,sql FROM sqlite_master WHERE name IN ('_m10_acceptance_admit_a','_m10_acceptance_admit_b','_m10_acceptance_reservations_capture') ORDER BY name",
        )
        == guards
    )
    for name in removed:
        sql(manifest, f"DROP TRIGGER _m10_acceptance_{name}")
    with pytest.raises(sqlite3.DatabaseError, match="frozen schema refused"):
        reserve(manifest, "independent-view-counterexample", amount)
    assert sql(manifest, "SELECT SUM(reserved_micro_usd) FROM llm_reservations") == [(2_000_000,)]
    assert sql(manifest, "SELECT COUNT(*) FROM _m10_acceptance_reservations") == [(1,)]
    with pytest.raises(guard.Refused):
        state(manifest)
    with pytest.raises(guard.Refused):
        active(manifest)


@pytest.mark.parametrize("mutation", ["binding-view", "update-guard", "delete-guard"])
def test_binding_indirection_cannot_hide_changed_views(manifest, mutation):
    active(manifest)
    reserve(manifest, "original-max", 2_000_000)
    replace_views(manifest)
    if mutation == "binding-view":
        sql(manifest, "DROP TABLE _m10_acceptance_objects")
        sql(
            manifest,
            "CREATE VIEW _m10_acceptance_objects AS SELECT name,type AS kind,sql FROM sqlite_master WHERE sql IS NOT NULL",
        )
    elif mutation == "update-guard":
        sql(manifest, "DROP TRIGGER _m10_acceptance_objects_update")
        sql(
            manifest,
            "UPDATE _m10_acceptance_objects SET sql=(SELECT sql FROM sqlite_master WHERE sqlite_master.name=_m10_acceptance_objects.name) WHERE name IN ('_m10_acceptance_integrity','_m10_acceptance_totals')",
        )
    else:
        sql(manifest, "DROP TRIGGER _m10_acceptance_objects_delete")
        sql(
            manifest,
            "DELETE FROM _m10_acceptance_objects WHERE name IN ('_m10_acceptance_integrity','_m10_acceptance_totals','_m10_acceptance_objects_delete')",
        )
    with pytest.raises(sqlite3.DatabaseError, match="frozen schema refused"):
        reserve(manifest, "hidden-drift", 0)
    assert sql(manifest, "SELECT SUM(reserved_micro_usd) FROM llm_reservations") == [(2_000_000,)]
