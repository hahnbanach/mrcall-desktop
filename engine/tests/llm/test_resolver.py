"""Resolver v2: requirements, measurement, rankings, the bootstrap and the record (brief D1, D4, D7, D8).

`zylch/llm/roles/resolver.py` ranks, per preset and role, the candidates of
`candidates.py` and `impute.py` that the role's measurement admits: maximise
roles the models that passed, by their index; satisfice roles the models at
or above the measured threshold, cheapest first; at most five; the
Anthropic subset beside. Without the measurement there is no ranking. Before
any threshold exists the bootstrap chooses the arms to measure. These cases
run on the 2026-10-02 capture with a synthetic `measured.json` (AC 3's
ordering) and on small synthetic pools for the rules. The script and its
exit codes are in `test_resolve_models_script.py`; 10a's resolver and its
kit differential moved to `resolver_10a.py` and `test_resolver_10a_kit.py`.
"""

from __future__ import annotations

import copy
import hashlib
from decimal import Decimal

import pytest
from zylch.llm.roles import gates, resolver, snapshot

from .resolver_fixture import HAIKU, K3, OPUS, QWEN, READ_AT, SONNET, requirements, sources

GLM, GROK, SOL = "z-ai/glm-5.3", "x-ai/grok-4.6", "openai/gpt-6.1-sol"
ROSTER = (
    "MNEMONIC MEMORY_EXTRACT MEMORY_MERGE TASK_DETECTION REANALYZE DEDUP REPLY_NEED INTENT CHAT"
    " TASK_SOLVE TRAIN COMPACTION SYNC_ANALYSIS WEB_SEARCH CORRECTION_LEARNING NARRATION"
).split()
SHA = hashlib.sha256(b"synthetic").hexdigest()


def outcome(passed=(), failed=(), threshold=None, measured_only=False) -> dict:
    results = {m: {"pass": True} for m in passed} | {m: {"pass": False} for m in failed}
    return {
        "threshold": threshold,
        "measured_only": measured_only,
        "results": results,
        "case_set_sha256": SHA,
        "prompt_sha256": SHA,
    }


def measured_all(req: dict) -> dict:
    """A synthetic measurement of every role: maximise roles passed by the
    capture's leaders, satisfice roles at a threshold of 40."""
    leaders = [SONNET, OPUS, QWEN, GLM, GROK, SOL, K3]
    roles = {}
    for role, rule in req["roles"].items():
        roles[role] = outcome(leaders) if rule["rule"] == "maximise" else outcome(threshold=40)
    return {"schema": 1, "roles": roles}


def capture_pool(req: dict | None = None) -> list[dict]:
    req = req or requirements()
    return resolver.pool(req, sources())["pool"]


def c(model: str, price, score, direct: str | None = None, index: str = "intelligence") -> dict:
    scores = {"intelligence": None, "coding": None, "agentic": None, index: score}
    return {
        "id": model,
        "price": Decimal(str(price)),
        "input_price": Decimal("1"),
        "direct_id": direct,
        "scores": scores,
        "imputed": {},
    }


def ids(rows: list[dict]) -> list[str]:
    return [row["id"] for row in rows]


MAX = {"rule": "maximise", "index": "intelligence"}
SAT = {"rule": "satisfice", "index": "intelligence"}


# ------------------------------------------------------- the requirements


def test_the_committed_requirements_are_v2s():
    req = resolver.validate_requirements(requirements())
    assert list(req["roles"]) == ROSTER
    assert all(set(rule) == {"rule", "index"} for rule in req["roles"].values())
    assert {k: v["ceiling"] for k, v in req["presets"].items()} == {"economy": 10, "balanced": 20}
    assert "excluded_prefixes" not in req["common"]
    assert req["excluded_families"] == [{"vendor": "anthropic", "token": "haiku"}]
    assert req["margin"] == 1.25 and req["excluded_endpoint_variants"] == ["flex"]
    quantizations = ["int8", "fp8", "mxfp8", "fp16", "bf16", "fp32", "unknown"]
    assert req["provider_policy"]["quantizations"] == quantizations
    assert req["reference"] == K3
    # 10a's readers keep their keys until the switch-over; the resolver ignores them.
    assert req["allowlist"] and req["mrcall_served"]


@pytest.mark.parametrize(
    "change, says",
    [
        (lambda r: r["roles"]["CHAT"].update(floor=40), "measured"),
        (lambda r: r["roles"]["CHAT"].update(index="speed"), "index must be"),
        (lambda r: r["presets"]["economy"].update(ceiling=None), "must be a price"),
        (lambda r: r.pop("margin"), "margin"),
        (lambda r: r.update(margin=0.9), "margin"),
        (lambda r: r.update(excluded_families=[{"vendor": "anthropic"}]), "excluded_families"),
        (lambda r: r["provider_policy"].update(quantizations=[]), "quantizations"),
        (lambda r: r.pop("excluded_endpoint_variants"), "excluded_endpoint_variants"),
        (lambda r: r.pop("reference"), "reference"),
        (lambda r: r["common"].update(required_scores=["speed"]), "required_scores"),
    ],
)
def test_requirements_the_resolver_cannot_read_are_refused(change, says):
    req = requirements()
    change(req)
    with pytest.raises(resolver.ConfigError, match=says):
        resolver.validate_requirements(req)


@pytest.mark.parametrize(
    "change, says",
    [
        (lambda m: m.update(schema=2), "schema"),
        (lambda m: m["roles"].update(SPEED=m["roles"]["CHAT"]), "not a role"),
        (lambda m: m["roles"]["CHAT"].update(threshold="40"), "threshold"),
        (lambda m: m["roles"]["CHAT"].pop("measured_only"), "measured_only"),
        (lambda m: m["roles"]["CHAT"]["results"].update({QWEN: {"pass": 1}}), "results"),
        (lambda m: m["roles"]["CHAT"].update(prompt_sha256="abc"), "prompt_sha256"),
    ],
)
def test_a_measurement_the_resolver_cannot_read_is_refused(change, says):
    req = requirements()
    measured = measured_all(req)
    resolver.validate_measured(copy.deepcopy(measured), req["roles"])
    change(measured)
    with pytest.raises(resolver.ConfigError, match=says):
        resolver.validate_measured(measured, req["roles"])


# ------------------------------------------------- AC 3 on the capture


def test_ac_3_the_agentic_order_on_the_capture():
    req = requirements()
    ranked = resolver.rankings(req, capture_pool(req), measured_all(req))
    for role in ("CHAT", "TASK_SOLVE"):
        economy = ranked["presets"]["economy"]["roles"][role]
        balanced = ranked["presets"]["balanced"]["roles"][role]
        assert ids(economy["ranking"]) == [SONNET, QWEN, GLM, GROK, SOL]
        assert round(economy["ranking"][0]["scores"]["agentic"], 1) == 57.7  # imputed
        assert economy["ranking"][1]["scores"]["agentic"] == 56
        assert ids(balanced["ranking"]) == [OPUS, SONNET, QWEN, GLM, GROK]
        assert round(balanced["ranking"][0]["scores"]["agentic"], 1) == 59.8
        assert ids(economy["anthropic_ranking"]) == [SONNET]
        assert ids(balanced["anthropic_ranking"]) == [OPUS, SONNET]
    assert ranked["blocked"] == [] and resolver.publishable(ranked) == []


def test_haiku_is_never_ranked_even_when_it_passes():
    req = requirements()
    measured = measured_all(req)
    measured["roles"]["CHAT"]["results"][HAIKU] = {"pass": True}
    ranked = resolver.rankings(req, capture_pool(req), measured)
    for body in ranked["presets"].values():
        for row in body["roles"].values():
            assert HAIKU not in ids(row["ranking"]) + ids(row["anthropic_ranking"])


# ------------------------------------------------------------- the rules


def test_maximise_ranks_only_passing_models_best_first_tie_to_the_cheaper():
    pool = [
        c("v/a-dear", 3, 60),
        c("v/z-cheap", 2, 60),
        c("v/best", 9, 70),
        c("v/unmeasured", 1, 99),
    ]
    measured = outcome(passed=["v/a-dear", "v/z-cheap", "v/best"], failed=[])
    assert ids(resolver.rank(MAX, pool, measured, Decimal(10))) == [
        "v/best",
        "v/z-cheap",
        "v/a-dear",
    ]
    assert ids(resolver.rank(MAX, pool, measured, Decimal(5))) == ["v/z-cheap", "v/a-dear"]
    tie = [c("v/b", 2, 60), c("v/a", 2, 60)]
    assert ids(resolver.rank(MAX, tie, outcome(passed=["v/a", "v/b"]), Decimal(10))) == [
        "v/a",
        "v/b",
    ]


def test_satisfice_ranks_cheapest_first_at_or_above_the_threshold():
    pool = [c("v/below", 0.1, 39), c("v/at", 0.5, 40), c("v/high", 0.5, 47), c("v/dear", 5, 90)]
    pool.append(c("v/failed", 0.2, 45))
    measured = outcome(threshold=40, failed=["v/failed"])
    assert ids(resolver.rank(SAT, pool, measured, Decimal(10))) == ["v/high", "v/at", "v/dear"]
    only = outcome(passed=["v/dear", "v/below"], measured_only=True)
    assert ids(resolver.rank(SAT, pool, only, Decimal(10))) == ["v/below", "v/dear"]
    assert resolver.rank(SAT, pool, outcome(), Decimal(10)) == []  # no threshold, no list


def test_a_ranking_holds_at_most_five():
    pool = [c(f"v/m{n}", n, 50 + n) for n in range(1, 9)]
    measured = outcome(passed=[m["id"] for m in pool])
    assert ids(resolver.rank(MAX, pool, measured, Decimal(10))) == [
        f"v/m{n}" for n in (8, 7, 6, 5, 4)
    ]


def test_the_anthropic_ranking_is_the_direct_subset_and_may_be_empty():
    req = {"presets": {"low": {"ceiling": 10}}, "roles": {"R": MAX}}
    pool = [c("v/x", 1, 80), c("anthropic/a-1", 5, 60, "a-1"), c("anthropic/b-1", 5, 70)]
    passed = {
        "schema": 1,
        "roles": {"R": outcome(passed=["v/x", "anthropic/a-1", "anthropic/b-1"])},
    }
    row = resolver.rankings(req, pool, passed)["presets"]["low"]["roles"]["R"]
    assert ids(row["ranking"]) == ["v/x", "anthropic/b-1", "anthropic/a-1"]
    assert ids(row["anthropic_ranking"]) == ["anthropic/a-1"]
    none = {"schema": 1, "roles": {"R": outcome(passed=["v/x"])}}
    ranked = resolver.rankings(req, pool, none)
    assert ranked["presets"]["low"]["roles"]["R"]["anthropic_ranking"] == []
    assert resolver.publishable(ranked) == []  # an empty Anthropic ranking is publishable


def test_no_ranking_without_the_measurement():
    req = requirements()
    ranked = resolver.rankings(req, capture_pool(req), None)
    assert ranked["blocked"] == ROSTER
    assert all(body["roles"] == {} for body in ranked["presets"].values())
    partial = measured_all(req)
    del partial["roles"]["NARRATION"]
    ranked = resolver.rankings(req, capture_pool(req), partial)
    assert ranked["blocked"] == ["NARRATION"]
    assert resolver.publishable(ranked) == ["measured.json does not cover NARRATION"]


def test_the_ceiling_raise_is_reported_and_never_published():
    req = {
        "presets": {"low": {"ceiling": 2}, "high": {"ceiling": 20}},
        "roles": {"R": MAX, "S": SAT},
    }
    pool = [c("v/a", 4, 60), c("v/b", 9, 70), c("v/cheap", 1, 41)]
    measured = {
        "schema": 1,
        "roles": {"R": outcome(passed=["v/a", "v/b"]), "S": outcome(threshold=40)},
    }
    ranked = resolver.rankings(req, pool, measured)
    low, high = ranked["presets"]["low"], ranked["presets"]["high"]
    assert low["raised_to"] == Decimal(4) and high["raised_to"] is None
    assert ids(low["roles"]["R"]["ranking"]) == ["v/a"]
    assert resolver.publishable(ranked) == [
        "low's ceiling of 2 would be raised to 4, and a raised ceiling is never published"
    ]


def test_a_role_no_measured_model_qualifies_for_blocks_the_table():
    req = {"presets": {"low": {"ceiling": 10}}, "roles": {"R": MAX}}
    ranked = resolver.rankings(req, [c("v/a", 1, 60)], {"schema": 1, "roles": {"R": outcome()}})
    assert resolver.publishable(ranked) == ["low: no measured model qualifies for R"]


def test_refused_when_a_role_has_no_candidate_at_any_price():
    req = requirements()
    req["common"]["min_context"] = 10**9
    with pytest.raises(resolver.Refused, match="no candidate at any price for MNEMONIC"):
        resolver.pool(req, sources())


# --------------------------------------------------------- the bootstrap


def arms(boot: dict, role: str) -> dict:
    return {arm["id"]: arm["why"] for arm in boot["roles"][role]["arms"]}


def test_the_bootstrap_arms_on_the_capture():
    req = requirements()
    boot = resolver.bootstrap(req, capture_pool(req))
    assert boot["reference"] == K3
    chat = arms(boot, "CHAT")
    assert list(chat) == [SONNET, QWEN, GLM, OPUS, K3]
    assert chat[OPUS] == ["top 3 under balanced", "first Anthropic under balanced"]
    assert chat[K3] == ["reference"]
    mnemonic = arms(boot, "MNEMONIC")
    assert list(mnemonic) == [SONNET, SOL, "openai/gpt-6-sol", OPUS, K3]
    ladder = arms(boot, "MEMORY_EXTRACT")
    assert len(ladder) == 6 and list(ladder)[-1] == K3
    assert all(why[0].startswith("ladder step") for model, why in ladder.items() if model != K3)
    every = {model for role in ROSTER for model in arms(boot, role)}
    assert not [m for m in every if "haiku" in m]


def test_an_excluded_family_is_never_an_arm_even_scored_best():
    best = sources()
    for record in best["benchmarks"]:
        if record.get("model_permaslug") == "anthropic/claude-4.5-haiku-20251001":
            record["intelligence_index"] = 99
    req = requirements()
    boot = resolver.bootstrap(req, resolver.pool(req, best)["pool"])
    assert HAIKU not in {m for role in ROSTER for m in arms(boot, role)}
    req["excluded_families"] = []
    loose = resolver.bootstrap(req, resolver.pool(req, best)["pool"])
    assert arms(loose, "MNEMONIC")[HAIKU] == [
        "top 3 under economy",
        "first Anthropic under economy",
        "top 3 under balanced",
        "first Anthropic under balanced",
    ]


def test_the_first_anthropic_candidate_joins_the_maximise_arms():
    req = {"presets": {"low": {"ceiling": 10}}, "roles": {"R": MAX}, "reference": "v/ref"}
    pool = [c(f"v/m{n}", 1, 90 - n) for n in range(4)] + [c("anthropic/x-1", 1, 50, "x-1")]
    boot = resolver.bootstrap(req, pool)
    assert arms(boot, "R") == {
        "v/m0": ["top 3 under low"],
        "v/m1": ["top 3 under low"],
        "v/m2": ["top 3 under low"],
        "anthropic/x-1": ["first Anthropic under low"],
        "v/ref": ["reference"],
    }
    assert boot["roles"]["R"]["arms"][-1]["candidate"] is None  # the reference is not in the pool


def test_the_ladder_widens_its_step_until_six_models_remain():
    pool = [c(f"v/s{score}", score / 100, score) for score in range(10, 70, 5)]
    rungs = resolver.ladder(pool, "intelligence", Decimal(10))
    assert [floor for _, floor in rungs] == [10, 20, 30, 40, 50, 60]
    assert [m["id"] for m, _ in rungs] == ["v/s10", "v/s20", "v/s30", "v/s40", "v/s50", "v/s60"]
    few = [c(f"v/f{score}", score / 100, score) for score in (10, 15, 20)]
    assert [floor for _, floor in resolver.ladder(few, "intelligence", Decimal(10))] == [10, 15, 20]


# ---------------------------------------------------------- the record


def test_the_table_passes_the_gates_and_its_decision_ignores_prices():
    req = requirements()
    src = sources()
    ranked = resolver.rankings(req, resolver.pool(req, src)["pool"], measured_all(req))
    stamps = dict(resolved_at=READ_AT, catalogue_read_at=READ_AT)
    stamps.update(requirements_sha256=SHA, measured_sha256=SHA)
    table = resolver.document(ranked, stamps)
    rules = resolver.candidates.policy(req)
    snap = snapshot.build(src["catalogue"], src["endpoints"], rules, src["read_at"])
    gates.check_snapshot(snap)
    gates.check_table(table, req, snap)
    assert table["presets"]["economy"]["ceiling"] == "10"
    chat = table["presets"]["economy"]["roles"]["CHAT"]
    assert chat["ranking"][0] == {"id": SONNET, "direct_id": "claude-sonnet-5-5"}
    assert chat["ranking"][1] == {"id": QWEN, "direct_id": None}
    cheaper = sources()
    k3 = next(e for e in cheaper["catalogue"] if e["id"] == K3)
    k3["pricing"]["completion"] = "0.0000136"
    again = resolver.rankings(req, resolver.pool(req, cheaper)["pool"], measured_all(req))
    assert resolver.decision(resolver.document(again, stamps)) == resolver.decision(table)
    moved = copy.deepcopy(table)
    moved["presets"]["economy"]["roles"]["CHAT"]["ranking"].reverse()
    assert resolver.decision(moved) != resolver.decision(table)
