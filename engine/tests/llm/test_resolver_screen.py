"""Resolver v2: the screen and the scores, on the 2026-10-02 capture (brief D1–D3, AC 3).

`candidates.py` keeps the catalogue entries any role may rank — no variant,
alias, announced expiry or excluded family (matched on the id, the
`canonical_slug` and an alias's target), tools, the context, a fixed price,
an admitted endpoint — and admits endpoints by the provider policy (up, no
sub-8-bit quantization, tools, no flex tier, priced within the model-level
price × the margin). `impute.py` joins the Artificial Analysis records and
imputes a missing index from intelligence (D2). The capture's own numbers
are asserted where the brief states them; a synthetic entry isolates each
rule no real entry isolates.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from zylch.llm.roles import candidates, impute

from .resolver_fixture import (
    HAIKU,
    K3,
    OPUS,
    QWEN,
    READ_AT,
    SOL,
    SONNET,
    by_id,
    endpoint,
    entry,
    raw,
    requirements,
    sources,
)

FAMILY = {"vendor": "anthropic", "token": "haiku"}


def admitted_tags(model: str, req: dict | None = None) -> list[str]:
    src = sources()
    rules = candidates.policy(req or requirements())
    listed = candidates.admitted(by_id(src["catalogue"])[model], src["endpoints"][model], rules)
    return [e["tag"] for e in listed]


def screened(req: dict | None = None) -> tuple[list, dict]:
    src = sources()
    return candidates.screen(src["catalogue"], src["endpoints"], req or requirements())


def scored(req: dict | None = None) -> dict:
    req = req or requirements()
    kept, _ = screened(req)
    return impute.scored(kept, sources()["benchmarks"], {"intelligence", "agentic"}, req["common"])


# ------------------------------------------------------------ the capture


def test_the_capture_and_its_endpoint_pool():
    src = sources()
    assert src["read_at"] == READ_AT and len(src["catalogue"]) == 464
    pool = candidates.endpoint_pool(src["catalogue"], requirements()["common"])
    assert len(pool) == 218 == len(src["endpoints"])
    assert set(pool) == set(json.loads(raw()["endpoints"])["data"])
    assert not [m for m in pool if m.startswith("~") or ":" in m]


# --------------------------------------------------- endpoint admission


def test_premium_endpoints_are_refused_by_the_cap_and_vertex_us_admitted():
    assert "anthropic/fast" not in admitted_tags(OPUS)  # 40/M against 20 x 1.25
    assert "anthropic" in admitted_tags(OPUS)
    assert "openai/fast" not in admitted_tags(SOL)  # 20/M against 10 x 1.25
    assert {"google-vertex/us", "azure/us"} <= set(admitted_tags(SONNET))  # 11/M
    exact = requirements()
    exact["margin"] = 1
    assert not {"google-vertex/us", "azure/us"} & set(admitted_tags(SONNET, exact))


def test_sub_8_bit_quantizations_are_refused_and_undeclared_is_unknown():
    tags = admitted_tags(K3)
    assert {"morph/fp8", "deepinfra/bf16", "digitalocean", "together"} <= set(tags)
    src = sources()
    k3 = {e["tag"]: e for e in src["endpoints"][K3]}
    assert not [t for t in tags if k3[t]["quantization"] in ("fp4", "mxfp4", "nvfp4", "int4")]
    assert "inference-net/fp4" not in tags and "modal/mxfp4" not in tags
    rules = candidates.policy(requirements())
    model = entry()
    for quantization in ("fp4", "mxfp4", "nvfp4", "int4", "fp6"):
        assert not candidates.admitted(model, [endpoint(quantization=quantization)], rules)
    bare = endpoint()
    del bare["quantization"]
    assert candidates.admitted(model, [bare], rules) == [bare]
    rules["quantizations"] = [q for q in rules["quantizations"] if q != "unknown"]
    assert not candidates.admitted(model, [bare], rules)


def test_flex_tiers_are_refused_wherever_the_tag_puts_them():
    src = sources()
    assert "openai/flex" not in admitted_tags(SOL)  # the cheapest endpoint, at 5/M
    flex = [
        (model, e["tag"])
        for model, listed in src["endpoints"].items()
        for e in listed
        if "flex" in e["tag"].split("/")[1:]
    ]
    assert len(flex) == 45 and any(tag.count("/") == 2 for _, tag in flex)
    for model, tag in flex:
        assert tag not in admitted_tags(model)
    rules = candidates.policy(requirements())
    for tag in ("acme/flex", "acme/eu/flex"):
        assert not candidates.admitted(entry(), [endpoint(tag)], rules)
    assert candidates.admitted(entry(), [endpoint("acme/flexible")], rules)


def test_an_endpoint_down_or_without_tools_or_dear_is_refused():
    rules = candidates.policy(requirements())
    model = entry()
    refused = [
        endpoint(status=-2),
        endpoint(status=-5),
        endpoint(status=None),
        endpoint(status=False),
        endpoint(supported_parameters=["max_tokens"]),
        endpoint(pricing={"prompt": "0.000001", "completion": "0.0000025001"}),
        endpoint(pricing={"prompt": "0.0000012501", "completion": "0.000002"}),
        endpoint(pricing={"prompt": "-1", "completion": "-1"}),
        endpoint(tag=""),
    ]
    for one in refused:
        assert not candidates.admitted(model, [one], rules), one
    at_cap = endpoint(pricing={"prompt": "0.00000125", "completion": "0.0000025"})
    assert candidates.admitted(model, [at_cap], rules) == [at_cap]
    variable = entry(pricing={"prompt": "-1", "completion": "-1"})
    assert not candidates.admitted(variable, [endpoint()], rules)
    assert candidates.exclusion(variable, [endpoint()], requirements(), rules) == "no fixed price"


# ---------------------------------------------------------- the screen


def test_aliases_expiries_and_variants_are_screened_out():
    _, dropped = screened()
    assert dropped["~anthropic/claude-opus-latest"] == "an alias"
    assert dropped["qwen/qwen3-max"] == "expires on 2026-10-09"
    assert dropped[SONNET + ":batch"] == "a variant"
    assert {SONNET, OPUS, QWEN, K3, SOL}.isdisjoint(dropped)


def test_the_haiku_family_is_screened_out_on_id_slug_and_alias_target():
    src = sources()
    haiku = by_id(src["catalogue"])[HAIKU]
    assert haiku["canonical_slug"] == "anthropic/claude-4.5-haiku-20251001"
    _, dropped = screened()
    assert dropped[HAIKU] == "of the excluded family anthropic + haiku"
    # The slug alone: an id without the token, the real Haiku slug.
    renamed = entry("anthropic/claude-small-4.5", canonical_slug=haiku["canonical_slug"])
    assert candidates.family_of(renamed, [FAMILY]) == FAMILY
    rules = candidates.policy(requirements())
    reason = candidates.exclusion(renamed, [endpoint()], requirements(), rules)
    assert reason == "of the excluded family anthropic + haiku"
    # The alias target alone: an alias whose own id and slug lack the token.
    alias = entry("~anthropic/claude-small-latest", canonical_slug="~anthropic/claude-small-latest")
    alias["alias_target"] = {"name": "Anthropic: Claude Haiku 4.5", "slug": HAIKU}
    assert candidates.family_of(alias, [FAMILY]) == FAMILY
    real_alias = by_id(src["catalogue"])["~anthropic/claude-haiku-latest"]
    assert candidates.family_of(real_alias, [FAMILY]) == FAMILY
    # The vendor must match: the token under another vendor is no family.
    assert candidates.family_of(entry("acme/haiku-poet-1"), [FAMILY]) is None
    assert (
        candidates.exclusion(entry("acme/haiku-poet-1"), [endpoint()], requirements(), rules)
        is None
    )


def test_direct_ids_need_an_endpoint_tagged_anthropic():
    kept, _ = screened()
    rows = {row["id"]: row for row in kept}
    assert rows[SONNET]["direct_id"] == "claude-sonnet-5-5"
    assert rows["anthropic/claude-opus-4.1"]["direct_id"] is None  # Bedrock only
    assert rows[QWEN]["direct_id"] is None
    assert rows[OPUS]["price"] == Decimal(20) and rows[OPUS]["input_price"] == Decimal(4)


def test_a_model_with_no_admitted_endpoint_is_no_candidate():
    rules = candidates.policy(requirements())
    model = entry()
    assert candidates.exclusion(model, [endpoint(status=-2)], requirements(), rules) == (
        "no admitted endpoint"
    )
    assert candidates.exclusion(model, None, requirements(), rules) == (
        "its endpoints were not read"
    )


# ------------------------------------------------------------ the scores


def test_the_imputation_of_the_capture():
    result = scored()
    line = result["fits"]["agentic"]
    assert line["n"] == 95 and round(line["slope"], 3) == 1.318 and round(line["sd"], 2) == 4.69
    pool = {c["id"]: c for c in result["pool"]}
    for model, value in ((SONNET, 57.7), (OPUS, 59.8)):
        assert round(pool[model]["scores"]["agentic"], 1) == value
        assert pool[model]["imputed"] == {"agentic": line["sd"]}
    assert pool[QWEN]["scores"]["agentic"] == 56 and pool[QWEN]["imputed"] == {}


def test_the_agentic_order_under_each_ceiling_is_ac_3s():
    pool = scored()["pool"]

    def order(ceiling: int) -> list[str]:
        under = [c for c in pool if c["price"] <= ceiling and c["scores"]["agentic"] is not None]
        return [c["id"] for c in sorted(under, key=lambda c: (-c["scores"]["agentic"], c["price"]))]

    assert order(10)[:2] == [SONNET, QWEN]
    assert order(20)[:3] == [OPUS, SONNET, QWEN]


def test_unscored_models_are_listed_with_their_reason():
    result = scored()
    assert result["unscored"]["qwen/qwen3.8-max-prime"] == "no Artificial Analysis record"
    assert result["unscored"]["openai/gpt-5.4"] == "no intelligence index"
    assert not set(result["unscored"]) & {c["id"] for c in result["pool"]}
    kept, _ = screened()
    assert len(result["unscored"]) + len(result["pool"]) == len(kept)


def test_a_line_needs_three_records_and_a_spread():
    two = {"a": {"intelligence": 40, "agentic": 41}, "b": {"intelligence": 50, "agentic": 52}}
    assert impute.fit(two, "agentic") is None
    flat = {k: {"intelligence": 40, "agentic": v} for k, v in zip("abc", (40, 41, 42))}
    assert impute.fit(flat, "agentic") is None
    line = impute.fit({**two, "c": {"intelligence": 60, "agentic": 62}}, "agentic")
    assert line["n"] == 3 and line["slope"] == pytest.approx(1.05)


def test_ambiguous_slugs_score_nothing():
    record = {"source": "artificial-analysis", "model_permaslug": "acme/model-1-20260101"}
    record.update(intelligence_index=50, coding_index=None, agentic_index=None)
    other = {**record, "intelligence_index": 10}
    design = {**record, "source": "design-arena", "intelligence_index": 99}
    scores, ambiguous = impute.scores_by_slug([record, design])
    assert scores == {
        "acme/model-1-20260101": {"intelligence": 50, "coding": None, "agentic": None}
    }
    scores, ambiguous = impute.scores_by_slug([record, other])
    assert scores == {} and ambiguous == {"acme/model-1-20260101"}


# ------------------------------------------------------------ the payloads


def test_payloads_that_cannot_be_read_whole_are_refused():
    payload = json.loads(raw()["endpoints"])
    del payload["data"][QWEN]
    with pytest.raises(candidates.Refused, match=f"cannot read the endpoints of {QWEN}"):
        candidates.endpoints_by_model(json.dumps(payload).encode(), [QWEN, K3])
    for body, says in ((None, "no payload"), (b"<html>", "not JSON"), (b'{"data": []}', "object")):
        with pytest.raises(candidates.Refused, match=says):
            candidates.endpoints_by_model(body, [QWEN])
    doubled = {"data": [{"id": "acme/a"}, {"id": "acme/a"}], "total_count": 2}
    with pytest.raises(candidates.Refused, match="lists acme/a more than once"):
        candidates.complete_catalogue(doubled, doubled["data"])
    paged = {"data": [{"id": "acme/a"}], "links": {"next": "/page/2"}}
    with pytest.raises(candidates.Refused, match="came in pages"):
        candidates.complete_catalogue(paged, paged["data"])
