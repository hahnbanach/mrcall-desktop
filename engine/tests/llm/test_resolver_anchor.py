"""The price anchor: the reference price and the fallback (`candidates.anchored`).

A model's reference price is its model-level price — the list price
OpenRouter shows — whenever at least half the eligible endpoints (up, an
allowed quantization, tools, no excluded tier, a fixed price; ⌈n / 2⌉ of n)
are priced within it × the margin (the half rule and K3's pin:
`test_resolver_anchor_k3.py`). A median of the endpoints is not the first anchor because it
flips with the count of regional premiums: Anthropic sells Opus 5.5 at its
list price on five endpoints and 10% above it on five regional ones, and one
more region would move the median to the premium. OpenRouter computes the
model-level price over every endpoint, those the policy excludes included,
so an fp4 endpoint can set it below every eligible one: on the live read of
2026-10-02 17:24Z GLM 5.3 Flash's model-level price was its fp4 endpoint's
(0.02625/0.9) and no endpoint was admitted. Then, the fallback, the
reference price is the reference endpoint's — the lower median, index
(n - 1) // 2, of the eligible endpoints ordered by Artificial Analysis's
blended price (3 × input + output) / 4, a tie by output, then input, then
tag; its cache prices where it publishes them, else the model-level ones.
An eligible endpoint is admitted at or under the reference price × the
margin. A model whose endpoints were not read, or with none eligible, keeps
the model-level price and admits nothing; so does one whose model-level
price is absent or variable, since the fallback is for a fixed model-level
price only (OpenRouter itself cannot price `openrouter/auto` and the like,
which route to a model of their choosing). Each case isolates one of these
rules, on the 2026-10-02 capture (13:36Z) where it shows one and on
synthetic endpoints otherwise.
"""

from __future__ import annotations

from decimal import Decimal

from zylch.llm.roles import candidates, snapshot

from .resolver_fixture import K3, OPUS, by_id, endpoint, entry, requirements, sources

D = Decimal
GLM_FLASH, ALL_FP4 = "z-ai/glm-5.3-flash", "poolside/laguna-s-2.1"
KIMI_K2_6 = "moonshotai/kimi-k2.6"
SUB_8_BIT = ("fp4", "nvfp4", "mxfp4", "int4", "fp6")


def per_token(price: str) -> str:
    """A price per million tokens as the payloads write it, per token."""
    return format(D(price) / candidates.MILLION, "f")


def priced(tag: str, input_price: str, output_price: str, **fields) -> dict:
    """An eligible endpoint at `input_price`/`output_price` per million."""
    pricing = {"prompt": per_token(input_price), "completion": per_token(output_price)}
    return endpoint(tag, pricing=pricing, **fields)


def listed_at(input_price: str, output_price: str, **cache: str) -> dict:
    """A catalogue entry whose model-level price is `input_price`/`output_price`
    per million (and `cache_read` / `cache_write` when given)."""
    pricing = {"prompt": per_token(input_price), "completion": per_token(output_price)}
    for side, value in cache.items():
        pricing[f"input_{side}"] = per_token(value)
    return entry(pricing=pricing)


# A model-level price no endpoint below fits under (× 1.25): the fallback.
OUTLIER = ("0.01", "0.01")


def rules(margin: str | None = None) -> dict:
    policy = candidates.policy(requirements())
    return {**policy, "margin": D(margin)} if margin else policy


def test_a_model_level_price_set_by_an_fp4_outlier_takes_the_fallback():
    src = sources()
    glm, listed = by_id(src["catalogue"])[GLM_FLASH], src["endpoints"][GLM_FLASH]
    fp4 = next(e for e in listed if e["tag"] == "open-inference/fp4")
    # The live read's model-level price: its fp4 endpoint's.
    live = {
        **glm,
        "pricing": {**glm["pricing"], **{k: fp4["pricing"][k] for k in ("prompt", "completion")}},
    }
    assert candidates.model_price(live) == (D("0.02625"), D("0.9"))
    level = candidates.prices_of(live["pricing"])
    eligible = candidates.eligible(listed, rules())
    assert not [e for e, p in eligible if candidates.fits(p, level, D("1.25"))]
    price, admitted = candidates.anchored(live, listed, rules())
    assert (price["input"], price["output"]) == (D("0.15"), D("0.5"))
    assert len(admitted) == 20 and fp4 not in admitted
    assert not [e for e in admitted if candidates.quantization(e) in SUB_8_BIT]
    # The same shape on four endpoints.
    outlier = priced("outlier/fp4", "0.02625", "0.9", quantization="fp4")
    rest = [priced(f"p{n}/fp8", "0.15", "0.5") for n in range(2)]
    rest.append(priced("p2", "0.1", "0.4", quantization=None))
    price, admitted = candidates.anchored(listed_at("0.02625", "0.9"), [outlier, *rest], rules())
    assert (price["input"], price["output"]) == (D("0.15"), D("0.5")) and admitted == rest


def test_a_model_level_price_that_admits_half_the_endpoints_stays_the_reference():
    cheap, mid, dear = (
        priced("cheap", "0.5", "1"),
        priced("mid", "0.6", "1.2"),
        priced("dear", "3", "6"),
    )
    price, admitted = candidates.anchored(listed_at("1", "2"), [dear, mid, cheap], rules())
    # Two of three fit under it, at least half. Neither the cheapest (0.5/1)
    # nor the median (0.6/1.2): the list price.
    assert (price["input"], price["output"]) == (D(1), D(2))
    assert admitted == [mid, cheap]
    # K3 on the capture: morph/fp8 (2/11.357) is its cheapest eligible endpoint,
    # and anchored there the pinned digitalocean endpoint (2.55 in) would be shut out.
    src = sources()
    k3, listed = by_id(src["catalogue"])[K3], src["endpoints"][K3]
    rows = dict((e["tag"], p) for e, p in candidates.eligible(listed, rules()))
    assert min(rows, key=lambda tag: candidates.blended(rows[tag])) == "morph/fp8"
    assert (rows["morph/fp8"]["input"], rows["morph/fp8"]["output"]) == (D(2), D("11.357"))
    assert not candidates.fits(rows["digitalocean"], rows["morph/fp8"], D("1.25"))
    price, admitted = candidates.anchored(k3, listed, rules())
    assert (price["input"], price["output"]) == (D("2.7"), D("13.5"))
    assert len(admitted) == 10 and "digitalocean" in [e["tag"] for e in admitted]


def test_bimodal_list_and_regional_prices_keep_the_list_price_whatever_the_region_count():
    listed = [priced(f"list{n}", "4", "20") for n in range(5)]
    fast = priced("vendor/fast", "8", "40")
    for regions, median in ((5, D(20)), (6, D(22))):
        regional = [priced(f"region{n}", "4.4", "22") for n in range(regions)]
        # The median alone flips with one more region...
        rows = candidates.eligible([*listed, *regional], rules())
        assert candidates.reference(rows)[1]["output"] == median
        # ...the reference price does not, and the premium tier stays out.
        price, admitted = candidates.anchored(
            listed_at("4", "20"), [*listed, *regional, fast], rules()
        )
        assert (price["input"], price["output"]) == (D(4), D(20)), regions
        assert admitted == [*listed, *regional], regions
    # Opus 5.5 on the capture: five list, five regional and anthropic/fast.
    src = sources()
    price, admitted = candidates.anchored(
        by_id(src["catalogue"])[OPUS], src["endpoints"][OPUS], rules()
    )
    assert (price["input"], price["output"]) == (D(4), D(20)) and len(admitted) == 10
    assert "anthropic/fast" not in [e["tag"] for e in admitted]


def test_an_anti_correlated_pair_under_the_fallback_admits_its_reference():
    a, b = priced("vendor-a", "0.1", "1.0"), priced("vendor-b", "0.3", "0.2")
    price, admitted = candidates.anchored(listed_at(*OUTLIER), [a, b], rules())
    # Blended, B (0.275) is under A (0.325): the lower median of two is B.
    assert (price["input"], price["output"]) == (D("0.3"), D("0.2"))
    assert admitted == [b]  # A's output, 1.0, is above 0.2 x 1.25


def test_the_fallback_reference_is_the_lower_median_a_tie_by_output_then_input_then_tag():
    rows = [
        priced("z-out", "0.3", "0.1"),
        priced("b-mid", "0.2", "0.4"),
        priced("a-mid", "0.2", "0.4"),
        priced("y-out", "0.1", "0.7"),
    ]
    assert {candidates.blended(p) for _, p in candidates.eligible(rows, rules())} == {D("0.25")}
    # Ordered z-out, a-mid, b-mid, y-out: index (4 - 1) // 2 = 1, the lower middle.
    assert candidates.reference(candidates.eligible(rows, rules()))[0]["tag"] == "a-mid"
    # At one blended price a lower output is a higher input: output decides first.
    pair = candidates.eligible([rows[3], rows[0]], rules())
    assert candidates.reference(pair)[0]["tag"] == "z-out"
    odd = [*rows, priced("x-low", "0.1", "0.1")]  # blended 0.1: first of five
    assert candidates.reference(candidates.eligible(odd, rules()))[0]["tag"] == "a-mid"
    assert candidates.reference([]) is None
    price, _ = candidates.anchored(listed_at(*OUTLIER), rows, rules())
    assert (price["input"], price["output"]) == (D("0.2"), D("0.4"))


def test_the_blend_weighs_input_three_to_one():
    cheap_input = priced("cheap-input", "0.1", "1.0")  # blended 0.325
    cheap_output = priced("cheap-output", "0.4", "0.3")  # blended 0.375
    anchor = candidates.reference(candidates.eligible([cheap_output, cheap_input], rules()))
    assert anchor[0]["tag"] == "cheap-input"
    assert candidates.blended({"input": D("0.1"), "output": D("1.0")}) == D("0.325")


def test_the_reference_endpoint_is_always_admitted():
    rows = [priced("a", "1", "2"), priced("b", "1", "3"), priced("c", "2", "1")]
    # The fallback: blended 1.25, 1.5, 1.75, so the reference is b; even at a
    # margin of 1 it is admitted.
    price, admitted = candidates.anchored(listed_at(*OUTLIER), rows, rules("1"))
    assert (price["input"], price["output"]) == (D(1), D(3))
    assert admitted == rows[:2]
    # At the model-level price (a and b of three fit, at least half), an
    # endpoint priced exactly at the cap is admitted: b at 1/3.
    price, admitted = candidates.anchored(listed_at("1", "3"), rows, rules("1"))
    assert (price["input"], price["output"]) == (D(1), D(3)) and admitted == rows[:2]


def test_cache_prices_follow_the_reference():
    own = priced("acme", "1", "2")
    own["pricing"]["input_cache_read"] = per_token("0.2")
    # The model-level price is the reference: its cache prices too.
    price, _ = candidates.anchored(
        listed_at("1", "2", cache_read="0.1", cache_write="1.25"), [own], rules()
    )
    assert price == {
        "input": D(1),
        "output": D(2),
        "cache_read": D("0.1"),
        "cache_write": D("1.25"),
    }
    # The fallback: the reference endpoint's, else the model-level ones.
    outlier = listed_at(*OUTLIER, cache_read="0.1", cache_write="1.25")
    price, _ = candidates.anchored(outlier, [own], rules())
    assert price == {
        "input": D(1),
        "output": D(2),
        "cache_read": D("0.2"),
        "cache_write": D("1.25"),
    }


def test_an_unpooled_model_keeps_its_model_level_price():
    src = sources()
    built = snapshot.build(src["catalogue"], src["endpoints"], rules(), src["read_at"])
    for model in ("cohere/command-a-plus", "~anthropic/claude-opus-latest"):
        assert model not in src["endpoints"]
        assert built["models"][model]["endpoints"] is None
        assert built["models"][model]["pricing"] == snapshot.pricing(
            by_id(src["catalogue"])[model]["pricing"]
        )
    model = entry()
    assert candidates.anchored(model, None, rules()) == (
        candidates.prices_of(model["pricing"]),
        None,
    )
    # Pooled, Opus 5.5 is published at its model-level price, Kimi K2.6 at the fallback's.
    assert built["models"][OPUS]["pricing"]["output"] == "20"
    assert by_id(src["catalogue"])[KIMI_K2_6]["pricing"]["completion"] == "0.000001828"
    kimi = built["models"][KIMI_K2_6]
    assert (kimi["pricing"]["input"], kimi["pricing"]["output"]) == ("0.77", "3.4")


def test_a_variable_priced_pooled_model_stays_unpriced_and_admits_nothing():
    listed = [priced(f"acme{n}", "1", "2") for n in range(3)] + [priced("cheap", "0.5", "1")]
    assert len(candidates.eligible(listed, rules())) == 4
    variable = entry("router/auto", pricing={"prompt": "-1", "completion": "-1"})
    half = entry(pricing={"prompt": per_token("1"), "completion": "-1"})
    absent = entry(pricing={})
    for model in (variable, half, absent):
        price, admitted = candidates.anchored(model, listed, rules())
        assert price == candidates.prices_of(model["pricing"]) and admitted == [], model
        assert price["output"] is None
    # Published unpriced, no endpoint admitted: no cap a request could run under.
    built = snapshot.build([variable], {"router/auto": listed}, rules(), "2026-10-02T13:36:42Z")
    row = built["models"]["router/auto"]
    assert (row["pricing"]["input"], row["pricing"]["output"]) == (None, None)
    assert row["endpoints"] == []


def test_an_all_fp4_model_has_no_admitted_endpoint():
    src = sources()
    laguna, listed = by_id(src["catalogue"])[ALL_FP4], src["endpoints"][ALL_FP4]
    assert {candidates.quantization(e) for e in listed} == {"fp4"}
    assert candidates.anchored(laguna, listed, rules()) == (
        candidates.prices_of(laguna["pricing"]),
        [],
    )
    _, dropped = candidates.screen(src["catalogue"], src["endpoints"], requirements())
    assert dropped[ALL_FP4] == "no admitted endpoint"
    model = entry()
    quantized = [priced(f"q/{q}", "0.1", "0.2", quantization=q) for q in SUB_8_BIT]
    assert candidates.anchored(model, quantized, rules()) == (
        candidates.prices_of(model["pricing"]),
        [],
    )


def test_twenty_six_models_of_the_capture_take_the_fallback():
    src = sources()
    catalogue = by_id(src["catalogue"])

    def anchored(model: str) -> tuple[dict, list | None]:
        return candidates.anchored(catalogue[model], src["endpoints"][model], rules())

    def fitting(model: str) -> int:
        rows = candidates.eligible(src["endpoints"][model], rules())
        return sum(candidates.fits(p, level[model], D("1.25")) for _, p in rows)

    level = {m: candidates.prices_of(catalogue[m]["pricing"]) for m in src["endpoints"]}
    taken = sorted(m for m in src["endpoints"] if anchored(m)[0] != level[m])
    # Six whose model-level price admits no eligible endpoint...
    none = [m for m in taken if fitting(m) == 0]
    assert none == [
        "meta-llama/llama-4-scout",
        "moonshotai/kimi-k2.5",
        KIMI_K2_6,
        "qwen/qwen3-coder",
        "qwen/qwen3.5-122b-a10b",
        "z-ai/glm-4.6",
    ]
    # ...and twenty whose model-level price admits fewer than half of them.
    minority = [m for m in taken if m not in none]
    assert len(minority) == 20 and "z-ai/glm-5.2" in minority
    for model in minority:
        eligible = len(candidates.eligible(src["endpoints"][model], rules()))
        assert 0 < 2 * fitting(model) < eligible, model
    assert all(anchored(m)[1] for m in taken)
    price, admitted = anchored(KIMI_K2_6)
    assert (price["input"], price["output"]) == (D("0.77"), D("3.4")) and len(admitted) == 7
    # The screen ranks a model the fallback prices at its reference price.
    kept, _ = candidates.screen(src["catalogue"], src["endpoints"], requirements())
    row = next(r for r in kept if r["id"] == KIMI_K2_6)
    assert (row["input_price"], row["price"]) == (D("0.77"), D("3.4"))
