"""The standalone table gate, `gates.check_table_standalone`: the one the billing server mirrors.

A consumer without `requirements.json` takes the roster and the ceilings
from the table, and the excluded families (beside the margin, the
quantizations and the excluded endpoint tiers) from the snapshot's `policy`
(`contract/README.md`). These cases run on the contract's examples: each
rule the standalone gate applies rejects a table crafted to break it, a
family named only by the snapshot's policy included, and the one rule it
cannot apply — a raised ceiling — passes it and fails `check_table`.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from zylch.llm.roles import gates

CONTRACT = Path(gates.__file__).resolve().parent / "contract"
HAIKU, SONNET = "anthropic/claude-haiku-4.5", "anthropic/claude-sonnet-5.5"
QWEN, K3 = "qwen/qwen3.8-max-0902", "moonshotai/kimi-k3"
REQUIREMENTS = {
    "presets": {"economy": {"ceiling": 10}, "balanced": {"ceiling": 20}},
    "roles": {"CHAT": {}, "MNEMONIC": {}},
    "excluded_families": [{"vendor": "anthropic", "token": "haiku"}],
}


def load(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


@pytest.fixture
def snapshot() -> dict:
    return load("snapshot.example.json")


@pytest.fixture
def table() -> dict:
    return load("table.example.json")


def restamped(doc: dict, change) -> dict:
    """`doc` changed by `change` and stamped again, so only the change fails."""
    copied = copy.deepcopy(doc)
    change(copied)
    return gates.stamped(copied)


def standalone(table: dict, snapshot: dict) -> list[str]:
    with pytest.raises(gates.GateError) as failed:
        gates.check_table_standalone(table, snapshot)
    return failed.value.violations


def ranking(table: dict, preset: str = "balanced", role: str = "CHAT") -> list:
    return table["presets"][preset]["roles"][role]["ranking"]


def test_the_examples_pass_and_the_snapshot_names_the_families(table, snapshot):
    gates.check_table_standalone(table, snapshot)
    assert snapshot["policy"]["excluded_families"] == [{"vendor": "anthropic", "token": "haiku"}]


def test_a_ranked_id_of_a_family_the_snapshot_names_fails(table, snapshot):
    priced = restamped(snapshot, lambda s: s["models"].update({HAIKU: s["models"][SONNET]}))
    ranked = restamped(table, lambda t: ranking(t).append({"id": HAIKU, "direct_id": None}))
    assert standalone(ranked, priced) == [
        f"balanced / CHAT / ranking: {HAIKU} is of the excluded family anthropic + haiku"
    ]
    # The families are the snapshot's: a policy without them lets the same table pass.
    unfenced = restamped(priced, lambda s: s["policy"].update(excluded_families=[]))
    gates.check_table_standalone(ranked, unfenced)


def test_coverage_is_over_the_tables_own_roster(table, snapshot):
    def economy_only(t):
        t["presets"]["economy"]["roles"]["NEW"] = copy.deepcopy(
            t["presets"]["economy"]["roles"]["CHAT"]
        )

    assert standalone(restamped(table, economy_only), snapshot) == [
        "coverage: balanced / NEW has no ranking"
    ]
    emptied = restamped(table, lambda t: ranking(t, "economy").clear())
    assert standalone(emptied, snapshot) == ["coverage: economy / CHAT has no ranking"]

    def no_roles(t):
        for body in t["presets"].values():
            body["roles"] = {}

    for nothing in (restamped(table, no_roles), restamped(table, lambda t: t.update(presets={}))):
        assert standalone(nothing, snapshot) == ["coverage: the table ranks no role"]


def test_the_tables_own_ceilings_bound_the_prices_and_a_raise_needs_check_table(table, snapshot):
    dear = restamped(table, lambda t: ranking(t, "economy").append({"id": K3, "direct_id": None}))
    assert standalone(dear, snapshot) == [
        f"economy / CHAT / ranking: {K3} costs 13.5 per million output tokens,"
        " above the ceiling of 10"
    ]
    raised = restamped(dear, lambda t: t["presets"]["economy"].update(ceiling="14"))
    gates.check_table_standalone(raised, snapshot)  # the ceiling in force is unknown here
    with pytest.raises(gates.GateError, match="ceiling: economy is 14, above the 10 in force"):
        gates.check_table(raised, REQUIREMENTS, snapshot)


def test_the_other_table_rules_apply_unchanged(table, snapshot):
    with pytest.raises(gates.GateError, match="schema: "):
        gates.check_table_standalone({"schema": 1}, snapshot)
    stale = copy.deepcopy(table)
    ranking(stale).reverse()
    assert standalone(stale, snapshot) == [f"version: {table['version']} is not the content's"]
    alias = restamped(table, lambda t: ranking(t).append({"id": "~v/alias", "direct_id": None}))
    assert standalone(alias, snapshot) == [
        "balanced / CHAT / ranking: ~v/alias is an alias",
        "balanced / CHAT / ranking: ~v/alias is not in the snapshot",
    ]
    expiring = restamped(
        snapshot, lambda s: s["models"][QWEN]["metadata"].update(expiration_date="2026-10-09")
    )
    assert len(standalone(table, expiring)) == 3  # Qwen is ranked three times
    twice = restamped(table, lambda t: ranking(t).append(copy.deepcopy(ranking(t)[0])))
    assert standalone(twice, snapshot) == ["balanced / CHAT / ranking: an id is ranked twice"]
    wrong = restamped(table, lambda t: ranking(t)[1].update(direct_id="qwen3.8-max-0902"))
    assert standalone(wrong, snapshot) == [
        f"balanced / CHAT / ranking: {QWEN} carries the direct id qwen3.8-max-0902, not None"
    ]
